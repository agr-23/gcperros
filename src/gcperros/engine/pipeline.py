"""Motor de procesamiento con estado.

Ordena las piezas del recorrido de un evento: primero se decide si hay que
procesarlo, después se aplica. El orden importa y por eso está aquí explícito,
en un único sitio legible, en vez de repartido por el código que consume del
broker.

De momento el motor sólo deduplica (HU-11). El reordenamiento por marca de agua
sobre ``event_time`` (HU-12) se insertará entre la deduplicación y la aplicación
al estado, que es el único punto donde tiene sentido: reordenar antes de
deduplicar obligaría a mantener en el buffer eventos que van a descartarse.
"""

from __future__ import annotations

from dataclasses import dataclass

from gcperros.core.contracts import MatchEvent
from gcperros.core.stats import MatchSummary
from gcperros.engine.dedup import DEFAULT_CAPACITY, Deduplicator, DedupStats
from gcperros.engine.state import LiveMatchState


@dataclass(frozen=True, slots=True)
class EngineResult:
    """Resultado de procesar un flujo: los indicadores y cómo se llegó a ellos."""

    summary: MatchSummary
    dedup: DedupStats


class MatchEngine:
    """Consume eventos de un partido y mantiene su estado vivo."""

    __slots__ = ("_dedup", "_state")

    def __init__(self, dedup_capacity: int = DEFAULT_CAPACITY) -> None:
        """Crea un motor con su deduplicador y su estado vacíos."""
        self._dedup = Deduplicator(capacity=dedup_capacity)
        self._state = LiveMatchState()

    @property
    def state(self) -> LiveMatchState:
        """Estado vivo, consultable en cualquier momento del partido."""
        return self._state

    @property
    def dedup_stats(self) -> DedupStats:
        """Contadores de deduplicación, para el marco de calidad (HU-17)."""
        return self._dedup.stats

    def process(self, event: MatchEvent) -> bool:
        """Procesa una entrega del broker.

        Args:
            event: Evento tal como lo entregó Pub/Sub, que puede ser una
                repetición de otro ya recibido.

        Returns:
            ``True`` si el evento se aplicó al estado, ``False`` si se descartó
            por duplicado.
        """
        # La deduplicación va antes de tocar el estado. Al revés, el estado ya
        # estaría corrupto cuando se detectara la repetición.
        if not self._dedup.accept(event.event_id):
            return False

        self._state.apply(event)
        return True

    def process_all(self, events: list[MatchEvent]) -> EngineResult:
        """Procesa un flujo completo y devuelve el resultado."""
        for event in events:
            self.process(event)
        return self.result()

    def result(self) -> EngineResult:
        """Instantánea de los indicadores y de los contadores de calidad."""
        return EngineResult(summary=self._state.summary(), dedup=self._dedup.stats)
