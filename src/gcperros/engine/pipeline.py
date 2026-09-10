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
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

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


@dataclass(frozen=True, slots=True)
class EngineResult:
    """Los indicadores del partido y la traza de cómo se llegó a ellos."""

    summary: MatchSummary
    dedup: DedupStats
    watermark: WatermarkStats
    possession: PossessionSnapshot
    possession_windows: tuple[PossessionWindow, ...]


class MatchEngine:
    """Consume eventos de un partido y mantiene su estado vivo."""

    __slots__ = ("_closed_windows", "_dedup", "_possession", "_reorderer", "_state")

    def __init__(
        self,
        dedup_capacity: int = DEFAULT_CAPACITY,
        allowed_lateness_s: float = DEFAULT_ALLOWED_LATENESS_S,
        possession_window_s: float = POSSESSION_WINDOW_S,
        max_in_play_gap_s: float = MAX_IN_PLAY_GAP_S,
    ) -> None:
        """Crea un motor con sus componentes vacíos."""
        self._dedup = Deduplicator(capacity=dedup_capacity)
        self._reorderer = WatermarkReorderer(allowed_lateness_s=allowed_lateness_s)
        self._state = LiveMatchState()
        self._possession = PossessionTracker(
            window_s=possession_window_s,
            max_in_play_gap_s=max_in_play_gap_s,
        )
        self._closed_windows: list[PossessionWindow] = []

    @property
    def state(self) -> LiveMatchState:
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
    def pending(self) -> int:
        """Eventos retenidos a la espera de que avance la marca de agua."""
        return self._reorderer.buffered

    def process(self, event: MatchEvent) -> Outcome:
        """Procesa una entrega del broker.

        Args:
            event: Evento tal como lo entregó Pub/Sub: puede ser una repetición
                y puede venir fuera de orden.

        Returns:
            Qué se hizo con él. ``ACCEPTED`` no significa «ya aplicado»: el
            evento espera en el buffer hasta que su ventana se cierre.
        """
        if not self._dedup.accept(event.event_id):
            return Outcome.DUPLICATE

        accepted, released = self._reorderer.push(event)
        for ready in released:
            self._apply(ready)

        # Las ventanas las cierra la marca de agua, no la llegada de un evento
        # posterior: es la misma promesa de la HU-12 elevada a un agregado.
        watermark = self._reorderer.watermark
        if watermark is not None:
            self._closed_windows.extend(self._possession.close_through(watermark))

        return Outcome.ACCEPTED if accepted else Outcome.DROPPED_LATE

    def _apply(self, event: MatchEvent) -> None:
        self._state.apply(event)
        self._possession.apply(event)

    def flush(self) -> None:
        """Aplica lo que quedaba retenido y cierra las ventanas que faltaban.

        Al cerrarse el flujo ya no va a llegar nada más, así que la última
        ventana se da por terminada aunque la marca de agua no haya alcanzado su
        borde derecho: retenerla sólo la perdería.
        """
        last: MatchEvent | None = None
        for event in self._reorderer.flush():
            self._apply(event)
            last = event

        final = last.event_time if last is not None else self._reorderer.watermark
        if final is not None:
            self._closed_windows.extend(self._possession.close_through(final))

    def process_all(self, events: list[MatchEvent]) -> EngineResult:
        """Procesa un flujo completo, lo vacía y devuelve el resultado."""
        for event in events:
            self.process(event)
        self.flush()
        return self.result()

    def result(self) -> EngineResult:
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
        )
