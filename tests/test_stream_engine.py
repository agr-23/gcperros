"""El motor no sabe de qué deporte es el partido (#89).

Se le inyecta un estado inventado, que no es ni fútbol ni baloncesto, y el motor
tiene que deduplicarlo, reordenarlo y aplicarlo igual que siempre.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from gcperros.core.contracts import MatchEvent
from gcperros.core.lineage import LineageAccumulator, LineageRecord
from gcperros.core.stats import MatchSummary
from gcperros.engine.pipeline import MatchEngine, Outcome, StreamEngine
from gcperros.engine.sport import SportState
from gcperros.engine.state import LiveMatchState

T0 = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)


class _TapeState:
    """Un «deporte» cuyo único indicador es la cinta de eventos en el orden aplicado."""

    contract_version = "v1"
    team_indicators: tuple[str, ...] = ()
    models_by_indicator: Mapping[str, Mapping[str, str]] = {}

    def __init__(self) -> None:
        self.tape: list[str] = []
        self._lineage = LineageAccumulator()

    def apply(self, event: MatchEvent) -> None:
        self.tape.append(event.event_id)
        self._lineage.add(event.event_id)

    def summary(self) -> tuple[str, ...]:
        return tuple(self.tape)

    def lineage(self, indicator: str, scope: str) -> LineageRecord:
        return self._lineage.record(indicator, scope)

    def lineage_records(self) -> tuple[LineageRecord, ...]:
        return (self._lineage.record("tape", "*"),)

    @property
    def event_count(self) -> int:
        return len(self.tape)

    @property
    def teams(self) -> tuple[str, ...]:
        return ()


def _event(n: int) -> MatchEvent:
    return MatchEvent(
        event_id=f"ev-{n}",
        event_time=T0 + timedelta(seconds=n),
        match_id="m-1",
        team="A",
        event_type="timeout",
        attrs={"period": 1},
    )


def test_an_injected_state_is_deduplicated_and_ordered_like_any_other() -> None:
    engine = StreamEngine(_TapeState(), allowed_lateness_s=10)
    delivered = [_event(n) for n in (3, 1, 2, 2, 5, 4, 1, 6)]

    outcomes = [engine.process(event) for event in delivered]
    result = engine.process_all([])

    assert outcomes.count(Outcome.DUPLICATE) == 2
    assert result.summary == ("ev-1", "ev-2", "ev-3", "ev-4", "ev-5", "ev-6")
    assert result.dedup.duplicates == 2


def test_the_engine_exposes_the_state_it_was_given() -> None:
    state = _TapeState()
    engine = StreamEngine(state)

    engine.process_all([_event(1)])

    assert engine.state is state
    assert engine.state.event_count == 1


def test_the_football_engine_is_the_same_engine_with_the_football_state() -> None:
    engine = MatchEngine()
    football: SportState[MatchSummary] = engine.state

    assert isinstance(engine, StreamEngine)
    assert isinstance(engine.state, LiveMatchState)
    assert football.team_indicators[0] == "goals"
    assert football.models_by_indicator["total_xg"]["xg"].startswith("xg-")
