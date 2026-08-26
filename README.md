# GCPerros — Pipeline de Streaming de Datos Deportivos

Plataforma de ingeniería de datos que ingiere, procesa y dispone en tiempo real
dos flujos de eventos —acciones de un partido de fútbol y actualizaciones de
cuotas— para generar indicadores analíticos y señales de apoyo a la decisión
durante el encuentro.

**SI4002 · Proyecto de Ingeniería de Datos · EAFIT · 2026-2**
Prof. Jose Fabio Jaramillo Castro

| Integrante | Rol |
|---|---|
| Jean Carlo Londoño | Ingeniero de Pipelines / Big Data |
| Tomás Londoño | Arquitecto de Datos / Cloud |
| Alejandro Garcés | Oficial de Gobernanza / Líder DataOps |

> **Uso responsable.** Proyecto estrictamente académico. El sistema es una
> herramienta de apoyo a la decisión informada: no ejecuta apuestas, no
> intermedia en el juego y no promete rentabilidad alguna. Los datos del dominio
> deportivo son sintéticos.

---

## Arquitectura

```
Generadores sintéticos          (fuera de GCP, costo cero)
        │
        ▼
Pub/Sub · match-events + odds-updates        ← capa de ingestión
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

La entrega del broker es *at-least-once* y sin orden. Eso es **premisa de
diseño**, no un defecto: la deduplicación por `event_id` y el reordenamiento por
marcas de agua ocurren en el motor, y son parte del objeto de estudio.

---

## Empezar

```bash
python -m venv .venv
source .venv/Scripts/activate      # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install --install-hooks
```

```bash
# Un partido completo, un evento por línea
gcperros-generate-match --seed 20260826 --out partido.jsonl --summary

# Las cuotas del mismo partido: la semilla describe el mismo encuentro
gcperros-generate-odds --seed 20260826 --out cuotas.jsonl --summary

# Publicar hacia el broker (--dry-run recorre todo sin salir del proceso)
gcperros-publish --seed 20260826 --dry-run
```

Procesar un flujo con el motor:

```python
from gcperros.engine.pipeline import MatchEngine

engine = MatchEngine()
for event in delivered:  # con duplicados y desordenados
    engine.process(event)  # -> ACCEPTED | DUPLICATE | DROPPED_LATE
engine.flush()

engine.result().summary  # indicadores del partido
engine.dedup_stats.duplicates  # repeticiones suprimidas
engine.watermark_stats.timeliness  # proporción aplicada dentro de plazo
```

---

## Estado

| Componente | Estado | Historia |
|---|---|---|
| Generador de eventos de partido | ✅ | HU-8 |
| Generador de cuotas | ✅ | HU-9 |
| Publicación hacia Pub/Sub | ✅ código; sin broker vivo todavía | HU-10 |
| Motor: deduplicación | ✅ | HU-11 |
| Motor: marca de agua | ✅ | HU-12 |
| Infraestructura Pub/Sub en Terraform | ✅ código; sin desplegar | HU-13 |
| Consumidor a BigQuery Raw | ⏳ | HU-14 |
| Estado vivo en Firestore | ⏳ | HU-15 |
| Contratos formales y reglas de calidad | ⏳ | HU-16, HU-17 |

---

## Estructura

```
src/gcperros/core/          Dominio compartido: contratos, campo, xG, cuotas, agregados
src/gcperros/generators/    Generadores sintéticos e inyector de perturbaciones
src/gcperros/engine/        Motor con estado: dedup, marca de agua, estado vivo
src/gcperros/publishing/    Publicación hacia el broker
tests/                      Unitarias por componente y de tubería completa
infra/terraform/            Infraestructura como código
docs/                       Decisiones de diseño con su evidencia
```

`core/` existe porque generador y motor deben compartir el **mismo** modelo de xG
y la **misma** matemática de cuotas. Si fueran implementaciones distintas,
comparar los dos planos no probaría nada.

---

## Dónde seguir

- **[docs/decisiones-de-diseno.md](docs/decisiones-de-diseno.md)** — cada decisión
  no obvia, la alternativa descartada y la medición que la sostiene. Es la fuente
  única de las tablas de calibración.
- **[infra/terraform/README.md](infra/terraform/README.md)** — desplegar la capa
  de ingestión, y qué se adaptó de la plantilla del curso.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — entorno, linters, convención de commits
  y las reglas que no son negociables.

### Sin cuenta de nube

Todo lo anterior corre en local. Para publicar contra un broker de verdad sin
cuenta de GCP existe el emulador de Pub/Sub:

```bash
gcloud components install pubsub-emulator      # necesita Java 11 o superior
gcloud beta emulators pubsub start --project=gcperros-local

export PUBSUB_EMULATOR_HOST=localhost:8085
gcperros-publish --seed 20260826 --project gcperros-local --create-topics
```

El mismo código publica en GCP en cuanto se quita esa variable.
