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

---

## 8. Marco de calidad

### Tres dimensiones, no las seis del catálogo

Exactitud, consistencia y validez quedan fuera de este sprint. No por descuido:
son las que **no se pueden medir con lo que el pipeline ya observa**, y una
dimensión sin forma de medirla es una casilla en un informe, no una garantía.

Las tres que sí entran ya tenían sus contadores repartidos por el código
—`GateStats`, `DedupStats`, `WatermarkStats`—. Lo que faltaba no era el número,
era **el umbral**: sin él se podía describir la calidad pero no afirmar que
estuviera bien ni mal.

### Dónde se mide cada dimensión, y por qué ahí

Es la decisión de fondo de esta historia, y las dos caras del mismo error:

- **Completitud sobre lo entregado, no sobre lo admitido.** Medir solo lo que
  entró daría siempre el cien por cien, y lo daría por construcción: lo
  incompleto lo rechazó la propia frontera (HU-16). Una regla así estaría
  midiendo su propio filtro.
- **Unicidad sobre la entrega, no después de deduplicar.** Contar identificadores
  ya deduplicados daría siempre uno. Lo que se mide es el flujo tal como lo
  entregó el broker, que es donde la repetición ocurre.

Es la misma forma del argumento que sostiene que la posesión sea un resultado y
no un parámetro (sección 1): **un indicador que sale bien porque se fijó de
antemano no prueba nada.**

### No medido no es lo mismo que aprobado

El flujo de cuotas no pasa por el motor, así que no tiene deduplicación ni marca
de agua. El informe **nombra** esas dimensiones como no medidas en lugar de
omitirlas. Omitirlas dejaría un informe en verde que parecería decir que todo se
comprobó, que es peor que no tener informe.

### Los umbrales: dos medidos y uno que no

El proyecto exige que un umbral se sostenga en evidencia. Dos la tienen y el
tercero no, y conviene decirlo antes de que lo pregunten:

| Dimensión | Umbral | De dónde sale |
|---|---|---|
| Oportunidad | 0,95 | **Declarado** por el proyecto en el OE-2. Es el mismo que sostiene el margen de 10 s de la sección 3. Observado: 0,9992 – 1,0000 |
| Unicidad | 0,90 | **Medido.** Con el inyector de duplicados en su 5 % por defecto —ya exagerado frente a Pub/Sub— ocho partidos dan entre 0,942 y 0,955 |
| Completitud | 0,99 | **Política, no medido.** Con los generadores del propio proyecto no hay rechazos, así que no hay nada que observar todavía |

El umbral de unicidad queda deliberadamente por debajo del peor caso observado:
**acota lo anormal, no la adversidad que el proyecto se autoimpone**. Si un día
salta, es que el broker se comporta peor que el escenario de estrés, y eso sí es
noticia.

El de completitud se recalibra cuando exista ingestión real (HU-14). Hasta
entonces es una política declarada, y `tests/test_quality.py` deja constancia de
cuál es la evidencia de cada uno para que nadie los endurezca sin aportar la
suya.

### El informe guarda numerador y denominador

Nueve de diez y novecientos de mil dan el mismo 0,9 y no merecen la misma
confianza. Publicar solo la proporción perdería esa diferencia justo cuando más
importa: al decidir si un fallo es una señal o una casualidad.

Guarda además los **motivos de rechazo**, que no son una medición sino el
diagnóstico. Saber que la completitud cayó no dice qué arreglar; saber que fueron
cuarenta `missing_field` en `attrs.xg`, sí.

### El informe lleva marca temporal

Sin ella no hay serie, y sin serie la calidad vuelve a ser una auditoría suelta
al final del semestre, que es exactamente lo que la historia pide evitar. El
reloj se inyecta, por el mismo motivo que en el repositorio de inválidos.

### Se mide en el mismo acto de ingerir

`gcperros-quality` recorre la ingestión completa —frontera y motor— y emite el
informe de esa pasada. No es un script que alguien tiene que acordarse de
ejecutar sobre datos ya guardados: es el propio camino del dato el que produce la
medición. Un paso del pipeline lo ejecuta con `--strict` sobre el flujo de
referencia, de modo que una regresión de calidad rompe la construcción.

