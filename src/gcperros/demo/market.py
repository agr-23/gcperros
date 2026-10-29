"""El mercado de la repetición: precios vigentes, modelo y señales (#32).

Es lo que el cliente compra: *te avisamos cuando un operador tiene un precio
viejo, antes de que el mercado lo corrija*. Esta cinta recorre las cuotas y los
eventos del partido intercalados por tiempo, igual que la referencia batch de la
HU-19, pero hasta el instante que marque el reloj de la repetición.

No hay lógica nueva de señales: la cinta alimenta a ``DiscrepancyDetector`` tal
cual. Lo único que añade es memoria para enseñarlo —el último precio de cada
operador y lo que cree el modelo en cada momento—, y hay una prueba que exige
que, al pitido final, las señales sean exactamente las del batch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from gcperros.core.contracts import MatchEvent, OddsUpdate
from gcperros.core.odds import implied_probabilities
from gcperros.engine.signals import (
    DEFAULT_THRESHOLD,
    DiscrepancyDetector,
    DiscrepancySignal,
    model_probabilities,
)

#: Señales que se enseñan a la vez. El resto sigue contado en ``total_signals``.
RECENT_SIGNALS = 12


@dataclass(frozen=True, slots=True)
class MarketView:
    """El resultado final (1X2) según el modelo y según cada operador, y las señales."""

    model: dict[str, float]
    operators: dict[str, dict[str, float]]
    recent_signals: tuple[DiscrepancySignal, ...]
    total_signals: int


class MarketTape:
    """Recorre cuotas y eventos intercalados por tiempo hasta donde se le pida."""

    __slots__ = ("_books", "_detector", "_events", "_next_event", "_next_odds", "_odds", "_signals")

    def __init__(
        self,
        match_events: list[MatchEvent],
        odds_updates: list[OddsUpdate],
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        """Prepara la cinta antes del pitido inicial."""
        self._events = sorted(match_events, key=lambda event: event.event_time)
        self._odds = sorted(odds_updates, key=lambda update: update.event_time)
        self._next_event = 0
        self._next_odds = 0
        self._detector = DiscrepancyDetector(threshold=threshold)
        # Probabilidad implícita, sin margen, del último 1X2 de cada operador.
        self._books: dict[str, dict[str, float]] = {}
        self._signals: list[DiscrepancySignal] = []

    def advance_to(self, instant: datetime) -> int:
        """Consume todo lo ocurrido hasta ``instant`` y devuelve las señales nuevas.

        Ante un empate de tiempos va primero el evento: una cuota se evalúa
        contra el partido tal como estaba cuando se publicó, que ya incluye lo
        ocurrido en ese mismo instante. Es el mismo orden que el batch.
        """
        before = len(self._signals)
        while True:
            event = self._events[self._next_event] if self._next_event < len(self._events) else None
            update = self._odds[self._next_odds] if self._next_odds < len(self._odds) else None
            if (
                event is not None
                and event.event_time <= instant
                and (update is None or event.event_time <= update.event_time)
            ):
                self._signals.extend(self._detector.apply_match_event(event))
                self._next_event += 1
            elif update is not None and update.event_time <= instant:
                self._signals.extend(self._detector.evaluate(update))
                if update.market == "1x2":
                    self._books[update.operator] = implied_probabilities(update.odds)
                self._next_odds += 1
            else:
                return len(self._signals) - before

    @property
    def signals(self) -> tuple[DiscrepancySignal, ...]:
        """Todas las señales emitidas hasta ahora, en orden."""
        return tuple(self._signals)

    @property
    def consumed_events(self) -> tuple[MatchEvent, ...]:
        """Los eventos del partido que la cinta ya consumió, en orden de tiempo."""
        return tuple(self._events[: self._next_event])

    @property
    def consumed_odds(self) -> tuple[OddsUpdate, ...]:
        """Las cuotas que la cinta ya consumió, en orden de tiempo."""
        return tuple(self._odds[: self._next_odds])

    def view(self, recent: int = RECENT_SIGNALS) -> MarketView:
        """El mercado en el instante actual, con las señales más nuevas primero."""
        model = model_probabilities("1x2", self._detector.state)
        return MarketView(
            model={outcome: round(p, 4) for outcome, p in model.items()},
            operators={
                operator: {outcome: round(p, 4) for outcome, p in book.items()}
                for operator, book in sorted(self._books.items())
            },
            recent_signals=tuple(reversed(self._signals[-recent:])) if recent else (),
            total_signals=len(self._signals),
        )
