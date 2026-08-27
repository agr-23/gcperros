# Decisiones de diseño

Cada decisión que no es obvia, con la alternativa que se descartó y la evidencia
que la sostiene. Este fichero es la **única fuente** de las tablas de
calibración: los docstrings del código apuntan aquí en lugar de repetirlas, para
que no puedan divergir.

---

## 1. Dominio y generación

### El partido es una secuencia de posesiones

Un muestreo independiente de eventos puede reproducir la frecuencia correcta de
cada tipo y aun así no ser un partido: le faltan las correlaciones temporales y
espaciales. Una posesión encadena pases, avanza el balón y termina por una causa
concreta.

La consecuencia que importa: **la posesión es un resultado, no un parámetro**. Si
se fijara «el local tiene el 60 %», el indicador saldría bien por construcción y
no porque el motor lo calcule bien.

### La fórmula de xG se comparte entre generador y motor

Vive en `core/xg.py` porque el generador decide cada gol muestreando
`Bernoulli(xG)` y el motor recalcula ese xG desde las coordenadas que recibe.

El argumento fino, que conviene tener claro: que los goles converjan a la suma de
xG **no valida el modelo** —sería tautológico, el gol se muestrea del propio xG—.
Valida que las coordenadas del remate **atravesaron el pipeline sin corromperse**.
Si el motor reconstruye un xG distinto del que usó el generador, el dato se
degradó en el transporte.

Puntos de referencia del modelo, en remate central de juego abierto:

| Distancia | xG | Lectura |
|---|---|---|
| 6 m | 0,49 | Área chica |
| 11 m | 0,22 | Punto de penal, juego abierto |
| 16,5 m | 0,10 | Frontal del área |
| 30 m | 0,02 | Disparo lejano |

El ángulo pesa: desde 16,5 m el xG cae de 0,104 en el centro a 0,018 a 25 m hacia
la banda. Es una función paramétrica cerrada, **no un modelo entrenado**:
entrenar ML está fuera del alcance declarado del proyecto.

### El gol se emite dos veces, a propósito

El contrato (HU-1) exige el gol como evento aparte, además del remate. El remate
guarda su xG para el modelo; el gol es un hecho de negocio con vida propia que
cualquier consumidor puede contar sin entender la semántica de un remate.

### Calibración del generador de partidos

Medias sobre 60 partidos, contra los rangos de referencia del dominio. Es el
criterio de verificación del OE-1, y `tests/test_match_statistics.py` lo
reverifica en cada ejecución.

| Métrica (ambos equipos) | Simulado | Referencia |
|---|---|---|
| Eventos por partido | 1.214 | 1.200 – 1.500 |
| Pases | 937 | 900 – 1.100 |
| Pases completados | 83,5 % | 80 – 85 % |
| Remates | 26,4 | ~25 |
| xG por remate | 0,116 | ~0,11 |
| xG acumulado | 3,06 | ~2,7 |
| Goles | 2,92 | ~2,7 |
| Faltas | 23,5 | ~22 |
| Tarjetas rojas | 0,240 | ~0,25 |
| Posesiones | 224 | 200 – 250 |

### El balón sale del campo en lugar de pegarse a la línea

La primera versión recortaba al rectángulo del campo la coordenada de todo pase
desviado. Ninguna prueba de determinismo ni de contrato lo detectaba; apareció al
mirar la distribución espacial:

| Medición | Antes | Después |
|---|---|---|
| Eventos con coordenada sobre una línea | 25,1 % | 2,4 % |
| Remates desde la línea de gol | 32,3 % | 0,8 % |
| Goles marcados desde ahí | 42 de 101 | — |

Un tercio de los remates salía de un punto físicamente imposible. Ahora el balón
que apunta fuera sale de juego y se repone con saque de banda o de puerta, y el
pase lleva sesgo hacia el centro.

La moraleja vale más que el arreglo: **el defecto sólo se vio perfilando los
datos**, que es exactamente la Fase 2 de la metodología del proyecto.

---

## 2. Mercado de cuotas

### Tres operadores, no uno

La arquitectura habla de un *feed de casas*, en plural. Tres operadores con
márgenes, retardos y valoraciones distintas convierten un gol en una ráfaga real
y producen las discrepancias entre mercados que buscará la HU-19. Los nombres son
ficticios a propósito: usar marcas reales sugeriría que el proyecto consume datos
de casas de apuestas reales.

### Patrón de tráfico

Unas **3 actualizaciones por minuto** de fondo contra **15 o más** en los veinte
segundos siguientes a un gol o una expulsión. El contraste sale de publicar
siempre ante evento relevante y sólo por umbral de movimiento el resto del
tiempo.

### Un mercado resuelto deja de cotizarse

