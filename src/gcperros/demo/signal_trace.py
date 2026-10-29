"""De dónde sale una señal del feed, con prueba (historia #25).

Hace con las señales lo que ``demo.trace`` hace con los números del marcador:
reconstruye los eventos que la produjeron y los verifica contra la huella que la
propia señal lleva. La reconstrucción no le pregunta nada al detector: lee los
flujos que la cinta ya consumió y aplica la definición del linaje de una señal
(``engine.signals``). Si no cuadra, la pantalla lo dice.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from gcperros.core.contracts import JsonValue, MatchEvent, OddsUpdate
from gcperros.core.lineage import LineageAccumulator
from gcperros.demo.market import MarketTape
from gcperros.demo.trace import TracedEvent
from gcperros.engine.signals import MARKET_MOVING_EVENTS, DiscrepancySignal


@dataclass(frozen=True, slots=True)
class SignalTrace:
    """Una señal, los eventos y la cuota que la produjeron, y si su huella cuadra."""

    signal: DiscrepancySignal
    events: tuple[TracedEvent, ...]
    update: OddsUpdate
    update_minute: int
    verified: bool

    def to_json(self) -> dict[str, JsonValue]:
        """Lo que recibe el diálogo de procedencia."""
        return {
            "operator": self.signal.operator,
            "market": self.signal.market,
            "outcome": self.signal.outcome,
            "model_version": self.signal.model_version,
            "lineage": self.signal.lineage.to_dict(),
            "verified": self.verified,
            "events": [
                {"minute": e.minute, "event_type": e.event_type, "team": e.team}
                for e in self.events
            ],
            "odds_update": {"event_id": self.update.event_id, "minute": self.update_minute},
        }


def _fixes_the_state(event: MatchEvent) -> bool:
    return event.event_type in MARKET_MOVING_EVENTS or event.attrs.get("reason") == "kickoff"


def trace_signal(tape: MarketTape, index: int, minute_at: Callable[[datetime], int]) -> SignalTrace:
    """Reconstruye y verifica la procedencia de la señal ``index`` de la cinta.

    Raises:
        IndexError: Si la cinta todavía no emitió esa señal.
    """
    if not 0 <= index < len(tape.signals):
        raise IndexError(f"no hay señal {index}")
    signal = tape.signals[index]

    seen = [e for e in tape.consumed_events if e.event_time <= signal.detected_at]
    update = [
        u
        for u in tape.consumed_odds
        if (u.operator, u.market) == (signal.operator, signal.market)
        and u.event_time <= signal.detected_at
    ][-1]
    # Los que fijan el estado, más el último, que pone el minuto.
    events = [e for e in seen if _fixes_the_state(e) or e is seen[-1]]

    fold = LineageAccumulator()
    for event_id in {e.event_id for e in events} | {update.event_id}:
        fold.add(event_id)

    return SignalTrace(
        signal=signal,
        events=tuple(
            TracedEvent(e.event_id, minute_at(e.event_time), e.event_type, e.team) for e in events
        ),
        update=update,
        update_minute=minute_at(update.event_time),
        verified=fold.digest == signal.lineage.digest,
    )
