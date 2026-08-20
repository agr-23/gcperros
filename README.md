# GCPerros — Pipeline de Streaming de Datos Deportivos

Plataforma de ingeniería de datos que ingiere, procesa y dispone en tiempo real
dos flujos de eventos —acciones de un partido de fútbol y actualizaciones de
cuotas de apuestas— para generar indicadores analíticos y señales de apoyo a la
decisión durante el encuentro.

**SI4002 · Proyecto de Ingeniería de Datos · EAFIT · 2026-2**
Prof. Jose Fabio Jaramillo Castro

| Integrante | Rol |
|---|---|
| Jean Carlo Londoño | Ingeniero de Pipelines / Big Data |
| Tomás Londoño | Arquitecto de Datos / Cloud |
| Alejandro Garcés | Oficial de Gobernanza / Líder DataOps |

> **Uso responsable.** Este es un proyecto estrictamente académico. El sistema
> es una herramienta de apoyo a la decisión informada: no ejecuta apuestas, no
> intermedia en el juego y no promete rentabilidad alguna. Los datos del dominio
> deportivo son sintéticos.

---

## Arquitectura

Cinco capas desacopladas, sobre servicios *serverless* de GCP:

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
marcas de agua sobre `event_time` ocurren en el motor, y son parte del objeto de
estudio del proyecto.

---

## Estado del repositorio

| Componente | Estado | Historia |
|---|---|---|
| `infra/terraform/` — capa de ingestión (Pub/Sub) | ✅ Desplegable | HU-13 (parcial) |
| Motor analítico en Cloud Run | ⏳ Pendiente | HU-11, HU-12 |
| Datasets de BigQuery / Firestore | ⏳ Pendiente | HU-14, HU-15 |
| Generadores sintéticos | ⏳ Pendiente | HU-8, HU-9, HU-10 |
| Contratos de datos y reglas de calidad | ⏳ Pendiente | HU-16, HU-17 |

---

## Estructura

```
infra/terraform/     Infraestructura como código (empezar por su README)
```

> La estructura completa del repositorio —`generators/`, `engine/`, `docs/`,
> `tests/`— corresponde a la HU-7 y está pendiente de definir por el equipo.
> Este árbol es el punto de partida, no la propuesta final.

---

## Empezar

La capa de ingestión se despliega por sí sola y no depende de ningún otro
componente:

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # y edita project_id
terraform init && terraform plan -out=tfplan
terraform apply tfplan
```

Instrucciones completas, decisiones de diseño y comandos de verificación en
[`infra/terraform/README.md`](infra/terraform/README.md).