---

## 9. Trazabilidad de los indicadores

### Qué se traza, y qué no

La historia habla de trazar **señales**. El proyecto no tiene ninguna: la de
discrepancia entre mercados es la HU-19, que el código menciona en siete sitios
como trabajo futuro y que **no tiene historia asignada en el tablero**. Trazar
algo que nadie va a construir habría sido escribir un mecanismo sin sujeto.

Lo que se traza son los indicadores que el motor sí produce, que además es lo que
cualquier señal futura va a consumir. Cuando la señal exista, declarar su linaje
es añadir una entrada a `MODELS_BY_INDICATOR` y plegar los identificadores que la
formaron: el mecanismo ya está montado.

### Una huella verificable en lugar de la lista de identificadores

Guardar los `event_id` completos no escala —1.200 eventos por partido, y la
temporada no está acotada—. Guardar solo un hash tampoco basta, porque por sí
solo no permite comprobar nada contra el origen.

La salida está en una premisa que el proyecto ya sostiene: **el pipeline es
determinista y la capa Raw guarda el flujo sin transformar**. No hace falta
almacenar el linaje entero; hace falta que **la re-derivación sea verificable**.
Se reprocesa el partido, se vuelve a plegar la huella y se compara. Es el mismo
mecanismo que las huellas SHA-256 congeladas de `tests/test_pipeline.py`, y
cuesta memoria constante por indicador en lugar de lineal.

Se conservan además tres identificadores en claro por indicador. No son el
linaje: son una muestra, para poder comprobar a mano contra la capa Raw sin
reprocesar el partido entero.

### El pliegue conmuta, y no es comodidad

La huella se acumula **sumando** las huellas individuales, de modo que no depende
del orden de llegada.

Es coherencia, no atajo. La sección 3 justifica el desempate entre eventos del
mismo instante diciendo que *"los indicadores son recuentos y sumas, que
conmutan, de modo que el desempate no altera el estado"*. Si el linaje **no**
conmutara, introduciría una dependencia del orden que el propio indicador no
tiene: el mismo partido entregado en dos órdenes distintos daría el mismo número
con dos procedencias distintas, y la auditoría no probaría nada.

Verificado: con duplicados al 5 % y desorden inyectados a la vez, las huellas de
los diecisiete indicadores son idénticas a las del flujo limpio.

**No se usa un XOR**, que también conmuta: el XOR de un valor consigo mismo se
cancela, así que un identificador repetido desaparecería de la huella sin dejar
rastro. La deduplicación (HU-11) debería impedirlo, pero un mecanismo de
auditoría no puede apoyarse en que otro no falle.

Por lo mismo, la muestra son los identificadores **menores**, no los primeros:
sin orden garantizado, «primero» no significaría lo mismo en dos ejecuciones.

### Solo se estampa versión donde de verdad hay un modelo

Contar goles no usa ningún modelo. Ponerle `xg-1.0.0` a un recuento haría el
informe más uniforme y menos cierto, y quien lo audite acabaría desconfiando de
todas las versiones al descubrir que una era decorativa. Hoy el único indicador
del motor con modelo detrás es `total_xg`.

### La versión del modelo no puede quedarse atrás

Un número calculado con otros coeficientes tiene que poder distinguirse del
anterior, así que `MODEL_VERSION` sube cuando el modelo cambia. Confiar en que
alguien se acuerde no es un mecanismo: `tests/test_xg.py` y
`tests/test_odds_math.py` congelan la huella de las **salidas** del modelo sobre
una rejilla, no de sus constantes, para detectar también un cambio en la fórmula.
Si la huella cambia, la prueba falla y obliga a subir la versión en el mismo
commit.

### Un indicador que vale cero también se explica

La auditoría recorre los indicadores declarados, no los linajes acumulados. Cero
tarjetas rojas es una respuesta legítima y su linaje es el conjunto vacío;
omitirla dejaría un número visible sin procedencia, que es justo lo que esta
historia persigue.

### Mejora pendiente: el linaje del plano batch