Sin ese corte, el generador publicaba precios pegados a los topes (1,01 contra
200) que ninguna casa ofrece, y hundían el overround medio de 1,057 a 1,002. Una
casa real suspende el mercado.

### El feed publica precios, no probabilidades

Como uno real. Descontar el margen del operador **no es dividir uno entre la
cuota**: con overround 1,06 ese atajo sobreestima cada resultado un 6 % y suma
1,059 en vez de 1. `core/odds.py` expone las dos operaciones por separado, y hay
una prueba que deja constancia del sesgo, porque es el error que la HU-19 debe
evitar.

---

## 3. Motor de procesamiento

### El orden de los pasos no es negociable

Deduplicar → reordenar → aplicar.

- **Deduplicar primero**: si se aplicase antes de comprobar, el estado ya estaría
  corrupto cuando se detectara la repetición.
- **Antes de reordenar**: para no ocupar el buffer con eventos que van a
  descartarse.

### La deduplicación tiene memoria acotada

Recordar todos los identificadores es correcto sobre un flujo finito y ruinoso
sobre uno no acotado. La garantía, enunciada con precisión: **un duplicado se
detecta siempre que entre el original y la repetición lleguen menos de
`capacity` eventos distintos.** Con el valor por defecto (100.000) caben decenas
de partidos, y la unidad de proceso declarada del proyecto es el partido
individual, así que dentro de esa unidad es exacta. Hay una prueba que documenta
el límite en vez de esconderlo.

**No se usa un filtro de Bloom**, que es la estructura habitual: admite falsos
positivos, diría «ya lo vi» sobre un evento nuevo y el motor descartaría un gol
legítimo. Perder un evento real es peor que gastar memoria.

Mejora pendiente: ahora que existe la marca de agua, la expiración podría ser por
tiempo de evento en lugar de por número, y sería exacta. Cambia la semántica del
componente y merece decidirse aparte.

### El margen de la marca de agua está medido

Sobre ocho partidos con retardo de red exponencial de media 2 s y cola acotada a
30 s:

| Margen | Oportunidad | Div. posesión | Div. xG | ¿Cumple OE-2? |
|---|---|---|---|---|
| 0 s | 87,22 % | 11,05 % | 0,3391 | no |
| 1 s | 89,52 % | 9,27 % | 0,0000 | no |
| 3 s | 94,80 % | 6,32 % | 0,0000 | no |
| 5 s | 98,28 % | 2,15 % | 0,0000 | no |
| **10 s** | **99,91 %** | **0,17 %** | **0,0000** | **sí** |
| 20 s | 100,00 % | 0,00 % | 0,0000 | sí |

El proyecto declara divergencia máxima del 1 % en posesión, 0,05 en xG y
oportunidad mínima del 95 %. **Diez segundos es el margen más ajustado que cumple
los tres.**

### Tensión abierta: el margen contra el SLA de latencia

El margen de 10 s **choca con el SLA declarado de latencia extremo a extremo por
debajo de 2 s en p95**: un evento retenido espera del orden del propio margen
antes de aplicarse. Los dos objetivos no se cumplen a la vez con este diseño.

Queda documentado en lugar de disimulado. La salida —publicar estado provisional
y corregirlo al cerrar la ventana— corresponde al sprint que caracteriza la
latencia bajo carga (OE-3).

### El rezagado se cuenta, no se pierde

Un evento que llega con su ventana cerrada se registra como descartado por
tardío, con su retraso medido. Esa cuenta alimenta la dimensión de *oportunidad*
del marco de calidad (HU-17) y permite auditar cuánta información se sacrificó a
cambio de latencia.

### Eventos con el mismo instante

El contrato no define un orden entre ellos —el gol y el remate que lo produjo
comparten `event_time`— así que se desempata por `event_id`, estable
independientemente del orden de llegada. Los indicadores son recuentos y sumas,
que conmutan, de modo que el desempate no altera el estado.

---

## 4. Publicación

### El publicador habla con un `Transport`, no con Pub/Sub

No es arquitectura por gusto. La historia pide **reintento y registro ante fallo**,
y eso no se puede probar contra un broker real: no hay forma de pedirle a Pub/Sub
que falle las dos primeras veces y acierte a la tercera. Con un transporte
inyectable la prueba provoca el fallo exacto que quiere, y el adaptador real
queda tan delgado que casi no hay lógica propia que pueda romperse sin que las
pruebas lo vean.

### El reintento lleva jitter

Sin él, todos los mensajes que fallaron a la vez reintentarían a la vez y
reproducirían intacto el pico que tumbó al broker.

### Agotados los intentos, se para

