# Cómo trabajar en este repositorio

## Preparar el entorno

```bash
make setup
```

Crea el entorno virtual, instala las dependencias y engancha `pre-commit`. Ese
último paso es el que suele olvidarse, y es el que más cuesta: sin él los
ganchos no corren, los fallos aparecen en integración continua en vez de antes
del commit, y hay que arreglarlos con la rama ya publicada.

Si se añade un gancho nuevo al proyecto, hay que volver a engancharlos —
`pre-commit install` solo instala los tipos que existían cuando se ejecutó:

```bash
make hooks
```

## Comprobaciones

Lo mismo que corre la CI, en local:

| Comando | Qué comprueba |
|---|---|
| `ruff check .` | Errores, imports, nombres, seguridad, docstrings |
| `ruff format .` | Formato |
| `mypy` | Tipos en modo estricto, sobre `src` y `tests` |
| `pytest` | La suite completa: unitarias por componente y de tubería |
| `pytest --cov=gcperros --cov-fail-under=90` | Lo mismo con el umbral de cobertura de la CI |
| `pre-commit run --all-files` | Todo lo anterior más el escaneo de secretos |
| `make check` | Todo lo de esta tabla de una vez |
| `python scripts/tamano_pr.py` | Que el cambio no supere los 250 deltas |

Las comprobaciones de Terraform (`terraform fmt -check`, `terraform validate`)
corren solo en CI, para no exigir el binario instalado a todo el equipo.

La CI revisa además, en un trabajo aparte, si alguna dependencia arrastra una
vulnerabilidad conocida (`pip-audit`). No está en el extra de desarrollo porque
arrastra bastante equipaje para lo poco que se usa; para reproducirlo en local
basta `pipx run pip-audit --desc`. Ese trabajo **no bloquea la fusión** a
propósito: una vulnerabilidad en una dependencia de desarrollo no la arregla
quien abre el pull request, y bloquear por algo que el autor no puede resolver
convierte el aviso en ruido que se acaba ignorando.

La CI además ejecuta las pruebas en **Windows y Linux**: el proyecto promete
ficheros idénticos byte a byte en cualquier sistema operativo, y sin comprobarlo
en ambos esa promesa sería una suposición.

## Mensajes de commit