`core.stats.summarize_events` produce los mismos indicadores y **no** calcula
linaje, así que la comparación streaming-contra-batch del OE-2 sigue siendo de
valores y no de procedencias. Como el pliegue conmuta, añadirlo daría huellas
idénticas por construcción. Se deja fuera a propósito: el mapeo de evento a
indicador vive hoy junto a los contadores del motor, donde no puede divergir de
ellos, y duplicarlo en el plano batch reintroduciría exactamente el riesgo que
esa cercanía evita. Merece decidirse aparte.

---

## 10. Cargador de la capa Raw (HU-14)

### Por qué el cargador no deduplica ni interpreta `attrs`

Es la decisión que más se presta a la confusión, porque el proyecto ya tiene
un deduplicador (HU-11) y sería tentador reutilizarlo aquí. No se hace, y es
deliberado: la capa Raw existe para responder a una pregunta distinta de la
que responde el estado vivo del motor.

El motor mantiene el estado *correcto* de un partido en curso —sin
repeticiones, en orden cronológico— porque de eso depende un indicador en
vivo. La capa Raw existe para poder reconstruir **qué pasó exactamente en el
broker**, repeticiones y desorden incluidos, algo que el propio README declara
premisa de diseño: *"la entrega del broker es at-least-once y sin orden"*. Si
el cargador dedujera por `event_id` antes de guardar, la capa Raw dejaría de
poder responder preguntas como "¿cuántas veces entregó el broker este
mensaje?" o "¿cuánto tardó la segunda entrega respecto a la primera?" —
exactamente el tipo de pregunta que una capa histórica está para sostener, y
que una copia ya limpiada no puede.

Interpretar `attrs` tendría el mismo problema en otra forma: la tabla Raw
declara `payload STRING` y no columnas por campo del contrato a propósito.
Abrir `attrs` para promover alguno de sus campos a columna sería tomar hoy una
decisión de esquema que un cambio de `contract_version` (regla 7 de
`CONTRIBUTING.md`) podría volver incorrecta mañana, y la tabla Raw es
justamente la que no debe romperse cuando el contrato evoluciona: es su
capacidad de reproceso completo la que permite reconstruir cualquier capa
derivada bajo el contrato que sea.

### El orden que sostiene la promesa de "sin pérdida"

Extraer, persistir y **después** confirmar, en ese orden y no en otro. Es la
misma lógica que ya aplica `gcperros.governance.gate` al validar antes de
deduplicar: cada paso descarta un riesgo que el siguiente ya no tiene que
correr. Confirmar antes de escribir dejaría una ventana en la que un fallo de
BigQuery —cuota agotada, tabla no encontrada, lo que sea— perdería el mensaje
en silencio: Pub/Sub ya lo daría por entregado y jamás lo reintentaría. Con el
orden actual, un fallo de escritura dispara `SinkError`, el lote **no** se
confirma, y el broker lo reentrega en el siguiente sondeo. La historia pide
"sin pérdida", y esta es la única forma de sostenerlo frente a un fallo
transitorio sin inventar un mecanismo de reintento propio.

### `insert_rows_json` con `row_ids`, y qué NO resuelve

El adaptador real (`loading/bigquery.py`) pasa el `message_id` de cada
registro como `row_id` del streaming insert. BigQuery usa esa columna para una
deduplicación de mejor esfuerzo, acotada a una ventana corta. Se activa a
propósito, pero conviene ser preciso sobre su alcance: protege contra que el
**propio cargador** duplique una fila si reintenta un lote que en realidad sí
se había insertado (un timeout de red tras un `insert_rows_json` exitoso, por
ejemplo). No protege, ni pretende hacerlo, contra que Pub/Sub entregue el
mismo mensaje dos veces con más separación temporal: esa repetición sí produce
dos filas, y es correcto que lo haga, por la razón de la primera sección de
este apartado.

### Pull síncrono en vez de `StreamingPull`

