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
| Generador de eventos de partido | ✅ Funcional | HU-8 |
| `infra/terraform/` — capa de ingestión (Pub/Sub) | ✅ Desplegable | HU-13 (parcial) |
| Generador de cuotas sintéticas | ⏳ Pendiente | HU-9 |
| Publicación hacia Pub/Sub | ⏳ Pendiente | HU-10 |
| Motor analítico en Cloud Run | ⏳ Pendiente | HU-11, HU-12 |
| Datasets de BigQuery / Firestore | ⏳ Pendiente | HU-14, HU-15 |
| Contratos de datos y reglas de calidad | ⏳ Pendiente | HU-16, HU-17 |

---

## Estructura

```
src/gcperros/core/          Dominio compartido: contrato de evento, campo, modelo de xG
src/gcperros/generators/    Generadores sintéticos de los flujos de entrada
tests/                      Determinismo, contrato, xG y plausibilidad estadística
infra/terraform/            Infraestructura como código (empezar por su README)
```

`core/` existe porque el generador y el motor deben compartir el **mismo** modelo
de xG: la HU-8 decide cada gol muestreando `Bernoulli(xG)` y el motor recalcula
ese xG desde las coordenadas que le llegan por el broker. Si fueran dos
implementaciones distintas, comparar ambos planos no probaría nada.

> La estructura definitiva del repositorio corresponde a la HU-7 y sigue
> pendiente de acordar por el equipo.

---

## Generar un partido

```bash
pip install -e ".[dev]"

gcperros-generate-match --seed 20260826 --out partido.jsonl --summary
```

Sale un evento por línea, en el mismo formato que viajará por Pub/Sub y que se
persistirá sin transformar en la capa Raw:

```json
{"attrs":{"is_goal":false,"period":1,"x":96.73,"xg":0.0098,"y":12.4},"contract_version":"v1","event_id":"40e1678e-…","event_time":"2026-08-26T19:05:39.269Z","event_type":"shot","match_id":"match-0001","team":"HOME"}
```

La promesa de la HU-8 es que la misma semilla produce el mismo partido **byte a
byte**, y se comprueba en cada ejecución de la CI:

```bash
gcperros-generate-match --seed 42 --out a.jsonl
gcperros-generate-match --seed 42 --out b.jsonl
cmp a.jsonl b.jsonl        # sin diferencias
```

El simulador está calibrado contra los rangos de referencia del dominio (1.214
eventos, 26,4 remates con xG medio 0,116, 2,92 goles, 83,5 % de pase completado
por partido). La tabla completa está en el docstring de
[`match.py`](src/gcperros/generators/match.py) y las pruebas marcadas
`statistical` la vuelven a verificar en cada ejecución.

---

## Desplegar la infraestructura

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

---

## Contribuir

Linters, ganchos de pre-commit, convención de mensajes de commit y las reglas
que no son negociables, en [`CONTRIBUTING.md`](CONTRIBUTING.md).