Se usa [Conventional Commits](https://www.conventionalcommits.org/), validado
por `commitizen` en el gancho `commit-msg` y de nuevo en CI sobre los commits de
cada pull request.

```
feat(generators): generador determinista de eventos de partido
fix(engine): deduplicar antes de aplicar el evento al estado
docs(infra): explicar la decisión sobre message ordering
test(generators): cubrir la salida del balón por línea de fondo
chore(ci): fijar la versión de terraform
```

Tipos admitidos: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`,
`build`, `ci`, `chore`. Si el commit cierra una historia, referénciala en el
cuerpo (`HU-8`): es lo que sostiene la trazabilidad que exige el eje de
gobernanza.

### El gitmoji se pone solo

El asunto lleva delante el icono de [gitmoji](https://gitmoji.dev) que
corresponde a su tipo, pero **no hay que escribirlo**: el tipo ya determina cuál
es, y `scripts/gitmoji.py` lo antepone en el gancho `prepare-commit-msg`, antes
de que se abra el editor.

```
escribes:  feat(engine): deduplicar antes de aplicar
se graba:  ✨ feat(engine): deduplicar antes de aplicar
```

| | | | | | |
|---|---|---|---|---|---|
| ✨ `feat` | 🐛 `fix` | 📝 `docs` | 🎨 `style` | ♻️ `refactor` | ⚡️ `perf` |
| ✅ `test` | 📦️ `build` | 👷 `ci` | 🔧 `chore` | ⏪️ `revert` | 🔖 `bump` |

Si ya lo escribiste, no se duplica. Si el asunto no sigue la convención, no se
toca: rechazarlo es trabajo de `commitizen`, que lo explica mejor.

El icono es **opcional para el validador**, de modo que los commits anteriores a
esta convención siguen pasando: reescribir historia ya publicada por un icono
sería peor que no tenerlo. Pero la integración continua sí lo exige en los
commits nuevos de cada pull request, para quien no tenga los ganchos
instalados.

## Reglas que no son negociables

1. **Nada de credenciales en el repositorio.** Ni llaves JSON de service
   account, ni `terraform.tfvars`, ni ficheros `.env`. Para hablar con GCP se
   usa suplantación de service account. `gitleaks` corre en cada commit.
2. **El generador y el motor no incorporan dependencias externas.** Solo
   biblioteca estándar: cualquier paquete de terceros introduce una versión más
   que podría alterar el muestreo pseudoaleatorio y romper la reproducibilidad.
   El cliente de Pub/Sub es la excepción, y por eso es un extra opcional
   (`pip install -e '.[pubsub]'`) que se importa de forma diferida: quien solo
   genere ficheros no tiene por qué instalarlo.
3. **Nada de `random` global, `uuid4` ni `datetime.now()`** en el código de
   generación. Los tres rompen el determinismo bajo semilla fija, que es la
   premisa sobre la que se apoya toda la validación del proyecto.
4. **Un cambio en las constantes del simulador exige revisar la calibración.**
   Las pruebas marcadas `statistical` acotan los agregados del partido contra
   los rangos del dominio; si fallan, el simulador dejó de ser plausible, y hay
   que actualizar la tabla de [docs/decisiones-de-diseno.md](docs/decisiones-de-diseno.md).
5. **Si cambia la huella de referencia, se explica.** `tests/test_pipeline.py`
   guarda el SHA-256 de la salida de la semilla de referencia. Que falle no es
   necesariamente un error —una recalibración legítima la cambia— pero nunca
   debe pasar sin querer: se actualiza a propósito y se dice por qué en el
   commit.
6. **Nada de `type: ignore` ni `noqa` sin discutirlo.** Ahora mismo el repo no
   tiene ninguno. Las excepciones reales se declaran en `pyproject.toml`, con su
   justificación al lado, donde todo el equipo las ve.
7. **Un pull request no pasa de 250 deltas**, contando líneas añadidas más
   borradas: código, pruebas y documentación. Un cambio más grande no se
   revisa, se hojea, y entra con la misma ceremonia que uno revisado.

   Se comprueba **antes del push** —el gancho `pre-push` lo mide contra
   `origin/main`— y otra vez en integración continua. Para verlo a mano en
   cualquier momento: `python scripts/tamano_pr.py`.

   Cuando un cambio tiene que ir junto de verdad, la excepción se declara y se
   ve: etiqueta el pull request como `pr-grande`, o exporta
   `GCPERROS_PR_GRANDE=1` para saltarlo en local. Una regla sin salida
   declarada acaba desactivada entera la primera vez que estorba.
8. **Un cambio en el contrato de datos exige versionarlo.** El esquema formal de
   los dos flujos vive en `src/gcperros/core/schema.py` y la frontera lo hace
   cumplir. Añadir un campo opcional es el único cambio que no rompe a nadie;
   todo lo demás —renombrar, cambiar un tipo, ampliar un vocabulario cerrado,
   o cambiar lo que un campo significa sin cambiar su forma— obliga a subir
   `contract_version`. La tabla completa está en la sección 7 de
   [docs/decisiones-de-diseno.md](docs/decisiones-de-diseno.md).

## Dónde está documentado el porqué

El código explica **qué** hace y las decisiones no obvias que lo condicionan.
El razonamiento largo —alternativas descartadas, tablas de calibración, tensiones
sin resolver— vive en
[docs/decisiones-de-diseno.md](docs/decisiones-de-diseno.md), que es su única
fuente. Si una tabla aparece en dos sitios, uno de los dos acabará mintiendo.
