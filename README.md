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
| Generador de cuotas sintéticas | ✅ Funcional | HU-9 |
| Publicación hacia Pub/Sub | ⏳ Pendiente | HU-10 |
| Motor: deduplicación por `event_id` | ✅ Funcional | HU-11 |
| Motor: reordenamiento por marca de agua | ⏳ Pendiente | HU-12 |
| Despliegue del motor en Cloud Run | ⏳ Pendiente | HU-11, HU-12 |
| Datasets de BigQuery / Firestore | ⏳ Pendiente | HU-14, HU-15 |
| Contratos de datos y reglas de calidad | ⏳ Pendiente | HU-16, HU-17 |

---

## Estructura

```
src/gcperros/core/          Dominio compartido: contratos, campo, xG, cuotas y agregados
src/gcperros/generators/    Generadores sintéticos y el inyector de perturbaciones
src/gcperros/engine/        Motor con estado: deduplicación y estado vivo del partido
tests/                      Determinismo, contrato, xG, cuotas, motor y estadística
infra/terraform/            Infraestructura como código (empezar por su README)
```

`core/` existe porque el generador y el motor deben compartir el **mismo** modelo
de xG: la HU-8 decide cada gol muestreando `Bernoulli(xG)` y el motor recalcula
ese xG desde las coordenadas que le llegan por el broker. Si fueran dos
implementaciones distintas, comparar ambos planos no probaría nada. Por la misma
razón vive ahí `core/odds.py`, que el motor usará para descontar el margen del
operador y obtener la probabilidad implícita (HU-19).

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

## Generar el flujo de cuotas

```bash
gcperros-generate-odds --seed 20260826 --out cuotas.jsonl --summary
```

Las cuotas se derivan del mismo partido: **la misma semilla describe el mismo
encuentro** desde el campo y desde el mercado. Se modelan tres operadores
sintéticos, cada uno con su margen, su retardo de reacción y su propia
valoración del local — de ahí salen las discrepancias entre casas que la HU-19
tendrá que detectar.

Un gol acorta la cuota del que marca, de golpe y en todas las casas:

```json
{"market":"1x2","operator":"OP-A","outcomes":[{"odds":2.15,"outcome":"home"},{"odds":3.72,"outcome":"draw"},{"odds":3.12,"outcome":"away"}],"trigger":"open", ...}
{"market":"1x2","operator":"OP-A","outcomes":[{"odds":1.34,"outcome":"home"},{"odds":5.06,"outcome":"draw"},{"odds":8.82,"outcome":"away"}],"trigger":"goal", ...}
```

El patrón de tráfico es el que la historia pide reproducir: unas **3 actualizaciones
por minuto** de fondo, contra **15 o más** en los veinte segundos siguientes a un
gol o una expulsión. Ese contraste es lo que someterá al pipeline al tráfico que
encontrará en producción.

El feed publica **precios, no probabilidades**, igual que un feed real. Convertir
la cuota en probabilidad implícita exige descontar el margen del operador, que no
es dividir uno entre la cuota: con un overround de 1,06 el atajo sobreestima cada
resultado un 6 %. `core/odds.py` expone las dos operaciones por separado.

---

## El motor: un duplicado no se cuenta dos veces

Pub/Sub entrega **al menos una vez**: si el consumidor tarda en confirmar, el
broker reentrega. Es el trato que se acepta a cambio de no perder nada, y sin
tratarlo se convierte en un gol contado dos veces.

El motor deduplica por `event_id` **antes** de tocar el estado. Al revés, el
estado ya estaría corrupto cuando se detectara la repetición.

```python
from gcperros.engine.pipeline import MatchEngine

engine = MatchEngine()
for event in delivered:  # tal como llega del broker, con repeticiones
    engine.process(event)

engine.result().summary  # indicadores del partido
engine.dedup_stats.duplicates  # cuántas repeticiones se suprimieron
```

Reentregando cada gol, cada remate y cada cambio de posesión de un partido real:

| Indicador | Real | Sin deduplicar | Con el motor |
|---|---|---|---|
| Goles | 4 | **8** | 4 |
| Remates | 16 | **32** | 16 |
| Posesiones | 110 | **220** | 110 |
| xG acumulado | 0,975 | **1,950** | 0,975 |

El resultado del motor coincide con el del plano batch de referencia
(`core.stats.summarize_events`), que es la comparación que el OE-2 exige y que
aquí ya queda preparada.

### La garantía, enunciada con precisión

La memoria está acotada: se recuerdan los últimos `capacity` identificadores.
Así que la promesa no es absoluta, y conviene saber decirla bien: **un duplicado
se detecta siempre que entre el original y la repetición lleguen menos de
`capacity` eventos distintos.** Con el valor por defecto (100.000) caben decenas
de partidos, y la unidad de procesamiento declarada del proyecto es el partido
individual — así que dentro de esa unidad la deduplicación es exacta. Hay una
prueba que documenta el límite en vez de esconderlo.

No se usa un filtro de Bloom, que es la estructura habitual para esto, porque
admite falsos positivos: diría «ya lo vi» sobre un evento nuevo y el motor
descartaría un gol legítimo. Perder un evento real es peor que gastar memoria.

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
