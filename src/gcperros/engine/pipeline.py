"""Motor de procesamiento con estado.

Ordena las piezas del recorrido de un evento, y el orden no es negociable:

1. **Deduplicar** (HU-11). Antes que nada: si se aplicase primero y se
   comprobase después, el estado ya estaría corrupto cuando se detectara la
   repetición. Y va antes de reordenar para no ocupar el buffer con eventos
   que van a descartarse.
2. **Reordenar** por marca de agua (HU-12). Retiene cada evento hasta que ya no
   pueda llegar nada anterior a él.
3. **Aplicar** al estado, en orden cronológico garantizado.

Tener los tres pasos en un solo sitio legible es lo que permite discutir el
diseño sin leer el código que consume del broker.

Ninguno de los tres sabe de qué deporte es el partido (#89). ``StreamEngine``
recibe el estado por inyección (``engine/sport.py``), y ``MatchEngine`` es ese
mismo motor con el estado del fútbol, que es lo que el resto del sistema ya
usaba.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar

from gcperros.core.contracts import MatchEvent
from gcperros.core.possession import (
    MAX_IN_PLAY_GAP_S,
    POSSESSION_WINDOW_S,
    PossessionSnapshot,
    PossessionTracker,
    PossessionWindow,
)
from gcperros.core.stats import MatchSummary
from gcperros.engine.dedup import DEFAULT_CAPACITY, Deduplicator, DedupStats
from gcperros.engine.latency import LatencyRecorder, LatencyStats
from gcperros.engine.sport import SportState
from gcperros.engine.state import LiveMatchState
from gcperros.engine.watermark import (
    DEFAULT_ALLOWED_LATENESS_S,
    WatermarkReorderer,
    WatermarkStats,
)


class Outcome(StrEnum):
    """Qué hizo el motor con una entrega del broker."""

    #: Aceptado. Se aplicará al estado en cuanto la marca de agua lo rebase.
    ACCEPTED = "accepted"

    #: Repetición de un evento ya visto (HU-11).
    DUPLICATE = "duplicate"

    #: Llegó cuando su ventana ya estaba cerrada (HU-12). Queda contado, no
    #: perdido en silencio.
    DROPPED_LATE = "dropped_late"


#: El resumen del deporte: ``MatchSummary`` en fútbol, ``BasketballSummary`` en
#: baloncesto.
S_co = TypeVar("S_co", covariant=True)


@dataclass(frozen=True, slots=True)
class EngineResult(Generic[S_co]):
    """Los indicadores del partido y la traza de cómo se llegó a ellos."""

    summary: S_co
    dedup: DedupStats
    watermark: WatermarkStats
    possession: PossessionSnapshot
    possession_windows: tuple[PossessionWindow, ...]
    latency: LatencyStats


class StreamEngine(Generic[S_co]):
    """Consume eventos de un partido de cualquier deporte y mantiene su estado vivo."""

    __slots__ = (
        "_clock",
        "_closed_windows",
        "_dedup",
        "_latency",
        "_possession",
        "_reorderer",
        "_state",
    )

    def __init__(
        self,
        state: SportState[S_co],
        dedup_capacity: int = DEFAULT_CAPACITY,
        allowed_lateness_s: float = DEFAULT_ALLOWED_LATENESS_S,
        possession_window_s: float = POSSESSION_WINDOW_S,
        max_in_play_gap_s: float = MAX_IN_PLAY_GAP_S,
    ) -> None:
        """Crea un motor vacío alrededor del estado de un deporte."""
        self._dedup = Deduplicator(capacity=dedup_capacity)
        self._reorderer = WatermarkReorderer(allowed_lateness_s=allowed_lateness_s)
        self._state = state
        self._possession = PossessionTracker(
            window_s=possession_window_s,
            max_in_play_gap_s=max_in_play_gap_s,
        )
        self._closed_windows: list[PossessionWindow] = []
        self._latency = LatencyRecorder()
        # Reloj del flujo: el último instante de llegada conocido. Nunca
        # retrocede, por la misma razón que la marca de agua.
        self._clock: datetime | None = None

    @property
    def state(self) -> SportState[S_co]:
        """Estado vivo, consultable en cualquier momento del partido."""
        return self._state

    @property
    def dedup_stats(self) -> DedupStats:
        """Contadores de deduplicación, para el marco de calidad (HU-17)."""
        return self._dedup.stats

    @property
    def watermark_stats(self) -> WatermarkStats:
        """Contadores de oportunidad: cuánto se aplicó dentro de la marca de agua."""
        return self._reorderer.stats

    @property
    def possession(self) -> PossessionSnapshot:
        """Posesión acumulada y la de la ventana todavía abierta (HU-20)."""
        return self._possession.snapshot()

    @property
    def possession_windows(self) -> tuple[PossessionWindow, ...]:
        """Ventanas de posesión ya cerradas, en orden y con su cifra definitiva."""
        return tuple(self._closed_windows)

    @property
    def latency(self) -> LatencyStats:
        """Latencia de lo aplicado hasta ahora, en tiempo del flujo (#18)."""
        return self._latency.stats()

    @property
    def pending(self) -> int:
        """Eventos retenidos a la espera de que avance la marca de agua."""
        return self._reorderer.buffered

    def process(self, event: MatchEvent, arrived_at: datetime | None = None) -> Outcome:
        """Procesa una entrega del broker.

        Args:
            event: Evento tal como lo entregó Pub/Sub: puede ser una repetición
                y puede venir fuera de orden.
            arrived_at: Cuándo lo entregó el broker. Sin él, se toma el propio
                ``event_time`` como llegada, y la latencia medida es sólo la
                que añade el motor al retener el evento.

        Returns:
            Qué se hizo con él. ``ACCEPTED`` no significa «ya aplicado»: el
            evento espera en el buffer hasta que su ventana se cierre.
        """
        # Cualquier entrega, incluso una repetida, dice que ese instante ya
        # llegó: el reloj avanza antes de decidir qué hacer con el evento.
        now = arrived_at if arrived_at is not None else event.event_time
        clock = self._clock if self._clock is not None and self._clock > now else now
        self._clock = clock

        if not self._dedup.accept(event.event_id):
            return Outcome.DUPLICATE

        accepted, released = self._reorderer.push(event)
        if accepted:
            self._latency.arrived(event, now)
        for ready in released:
            self._apply(ready, clock)

        # Las ventanas las cierra la marca de agua, no la llegada de un evento
        # posterior: es la misma promesa de la HU-12 elevada a un agregado.
        watermark = self._reorderer.watermark
        if watermark is not None:
            self._closed_windows.extend(self._possession.close_through(watermark))

        return Outcome.ACCEPTED if accepted else Outcome.DROPPED_LATE

    def _apply(self, event: MatchEvent, at: datetime) -> None:
        self._state.apply(event)
        self._possession.apply(event)
        self._latency.applied(event, at)

    def provisional(self) -> S_co:
        """La vista provisional: lo aplicado más lo que espera a la marca de agua.

        Un gol o una canasta aparece aquí en cuanto llega, sin esperar al
        margen; es la segunda salida de la sección 3 para el SLA. Lo exacto no
        se corrige nunca —contar no depende del orden—, y cuando la ventana se
        cierra la vista definitiva da lo mismo. El estado vivo no se toca: se
        trabaja sobre una copia.
        """
        view = copy.deepcopy(self._state)
        for event in self._reorderer.pending():
            view.apply(event)
        return view.summary()

    def flush(self) -> None:
        """Aplica lo que quedaba retenido y cierra las ventanas que faltaban.

        Al cerrarse el flujo ya no va a llegar nada más, así que la última
        ventana se da por terminada aunque la marca de agua no haya alcanzado su
        borde derecho: retenerla sólo la perdería.
        """
        if self._clock is None:
            return  # no entró nada: no hay buffer que vaciar ni ventana que cerrar

        last: MatchEvent | None = None
        for event in self._reorderer.flush():
            self._apply(event, self._clock)
            last = event

        final = last.event_time if last is not None else self._reorderer.watermark
        if final is not None:
            self._closed_windows.extend(self._possession.close_through(final))

    def process_all(self, events: list[MatchEvent]) -> EngineResult[S_co]:
        """Procesa un flujo completo, lo vacía y devuelve el resultado."""
        for event in events:
            self.process(event)
        self.flush()
        return self.result()

    def result(self) -> EngineResult[S_co]:
        """Instantánea de los indicadores y de los contadores de calidad.

        Refleja lo aplicado **hasta ahora**: lo que siga en el buffer esperando
        a la marca de agua todavía no cuenta.
        """
        return EngineResult(
            summary=self._state.summary(),
            dedup=self._dedup.stats,
            watermark=self._reorderer.stats,
            possession=self._possession.snapshot(),
            possession_windows=tuple(self._closed_windows),
            latency=self._latency.stats(),
        )


class MatchEngine(StreamEngine[MatchSummary]):
    """El motor con el estado del fútbol: el que usaba todo el sistema."""

    __slots__ = ("_live",)

    def __init__(
        self,
        dedup_capacity: int = DEFAULT_CAPACITY,
        allowed_lateness_s: float = DEFAULT_ALLOWED_LATENESS_S,
        possession_window_s: float = POSSESSION_WINDOW_S,
        max_in_play_gap_s: float = MAX_IN_PLAY_GAP_S,
    ) -> None:
        """Crea un motor de fútbol con sus componentes vacíos."""
        live = LiveMatchState()
        super().__init__(
            live, dedup_capacity, allowed_lateness_s, possession_window_s, max_in_play_gap_s
        )
        self._live = live

    @property
    def state(self) -> LiveMatchState:
        """Estado vivo del fútbol, con todo lo que sólo él sabe hacer."""
        return self._live
