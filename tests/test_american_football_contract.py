"""El contrato del fútbol americano, el tercer deporte, y su frontera.

El mismo sobre que el fútbol y el baloncesto, con su vocabulario cerrado: lo
que el motor necesita para deduplicar y reordenar no cambia, y lo que la
frontera juzga es propio.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from gcperros.core.contracts import (
    AmericanFootballEventType,
    ContractViolationError,
    JsonValue,
    MatchEvent,
    new_event_id,
    parse_american_football_event,
)
from gcperros.governance.gate import american_football_event_gate
from gcperros.governance.quarantine import InMemoryInvalidStore

KICKOFF = datetime(2026, 11, 15, 18, 0, tzinfo=UTC)


def _event(event_type: AmericanFootballEventType, **attrs: JsonValue) -> MatchEvent:
    return MatchEvent(
        event_id=new_event_id("nfl-1", len(attrs)),
        event_time=KICKOFF,
        match_id="nfl-1",
        team="KC",
        event_type=event_type,
        attrs={"period": 1, "clock_s": 900.0, **attrs},
    )


VALID = [
    _event("possession_change", from_team="BUF", to_team="KC", reason="kickoff"),
    _event("play", kind="pass_complete", yards=14, down=2),
    _event("touchdown"),
    _event("conversion", kind="kick", made=True, make_probability=0.94),
    _event("field_goal", distance_yd=47, made=False, make_probability=0.69),
    _event("punt", yards=45),
    _event("turnover", kind="interception"),
    _event("safety"),
    _event("timeout"),
]


@pytest.mark.parametrize("event", VALID, ids=lambda event: event.event_type)
def test_every_event_type_crosses_the_gate_as_it_left(event: MatchEvent) -> None:
    gate = american_football_event_gate(InMemoryInvalidStore())

    admitted = gate.admit(event.to_json())

    assert admitted == event == parse_american_football_event(event.to_json())


@pytest.mark.parametrize(
    "event",
    [
        _event("field_goal", distance_yd=75, made=True, make_probability=0.1),
        _event("play", kind="pass_complete", yards=120, down=1),
        _event("play", kind="pass_complete", yards=5, down=5),
        _event("conversion", kind="drop_kick", made=True, make_probability=0.9),
        _event("possession_change", from_team="BUF", to_team="KC", reason="onside"),
    ],
    ids=["gol-de-75", "jugada-de-120", "quinto-down", "conversion-rara", "motivo-raro"],
)
def test_what_the_rules_do_not_allow_is_rejected_with_its_cause(event: MatchEvent) -> None:
    invalid = InMemoryInvalidStore()

    assert american_football_event_gate(invalid).admit(event.to_json()) is None
    assert len(invalid.records) == 1 and invalid.records[0].causes


def test_another_sport_s_vocabulary_is_not_american_football() -> None:
    rebound = _event("play", kind="run", yards=3, down=1).to_json().replace('"play"', '"rebound"')

    with pytest.raises(ContractViolationError, match="tipo de evento desconocido"):
        parse_american_football_event(rebound)
