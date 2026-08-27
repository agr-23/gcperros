# Cómo trabajar en este repositorio

## Preparar el entorno

```bash
python -m venv .venv
source .venv/Scripts/activate      # en Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install --install-hooks
```

`pre-commit install` es el paso que suele olvidarse. Sin él los ganchos no se
ejecutan y los fallos aparecen en integración continua en vez de antes del
commit.

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

Las comprobaciones de Terraform (`terraform fmt -check`, `terraform validate`)
corren solo en CI, para no exigir el binario instalado a todo el equipo.

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
7. **Un cambio en el contrato de datos exige versionarlo.** El esquema formal de
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