`PubSubPullSubscriber` sondea por lotes (`client.pull`) en vez de mantener una
conexión de streaming abierta. La razón es operativa, no de rendimiento: la
historia describe un consumidor mínimo, y un proceso que sondea es más
sencillo de desplegar como trabajo programado (Cloud Scheduler + Cloud Run
Job, o un cron sobre una VM) que uno que necesita permanecer vivo. El costo es
más latencia entre sondeos —aceptable para una capa histórica, que no sirve
ningún indicador en vivo—, y `run_forever` en `raw_loader.py` deja la puerta
abierta a operarlo como servicio continuo el día que convenga, sin cambiar el
protocolo de extracción.

### Por qué la tabla se particiona por `loaded_at` y no por `event_time`

El registro trae tres marcas de tiempo candidatas: `publish_time` (cuándo lo
aceptó el broker), `event_time` (dentro de `payload`, sin abrir) y `loaded_at`
(cuándo lo escribió el cargador). Sólo la última es estable frente a un
reproceso: si el mismo partido se vuelve a publicar meses después para
depurar el motor, `event_time` seguiría señalando la fecha original del
partido sintético y las filas nuevas caerían en particiones viejas, mezclando
dos ejecuciones en la misma partición. `loaded_at` en cambio refleja siempre
cuándo *esta* fila entró a la tabla, que es la pregunta que la partición está
para responder: acotar el costo de una consulta reciente sin tener que abrir
`payload`.

### Protocolos, no clientes concretos

`PullSubscriber` y `RawSink` repiten deliberadamente la forma de `Transport`
(`publishing/transport.py`) e `InvalidEventStore`
(`governance/quarantine.py`): un protocolo mínimo más un doble en memoria. La
razón es la misma en los tres sitios y ya está documentada donde vive cada
uno — se resume aquí para no tener que ir a buscarla: la historia exige un
comportamiento ante un fallo concreto del colaborador externo (aquí, que
escribir en BigQuery falle a mitad de sondeo), y ese fallo no se puede
provocar a voluntad contra el servicio real. Con el protocolo inyectado, la
prueba lo provoca exactamente cuando quiere, y el adaptador real
(`loading/pubsub.py`, `loading/bigquery.py`) queda tan delgado que ambos
quedan fuera de la medición de cobertura, igual que `publishing/pubsub.py`.

---

## 11. Estado vivo en Firestore (HU-15)

### Un documento por partido, no uno por evento — y por qué eso ahorra lecturas, no escrituras

Es fácil leer la historia y pensar que la solución "ahorra cuota" en general;
vale la pena ser preciso sobre cuál mitad de la cuota ataca. Las
**escrituras** cambian poco entre las dos alternativas: tanto un documento
por evento como uno por partido escriben, a grandes rasgos, una vez por cada
lote de eventos que el motor libera. Lo que colapsa es la **lectura**: con un
documento por evento, saber "cómo va el partido ahora" exige leer todo su
historial —cientos de documentos—, y hay que repetir esa lectura cada vez que
alguien abre el dashboard. Con un único documento que se sobrescribe, esa
misma pregunta cuesta una lectura, sin importar cuántos eventos lleve el
partido. La cuota gratis diaria de Firestore es mucho más generosa en
escrituras (20.000) que en lecturas (50.000) pensando justamente en esta
clase de patrón: pocas escrituras por cambio real, muchas lecturas por cada
cliente que quiere enterarse de ese cambio.

"Denormalizado" es la otra mitad de la misma decisión: el documento trae los
indicadores de ambos equipos ya calculados y anidados adentro. La alternativa
—una colección de indicadores por equipo, referenciada desde el documento del
partido— habría obligado al dashboard a hacer una segunda lectura por cada
equipo para completar el cuadro. Cada lectura adicional es, otra vez, cuota
diaria gastada; denormalizar es literalmente pagar una vez por escritura para
no pagar dos veces por lectura.

### Por qué no se dedujo esto reutilizando la deduplicación del motor

