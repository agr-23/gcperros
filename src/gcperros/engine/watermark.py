"""Reordenamiento por tiempo de evento mediante marca de agua (HU-12).

El broker entrega sin orden. Un pase emitido en el minuto 12 puede llegar
después de otro del minuto 13, y aplicar los eventos en orden de llegada
corrompería la secuencia cronológica del partido.

La marca de agua es el **reloj de confianza** del motor: la afirmación «doy por
recibido todo lo anterior a este instante». Se calcula como el mayor
``event_time`` visto menos un margen de desorden tolerado. Los eventos esperan en
un buffer ordenado y sólo se liberan cuando la marca de agua los rebasa, momento
en el que ya no puede llegar nada anterior a ellos.

El compromiso, que es el punto
------------------------------
El margen tolerado no es un parámetro más: es la perilla que gradúa latencia
contra completitud.

* Margen **grande**: casi ningún evento llega tarde, pero todos esperan más
  antes de aplicarse, y el estado vivo va por detrás del partido.
* Margen **pequeño**: el estado va casi al día, pero los eventos rezagados
  encuentran su ventana ya cerrada.

Por eso un evento que llega tarde se registra como **descartado por tardío** y
no se pierde en silencio. Esa cuenta es la que permite auditar después cuánta
información se sacrificó a cambio de latencia, y alimenta la dimensión de
*oportunidad* del marco de calidad (HU-17), cuyo umbral declarado es que al
menos el 95 % de los eventos se apliquen dentro de la marca de agua.

Cómo se eligió el margen por defecto
------------------------------------
Medido sobre ocho partidos con retardo de red exponencial de media 2 s y cola
acotada a 30 s, que es la perturbación por defecto del inyector:

======== ============= =============== ========== ==============
 Margen   Oportunidad   Div. posesión   Div. xG    Cumple OE-2
======== ============= =============== ========== ==============
    0 s        87,22 %         11,05 %     0,3391   no
    1 s        89,52 %          9,27 %     0,0000   no
    3 s        94,80 %          6,32 %     0,0000   no
    5 s        98,28 %          2,15 %     0,0000   no
   10 s        99,91 %          0,17 %     0,0000   **sí**
   20 s       100,00 %          0,00 %     0,0000   sí
======== ============= =============== ========== ==============

El proyecto declara divergencia máxima del 1 % en posesión y de 0,05 en xG
frente al plano batch, y oportunidad mínima del 95 %. Diez segundos es el
margen más ajustado que cumple los tres criterios, y por eso es el valor por
defecto.

Una tensión que conviene tener presente
---------------------------------------
Ese margen entra en conflicto con el SLA declarado de latencia extremo a extremo
por debajo de 2 s en el percentil 95: un evento retenido a la espera de la marca
de agua espera del orden del propio margen antes de aplicarse. Los dos objetivos
no se pueden cumplir a la vez con este diseño, y la elección está documentada en
vez de disimulada. Resolverlo —publicando estado provisional y corrigiéndolo al
cerrar la ventana, por ejemplo— corresponde al sprint que caracteriza la latencia
bajo carga (OE-3).

Eventos con el mismo instante
-----------------------------
El contrato no define un orden entre eventos que comparten ``event_time`` —el
gol y el remate que lo produjo se emiten en el mismo instante, por ejemplo—, así
que se desempata por ``event_id`` para que el resultado sea determinista
independientemente del orden de llegada. Los indicadores del partido son
recuentos y sumas, que conmutan, de modo que ese desempate no altera el estado.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from datetime import datetime, timedelta

from gcperros.core.contracts import MatchEvent

#: Margen de desorden tolerado por defecto, en segundos. No es un número
#: redondo elegido a ojo: es el más pequeño de los medidos que cumple a la vez
#: los dos umbrales del OE-2. Ver la tabla del encabezado del módulo.
DEFAULT_ALLOWED_LATENESS_S = 10.0


@dataclass(frozen=True, slots=True)
class WatermarkStats:
    """Qué se aplicó, qué llegó tarde y cuánto se esperó por ello."""

    released: int
    dropped_late: int
    max_lateness_s: float
    total_lateness_s: float
    max_buffered: int

    @property
    def seen(self) -> int:
        """Eventos ofrecidos al reordenador."""
        return self.released + self.dropped_late

    @property
    def timeliness(self) -> float:
        """Proporción aplicada dentro de la marca de agua.

        Es la métrica de *oportunidad* del marco de calidad: el umbral declarado
        por el proyecto es 0,95.
        """
        return self.released / self.seen if self.seen else 1.0

    @property
    def mean_lateness_s(self) -> float:
        """Retraso medio de los eventos que llegaron fuera de plazo."""
        return self.total_lateness_s / self.dropped_late if self.dropped_late else 0.0


class WatermarkReorderer:
    """Ordena por ``event_time`` reteniendo los eventos hasta que sea seguro."""

    __slots__ = (
        "_allowed_lateness",
        "_buffer",
        "_dropped_late",
        "_max_buffered",
        "_max_event_time",
        "_max_lateness_s",
        "_released",
        "_total_lateness_s",
        "_watermark",
    )

    def __init__(self, allowed_lateness_s: float = DEFAULT_ALLOWED_LATENESS_S) -> None:
        """Crea un reordenador con el margen de desorden indicado.

        Args:
            allowed_lateness_s: Segundos de desorden que se toleran. Cuánto más
                alto, menos descartes y más latencia.

        Raises:
            ValueError: Si el margen es negativo.
        """
        if allowed_lateness_s < 0:
            raise ValueError("el margen de desorden no puede ser negativo")

        self._allowed_lateness = timedelta(seconds=allowed_lateness_s)
        # Montículo de (tiempo de evento, identificador, evento). El
        # identificador desempata y, al ser único, el evento nunca se compara.
        self._buffer: list[tuple[datetime, str, MatchEvent]] = []
        self._watermark: datetime | None = None
        self._max_event_time: datetime | None = None
        self._released = 0
        self._dropped_late = 0
        self._max_lateness_s = 0.0
        self._total_lateness_s = 0.0
        self._max_buffered = 0

    @property
    def watermark(self) -> datetime | None:
        """Instante hasta el que el motor da por completa la información."""
        return self._watermark

    @property
    def buffered(self) -> int:
        """Eventos esperando a que la marca de agua los rebase."""
        return len(self._buffer)

    @property
    def stats(self) -> WatermarkStats:
        """Instantánea de los contadores."""
        return WatermarkStats(
            released=self._released,
            dropped_late=self._dropped_late,
            max_lateness_s=self._max_lateness_s,
            total_lateness_s=self._total_lateness_s,
            max_buffered=self._max_buffered,
        )

    def push(self, event: MatchEvent) -> tuple[bool, list[MatchEvent]]:
        """Ofrece un evento y devuelve los que ya son seguros de aplicar.

        Args:
            event: Evento entregado por el broker, posiblemente desordenado.

        Returns:
            Par ``(aceptado, liberados)``. ``aceptado`` es ``False`` cuando el
            evento llegó con su ventana ya cerrada. ``liberados`` trae los
            eventos cuya ventana acaba de cerrarse, en orden cronológico, y
            puede venir vacío aunque el evento se haya aceptado: lo normal es
            que se quede esperando en el buffer.
        """
        if self._watermark is not None and event.event_time <= self._watermark:
            # Su ventana ya se cerró: no se aplica, pero queda contado.
            lateness = (self._watermark - event.event_time).total_seconds()
            self._dropped_late += 1
            self._total_lateness_s += lateness
            self._max_lateness_s = max(self._max_lateness_s, lateness)
            return False, []

        heapq.heappush(self._buffer, (event.event_time, event.event_id, event))
        self._max_buffered = max(self._max_buffered, len(self._buffer))

        self._advance_watermark(event.event_time)
        return True, self._release()

    def flush(self) -> list[MatchEvent]:
        """Vacía el buffer al cerrarse el flujo.

        Al terminar el partido ya no va a llegar nada más, así que retener
        eventos a la espera de la marca de agua sólo los perdería.
        """
        pending = [heapq.heappop(self._buffer)[2] for _ in range(len(self._buffer))]
        self._released += len(pending)
        if self._max_event_time is not None:
            self._watermark = self._max_event_time
        return pending

    def _advance_watermark(self, event_time: datetime) -> None:
        """Mueve el reloj de confianza, que nunca retrocede."""
        if self._max_event_time is None or event_time > self._max_event_time:
            self._max_event_time = event_time

        candidate = self._max_event_time - self._allowed_lateness
        # La monotonía es una garantía del modelo: si la marca de agua pudiera
        # retroceder, una ventana ya cerrada podría reabrirse y el estado
        # dejaría de ser reproducible.
        if self._watermark is None or candidate > self._watermark:
            self._watermark = candidate

    def _release(self) -> list[MatchEvent]:
        """Extrae del buffer todo lo que la marca de agua ya rebasó."""
        if self._watermark is None:
            return []

        ready: list[MatchEvent] = []
        while self._buffer and self._buffer[0][0] <= self._watermark:
            ready.append(heapq.heappop(self._buffer)[2])

        self._released += len(ready)
        return ready
