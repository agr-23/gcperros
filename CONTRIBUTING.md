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
| `pytest` | 40 pruebas: determinismo, contrato, xG y plausibilidad estadística |
| `pre-commit run --all-files` | Todo lo anterior más el escaneo de secretos |

Las comprobaciones de Terraform (`terraform fmt -check`, `terraform validate`)
corren solo en CI, para no exigir el binario instalado a todo el equipo.

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
2. **El generador no incorpora dependencias externas.** Solo biblioteca
   estándar: cualquier paquete de terceros introduce una versión más que podría
   alterar el muestreo pseudoaleatorio y romper la reproducibilidad.
3. **Nada de `random` global, `uuid4` ni `datetime.now()`** en el código de
   generación. Los tres rompen el determinismo bajo semilla fija, que es la
   premisa sobre la que se apoya toda la validación del proyecto.
4. **Un cambio en las constantes del simulador exige revisar la calibración.**
   Las pruebas marcadas `statistical` acotan los agregados del partido contra
   los rangos del dominio; si fallan, el simulador dejó de ser plausible.