El motor ya sabe deduplicar (HU-11). La tentación de reutilizar esa misma
lógica para decidir cuándo publicar el documento hay que resistirla: son
preguntas distintas. La deduplicación del motor decide qué eventos entran al
estado agregado; el publicador de HU-15 decide **cuándo ese estado, una vez
agregado, se refleja hacia afuera**. Mezclar las dos habría significado que
`LiveMatchState` supiera que alguien lo está publicando —una responsabilidad
que no le corresponde, y que rompería la composición limpia que ya tienen
HU-11/HU-12 (motor) y HU-14 (cargador de la capa Raw): cada capa nueva se
agrega envolviendo la anterior, no modificándola.

### Por qué se publica por evento y no con un temporizador

Dos diseños se compararon explícitamente antes de escribir código:

- **Por reloj**: un hilo aparte que, cada cierto intervalo, toma el estado
  actual y lo escribe, haya cambiado o no. Necesita su propio ciclo de vida
  —¿quién lo detiene, y cuándo termina el partido?— y puede escribir un
  documento idéntico al anterior si no llegó ningún evento en la ventana:
  cuota de escritura gastada sin ganar nada.
- **Por evento** (la elegida): se publica en cuanto el motor aplica uno o más
  eventos al estado. `PublishingMatchEngine` lo implementa envolviendo
  `MatchEngine` sin modificarlo —compara `state.event_count` antes y después
  de cada llamada, y publica sólo si avanzó—. No hace falta un reloj aparte,
  y nunca se escribe un documento que no cambió.

El costo del segundo diseño es que una ráfaga de eventos muy rápida (varios
goles y tiros en pocos segundos, algo que sí ocurre en los partidos
sintéticos de HU-8) puede escribir más seguido de lo que un humano percibiría
como necesario. Se acepta a propósito: 20.000 escrituras gratis por día
alcanzan de sobra para varios partidos completos incluso en el peor caso, y
resolver ese detalle con un límite de frecuencia adicional (agrupar
publicaciones dentro de una ventana mínima) es una optimización que se puede
añadir después sin cambiar el diseño, el día que la cuota real lo exija.

### Por qué el documento no interpreta ni denormaliza el linaje de los indicadores

El documento trae los ocho indicadores de `MatchSummary`, pero no el linaje
que HU-18 calcula para cada uno (qué eventos lo formaron, qué fórmula se
aplicó). Es la misma lógica que ya sostiene por qué el cargador de la capa
Raw (HU-14) no interpreta `attrs`: el linaje es información para quien
audita un número, no para quien simplemente lo está mirando en un dashboard
en vivo. Incluirlo habría inflado el documento sin que el consumidor
declarado —un tablero en tiempo real— tuviera uso para él, y cualquier
consulta de linaje sigue teniendo un camino: `gcperros-trace` sobre la capa
Raw, que si hiciera falta podría exponerse aparte, sin tener que cargarlo en
cada actualización del estado vivo.

### Modo nativo de Firestore, no modo Datastore

Firestore ofrece dos modos al crear la base de datos, y la elección es
permanente: no se puede cambiar de una a otra después sin recrear la base
completa. El modo Datastore es la opción pensada para cargas de trabajo de
backend clásicas, y **no ofrece listeners en tiempo real**. Elegirlo habría
significado que el propio Terraform de esta historia dejara al dashboard sin
la única vía de consumo que la historia pide explícitamente
("*consumed... through a real-time listener rather than polling*"): con
Datastore, el dashboard habría tenido que volver a sondear, que es
justamente el patrón que todo este diseño existe para evitar.

### Por qué Firestore no necesita declarar la colección en Terraform

A diferencia de una tabla de BigQuery (HU-14, sección 10), una colección de
Firestore no es un recurso que haya que crear de antemano: aparece la
primera vez que alguien escribe un documento en ella. `infra/terraform/firestore.tf`
declara únicamente la base de datos y quién puede escribir en el proyecto;
el nombre de la colección (`live_matches`) vive en código
(`gcperros.firestore.publisher.LIVE_MATCHES_COLLECTION`), no en la
infraestructura. Es una asimetría real entre los dos sistemas, no una
inconsistencia del proyecto: declarar una colección vacía en Terraform no
tendría ningún efecto observable en Firestore, así que hacerlo sólo añadiría
una entrada más que mantener sincronizada con el código sin ganar nada a
cambio.
