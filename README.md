# GCPerros — Pipeline de Streaming de Datos Deportivos

[![CI](https://github.com/agr-23/gcperros/actions/workflows/ci.yml/badge.svg)](https://github.com/agr-23/gcperros/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)
[![Pruebas](https://img.shields.io/badge/pruebas-412-brightgreen)](tests/)
[![Cobertura](https://img.shields.io/badge/cobertura-97%25-brightgreen)](pyproject.toml)

Ingerimos dos flujos de eventos —las acciones de un partido de fútbol y las
actualizaciones de cuotas de varias casas de apuestas— y los convertimos, en
tiempo real, en indicadores del partido y señales de apoyo a la decisión.

El problema de fondo no es el fútbol: es que el broker entrega **al menos una
vez y sin orden**. Todo el proyecto gira alrededor de convertir eso en un
resultado correcto y auditable.

**SI4002 · Proyecto de Ingeniería de Datos · EAFIT · 2026-2**
Prof. Jose Fabio Jaramillo Castro

| Integrante | Rol | Historias |
|---|---|---|
| Jean Carlo Londoño | Ingeniero de Pipelines / Big Data | HU-8 a HU-13 |
| Tomás Londoño | Arquitecto de Datos / Cloud | HU-14, HU-15 |
| Alejandro Garcés | Oficial de Gobernanza / Líder DataOps | HU-16 a HU-18 |

> **Uso responsable.** Proyecto estrictamente académico. El sistema es una
> herramienta de apoyo a la decisión informada: no ejecuta apuestas, no
> intermedia en el juego y no promete rentabilidad alguna. Los datos del dominio
> deportivo son sintéticos.

---

## Recorrido en cinco minutos

Todo lo que sigue corre **sin cuenta de GCP y sin credenciales**. Es a propósito:
queríamos poder desarrollar y demostrar el pipeline completo mientras se
resolvía el acceso a la nube.

```bash
python -m venv .venv
source .venv/Scripts/activate      # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
```

**1. Generar un partido.** La misma semilla produce siempre el mismo partido,
byte por byte.

```bash
gcperros-generate-match --seed 20260826 --out partido.jsonl --summary
```
```
eventos=1197 goles={'HOME': 4, 'AWAY': 0} xG={'HOME': 0.9751, 'AWAY': 0.7814}
remates={'HOME': 16, 'AWAY': 11} rojas={'HOME': 0, 'AWAY': 0} posesiones={'HOME': 110, 'AWAY': 111}
```

**2. Generar las cuotas de ese mismo partido.** Tres casas sintéticas que
reaccionan a los goles y las expulsiones.

```bash
gcperros-generate-odds --seed 20260826 --out cuotas.jsonl --summary
```
```
actualizaciones=93 disparadores={'open': 6, 'drift': 63, 'heartbeat': 9, 'goal': 15}
operadores={'OP-A': 31, 'OP-B': 30, 'OP-C': 32} overround={'1x2': 1.0557, 'over_under_2_5': 1.0472}
```

**3. Publicar hacia el broker.** `--dry-run` recorre el camino completo de
publicación sin salir del proceso, así que no hace falta broker ni credenciales.

```bash
gcperros-publish --seed 20260826 --dry-run
```

**4. La frontera de contrato.** Deja pasar lo conforme y aísla el resto con su
causa registrada.

```bash
gcperros-validate --stream match --in partido.jsonl --invalid invalidos.jsonl
```

**5. El informe de calidad de esa ingestión.**

```bash
gcperros-quality --stream match --in partido.jsonl
```
```
calidad=PASA alcance=match-events
  ok  completeness 1.0000 (minimo 0.99) sobre 1197 mensajes
  ok  uniqueness   1.0000 (minimo 0.9) sobre 1197 mensajes
  ok  timeliness   1.0000 (minimo 0.95) sobre 1197 mensajes
```

**6. De dónde sale un número.** Qué eventos lo formaron y qué versión del modelo
lo calculó.

```bash
gcperros-trace --in partido.jsonl --indicator total_xg --scope HOME
```
```
explicado total_xg de HOME
{"indicator":"total_xg","value":0.9751,"scope":"HOME",
 "lineage":{"event_count":16,"digest":"11c1f06e…","sample":["129c89ee-…","1ce6ad93-…"]},
 "model_versions":{"xg":"xg-1.0.0"}}
```

**7. La capa histórica.** Persiste cada mensaje sin transformar.

```bash
gcperros-load-raw --dry-run --stream match --in partido.jsonl
```

---

## Cómo está montado

```
Generadores sintéticos          (fuera de GCP, costo cero)
        │
        ▼
Pub/Sub · match-events + odds-updates        ← capa de ingestión
        │
        ▼
Frontera de contrato ──▶ repositorio de inválidos   ← rechaza antes de gastar
        │
        ▼
Cloud Run · motor con estado                 ← dedup, watermark, ventanas
        │
        ├──▶ Firestore   · estado vivo por partido
        └──▶ BigQuery    · histórico y calibración
                    │
                    ▼
            Dashboard (fuera de GCP)
```

La entrega *at-least-once* y sin orden es **premisa de diseño**, no un defecto
que sufrimos. La deduplicación por `event_id` y el reordenamiento por marca de
agua viven en el motor porque son el objeto de estudio del proyecto, no un
parche.

Así se encadena todo desde Python:

```python
from pathlib import Path

from gcperros.engine.pipeline import MatchEngine
from gcperros.governance.gate import match_event_gate
from gcperros.governance.quarantine import JsonlInvalidStore

# Nada llega al motor sin haber cumplido el contrato primero.
gate = match_event_gate(JsonlInvalidStore(Path("invalidos.jsonl")))
delivered = gate.admit_all(raw_messages)   # lo no conforme queda archivado

engine = MatchEngine()
for event in delivered:        # con duplicados y desordenados
    engine.process(event)      # -> ACCEPTED | DUPLICATE | DROPPED_LATE
engine.flush()

engine.result().summary              # indicadores del partido
engine.dedup_stats.duplicates        # repeticiones suprimidas
engine.watermark_stats.timeliness    # proporción aplicada dentro de plazo
```

---

## Si sólo vas a mirar cinco ficheros

| Fichero | Por qué este |
|---|---|
| [`core/contracts.py`](src/gcperros/core/contracts.py) | El contrato de los dos flujos. Todo lo demás depende de él |
| [`generators/match.py`](src/gcperros/generators/match.py) | El partido como secuencia de posesiones, con la calibración documentada en el docstring |
| [`engine/pipeline.py`](src/gcperros/engine/pipeline.py) | Los tres pasos del motor y por qué ese orden no es negociable |
| [`engine/watermark.py`](src/gcperros/engine/watermark.py) | El compromiso entre latencia y completitud, con el margen elegido a partir de mediciones |
| [`governance/gate.py`](src/gcperros/governance/gate.py) | La frontera: qué entra, qué se aísla y con qué causa |
| [`tests/test_pipeline.py`](tests/test_pipeline.py) | La prueba de que las piezas encajan, no sólo de que cada una funciona |

Y si quieres el razonamiento largo en un solo sitio:
**[`docs/decisiones-de-diseno.md`](docs/decisiones-de-diseno.md)** recoge cada
decisión no obvia con la alternativa que descartamos y la medición que la
sostiene.

---

## Historia → código → prueba

| Historia | Tablero | Qué hace | Código | Prueba | Estado |
|---|---|---|---|---|---|
| HU-8 | H-001 | Generador determinista de partido | [`generators/match.py`](src/gcperros/generators/match.py) | [`test_determinism.py`](tests/test_determinism.py) | ✅ |
| HU-9 | H-002 | Cuotas que reaccionan al partido | [`generators/odds.py`](src/gcperros/generators/odds.py) | [`test_odds_generator.py`](tests/test_odds_generator.py) | ✅ |
| HU-10 | H-003 | Publicación con reintento y registro | [`publishing/publisher.py`](src/gcperros/publishing/publisher.py) | [`test_publisher.py`](tests/test_publisher.py) | ✅ |
| HU-11 | H-004 | Deduplicación por `event_id` | [`engine/dedup.py`](src/gcperros/engine/dedup.py) | [`test_dedup.py`](tests/test_dedup.py) | ✅ |
| HU-12 | H-005 | Reordenamiento por marca de agua | [`engine/watermark.py`](src/gcperros/engine/watermark.py) | [`test_watermark.py`](tests/test_watermark.py) | ✅ |
| HU-13 | H-006 | Infraestructura declarada en Terraform | [`infra/terraform/pubsub.tf`](infra/terraform/pubsub.tf) | CI: `terraform validate` | ✅ sin desplegar |
| HU-14 | H-007 | Capa Raw en BigQuery | [`loading/raw_loader.py`](src/gcperros/loading/raw_loader.py) | [`test_raw_loader.py`](tests/test_raw_loader.py) | ✅ sin desplegar |
| HU-15 | H-008 | Estado vivo en Firestore | [`firestore/document.py`](src/gcperros/firestore/document.py) | [`test_live_document.py`](tests/test_live_document.py) | ✅ sin desplegar |
| HU-16 | H-009 | Contrato formal y repositorio de inválidos | [`governance/validation.py`](src/gcperros/governance/validation.py) | [`test_validation.py`](tests/test_validation.py) | ✅ |
| HU-17 | H-010 | Reglas de calidad sobre lo ingerido | [`governance/quality.py`](src/gcperros/governance/quality.py) | [`test_quality.py`](tests/test_quality.py) | ✅ |
| HU-18 | H-011 | Trazabilidad de los indicadores | [`governance/traceability.py`](src/gcperros/governance/traceability.py) | [`test_traceability.py`](tests/test_traceability.py) | ✅ |
| HU-19 | — | Señal de discrepancia con el mercado | — | — | ⏳ Sprint 2 |

El tablero numera las mismas historias con un desfase de siete (`H-00N` es
`HU-(N+7)`). El código y los commits usan `HU-N`, que es la numeración con la que
nació el repositorio; esta tabla es la única traducción entre ambas, para que
nadie tenga que deducirla comparando títulos.

---

## Cómo sabemos que funciona

**412 pruebas, 97 % de cobertura.** Pero el número que importa no es ese, sino
qué vigila cada familia:

| Familia | Qué protege |
|---|---|
| Determinismo | La misma semilla da los mismos bytes. Sin esto, comparar streaming contra batch no probaría nada |
| Contrato | Todo mensaje emitido cumple el esquema que declaramos, y lo que no cumple se rechaza nombrando la causa |
| Estadística | Los agregados del partido caen en los rangos de referencia del dominio. Si alguien cambia una constante y el partido deja de ser plausible, falla |
| Tubería | Generar → publicar → leer → procesar produce lo mismo que el plano batch, incluso con duplicados y desorden a la vez |
| Huellas congeladas | El SHA-256 de la salida de referencia. Si cambia, hay que actualizarlo **a propósito** y explicar por qué en el commit |

La integración continua corre en cada push ([`ci.yml`](.github/workflows/ci.yml)):

- **Linters y ganchos** — `ruff`, y `gitleaks` buscando credenciales filtradas.
- **Tipos y pruebas** — `mypy` en modo estricto y la suite completa en Python
  3.11, 3.12 y 3.13 sobre Linux, **más Windows**. Prometemos ficheros idénticos
  byte a byte en cualquier sistema operativo; sin comprobarlo en los dos sería
  una suposición.
- **Reproducibilidad** — genera el mismo partido dos veces y compara con `cmp`;
  valida que ambos flujos cumplen su propio contrato; corre el informe de calidad
  y la trazabilidad en modo estricto.
- **Terraform** — `fmt -check`, `init` y `validate` sin credenciales.

En todo el repositorio no hay **ni un solo `type: ignore` ni `noqa`**. Las
excepciones reales están declaradas en [`pyproject.toml`](pyproject.toml) con su
justificación al lado, donde todo el equipo las ve.

---

## Estructura

```
src/gcperros/core/          Dominio compartido: contratos, esquema, campo, xG, cuotas, linaje
src/gcperros/generators/    Generadores sintéticos e inyector de perturbaciones
src/gcperros/publishing/    Publicación hacia el broker
src/gcperros/governance/    Frontera de contrato, inválidos, calidad y trazabilidad
src/gcperros/engine/        Motor con estado: dedup, marca de agua, estado vivo
src/gcperros/loading/       Capa histórica Raw hacia BigQuery
src/gcperros/firestore/     Documento de estado vivo por partido
tests/                      Unitarias por componente y de tubería completa
infra/terraform/            Infraestructura como código
docs/                       Decisiones de diseño con su evidencia
```

`core/` existe por una razón concreta: el generador y el motor tienen que
compartir **el mismo** modelo de xG y **la misma** matemática de cuotas. Si
fueran dos implementaciones distintas, comparar los dos planos no probaría nada.

---

## Lo que todavía no está

Preferimos decirlo aquí a que se descubra leyendo:

- **Nada está desplegado en GCP.** El Terraform está escrito y validado en CI,
  pero nunca se ha ejecutado `apply`: hace falta un proyecto con facturación, y
  el plan del proyecto contempla usar créditos educativos.
- **HU-19** (la señal de discrepancia entre nuestro modelo y el mercado) es del
  Sprint 2. La matemática ya está lista en
  [`core/odds.py`](src/gcperros/core/odds.py); falta el emisor de señales.
- **Una tensión sin resolver.** El margen de la marca de agua que cumple los
  umbrales de divergencia (10 s) choca con el SLA de latencia p95 < 2 s que
  declaramos. No se pueden cumplir los dos con este diseño. Está medido y
  documentado en [`docs/decisiones-de-diseno.md`](docs/decisiones-de-diseno.md),
  sección 3, y resolverlo corresponde al sprint que caracteriza la latencia bajo
  carga.

---

## Sin cuenta de nube

Para publicar contra un broker de verdad sin cuenta de GCP existe el emulador
oficial de Pub/Sub:

```bash
gcloud components install pubsub-emulator      # necesita Java 11 o superior
gcloud beta emulators pubsub start --project=gcperros-local

export PUBSUB_EMULATOR_HOST=localhost:8085
gcperros-publish --seed 20260826 --project gcperros-local --create-topics
```

El mismo código publica en GCP en cuanto se quita esa variable.

---

## Dónde seguir

- **[docs/decisiones-de-diseno.md](docs/decisiones-de-diseno.md)** — cada decisión
  no obvia, la alternativa descartada y la medición que la sostiene. Es la fuente
  única de las tablas de calibración.
- **[infra/terraform/README.md](infra/terraform/README.md)** — cómo desplegar la
  capa de ingestión y qué adaptamos de la plantilla del curso.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — entorno, linters, convención de commits
  y las reglas que no negociamos.