Sería más cómodo descartar el evento y continuar, pero eso perdería un dato sin
que nadie se entere. Es coherente con el resto del sistema: un rezagado se cuenta
(HU-12), un duplicado se cuenta (HU-11), y uno que no se pudo publicar detiene la
ejecución con su causa registrada.

---

## 5. Reproducibilidad

### Nada de `random` global, `uuid4` ni `datetime.now()`

Los tres rompen el determinismo bajo semilla fija. Los identificadores se derivan
por UUID v5 del `match_id` y el número de secuencia; la hora de inicio es una
constante.

### El orden de los equipos no puede depender del `hash`

`summarize_events` derivaba los equipos de un conjunto, y el orden de iteración
de un `set` de cadenas cambia con `PYTHONHASHSEED`: doce ejecuciones dieron dos
órdenes distintos. La igualdad entre diccionarios lo ignora, así que las pruebas
no lo veían, pero en cuanto ese resumen se serialice la salida dejaría de ser
idéntica byte a byte. Ahora van en orden de primera aparición.

### El fichero de bloqueo de Terraform se versiona

Fija el hash exacto del provider para todo el equipo. Es el equivalente, en
infraestructura, de la semilla fija de los generadores.

### Huellas congeladas

`tests/test_pipeline.py` guarda el SHA-256 de la salida de referencia. Si cambia,
la prueba falla y obliga a actualizarla **a propósito**, explicando el motivo en
el commit. Es lo que impide que una recalibración accidental pase inadvertida.

---

## 6. Infraestructura

### Dos topics, no uno con un campo de tipo

Los eventos del partido llegan cada ~3 s de forma regular; las cuotas llegan en
ráfagas reactivas. En un solo canal una ráfaga de cuotas retrasaría los eventos
del partido, y además son dos contratos de datos distintos: se escalan, se
retienen y se auditan por separado.

### `enable_message_ordering = false`, deliberado

Ordenar en el broker ocultaría el desorden temporal que el motor debe resolver
con marcas de agua, que es precisamente lo que el proyecto quiere demostrar. Y
serializa la entrega, con su coste de latencia.

### Dead letter y repositorio de inválidos no son lo mismo

- **Repositorio de inválidos (HU-16)**: el mensaje incumple el contrato. Se
  rechaza en la frontera, antes de gastar cómputo.
- **Dead letter**: el mensaje está bien formado pero el motor no logró
  procesarlo tras varios intentos.

### Sin llaves descargadas

Los procesos locales se autentican por suplantación de service account. Responde
al riesgo declarado de «prohibición de credenciales en el repositorio».

---

## 7. Contratos y frontera de ingestión

### El contrato se declara como dato, no como comprobaciones

`core/schema.py` es una estructura, no una cadena de `if`. El motivo es que el
mismo contrato tiene que servir para tres trabajos distintos: rechazar en la
frontera (HU-16), medir completitud (HU-17) y derivar la tabla de destino cuando
exista la capa Raw (HU-14). Tres implementaciones del mismo contrato acabarían
divergiendo; una declaración no puede.

El vocabulario es corto a propósito —tipo, obligatoriedad, valores admisibles y
rango— porque un esquema capaz de expresar cualquier cosa deja de poder leerse, y
este fichero es el documento que se consulta para saber qué promete el proyecto a
sus consumidores.

### El defecto que motivó la historia

El lector comprobaba los campos de nivel superior y que `attrs` fuera un objeto,
pero **nunca miraba dentro**. Un remate sin `xg` atravesaba `parse_match_event`
sin protestar y reventaba mucho más tarde, al agregarlo:

```
LiveMatchState.apply -> as_float(event.attrs["xg"]) -> KeyError
```

Es exactamente el enunciado de la historia: gastar cómputo procesando basura y
descubrirlo cuando ya se ha gastado. `tests/test_gate.py` conserva las dos caras
—el fallo sin frontera y su ausencia con ella— porque una historia cuya
motivación no se puede reproducir es una historia que nadie puede evaluar.

### El vocabulario de `reason` es cerrado, y eso cuesta

Los motivos de cambio de posesión vivían implícitos en el generador. Ahora son un
`Literal` del contrato, y la frontera rechaza cualquier otro.

Tiene un precio real: añadir un motivo nuevo rompe la validación y obliga a
versionar el contrato. **Ese precio es justamente lo que hace que el contrato
signifique algo.** Un vocabulario abierto no promete nada, y un consumidor que
ramifique sobre `reason` no tendría forma de saber qué puede recibir sin leer el
código del productor —que es precisamente lo que un contrato existe para evitar.

### Todas las violaciones, una por campo

Dos reglas que parecen contradictorias y no lo son:

- **Se reportan todos los campos defectuosos**, no el primero. Un rechazo que
  informa de un problema por vez obliga a quien produce el mensaje a reenviarlo
  tantas veces como defectos tenga. Con el mensaje delante, la frontera ya sabe
  todo lo que está mal: decirlo entero cuesta lo mismo.
- **Una sola violación por campo.** Un campo vacío tampoco está entre los valores
  admitidos, y decir las dos cosas no añade información: la primera causa ya
  explica qué hay que arreglar.

Y cuando el discriminador no sirve —un `event_type` desconocido— **no se
inventan causas sobre los atributos**. Sin saber qué evento es, exigir unos u
otros sería adivinar, y una causa falsa es peor que ninguna: manda a quien la lee
a arreglar algo que no está roto.

### El mensaje inválido se archiva crudo

Sin normalizar, sin recortar espacios, sin reordenar claves. El registro existe
para demostrarle al productor qué mandó; si no reproduce exactamente lo que
mandó, no demuestra nada.

Por lo mismo se archiva lo que ni siquiera es UTF-8, decodificado con reemplazo:
un repositorio que se cae ante la basura peor formada es el que menos sirve.

Cada registro guarda además **la versión del contrato contra la que se juzgó**.
Sin ella el archivo no se puede interpretar más adelante: el mismo mensaje puede
ser inválido bajo `v1` y perfectamente válido bajo `v2`.

Esto no se solapa con el *dead letter* de Pub/Sub; la distinción está en la
sección 6.

### La frontera va antes del deduplicador

El recorrido completo de un mensaje queda así:

1. **Validar** contra el contrato y apartar lo no conforme (HU-16).
2. **Deduplicar** por `event_id` (HU-11).
3. **Reordenar** por marca de agua (HU-12).
4. **Aplicar** al estado.

Es el mismo argumento que ordena los otros tres pasos: cada uno descarta trabajo
que los siguientes ya no tendrán que hacer. Un mensaje inválido no merece ocupar
sitio en la memoria acotada del deduplicador, y menos aún en el buffer de la
marca de agua.

Hay un segundo efecto, menos obvio y más valioso: con la frontera delante, **el
motor puede asumir que todo lo que recibe es conforme**. Esa suposición es lo que
le permite ser tan simple como es. Validar dentro del motor lo obligaría además a
decidir qué hacer con lo que no entiende, que es una responsabilidad de
gobernanza y no de cálculo.

### Lo que la frontera no valida

La coherencia **entre** eventos: que un `goal` venga acompañado de su `shot`, que
el reloj avance, que la posesión sume. Son propiedades del flujo, no de un
mensaje suelto, y la frontera juzga de uno en uno porque es lo único que se puede
hacer antes de gastar cómputo. Eso es trabajo del marco de calidad (HU-17).

### El reloj del rechazo se inyecta

La regla 3 de `CONTRIBUTING.md` prohíbe `datetime.now()` en el código de
generación. Un rechazo sí ocurre en un instante real, así que la prohibición no
aplica tal cual — pero un repositorio que no se puede reproducir en una prueba
tampoco se puede verificar. El reloj es un parámetro con valor por defecto: en
producción marca la hora, en las pruebas se fija.

Los identificadores de rechazo siguen la misma regla que los del contrato: UUID
v5 derivado del flujo, la huella del mensaje y su posición. Con `uuid4`, comparar
dos ejecuciones del repositorio no significaría nada.

### Política de versionado

Los dos flujos se versionan **por separado**, igual que viajan por topics
separados: `match-events` puede evolucionar sin obligar a los consumidores de
`odds-updates` a tocar nada. La versión viaja en el sobre (`contract_version`) y
además como etiqueta del topic en Terraform, de modo que sea visible desde la
propia infraestructura.

| Cambio | ¿Compatible? | Qué exige |
|---|---|---|
| Añadir un campo **opcional** | Sí | Nada. Es el único cambio que no rompe. |
| Añadir un valor a un vocabulario cerrado | No | Subir versión |
| Añadir un tipo de evento | No | Subir versión y declarar su variante |
| Renombrar o eliminar un campo | No | Subir versión |
| Cambiar el tipo de un campo | No | Subir versión |
| Ensanchar o estrechar un rango | No | Subir versión |
| Cambiar la semántica sin cambiar la forma | No, y es el peor de todos | Subir versión |

El último merece su propia línea porque es el que se cuela: un campo que sigue
llamándose igual, con el mismo tipo, y que pasa a significar otra cosa no rompe
ninguna validación y rompe a todos los consumidores. Ningún mecanismo automático
lo detecta; por eso está escrito aquí.

Un `v2` que nadie acordó **no se acepta**: la versión es un valor cerrado del
esquema, así que un mensaje que se declare de una versión desconocida se rechaza
en la frontera en lugar de procesarse a medias.
