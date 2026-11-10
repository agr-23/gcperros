"""El contrato del baloncesto (#87)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from gcperros.core.contracts import (
    BASKETBALL_EVENT_TYPES,
    ContractViolationError,
    JsonValue,
    MatchEvent,
    parse_basketball_event,
    parse_match_event,
)
from gcperros.core.schema import BASKETBALL_VARIANTS, SCHEMAS

T0 = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)

#: Un evento válido de cada tipo, con los atributos que exige el contrato.
VALID_ATTRS: dict[str, dict[str, JsonValue]] = {
    "possession_change": {"from_team": "BOS", "to_team": "LAL", "reason": "jump_ball", "period": 1},
    "shot": {
        "x": 21.0,
        "y": 7.5,
        "points_value": 3,
        "made": True,
        "make_probability": 0.36,
        "period": 1,
    },
    "free_throw": {"made": False, "make_probability": 0.76, "period": 2},
    "rebound": {"kind": "offensive", "period": 3},
    "turnover": {"kind": "shot_clock_violation", "period": 4},
    "foul": {"against_team": "LAL", "free_throws": 2, "period": 4},
    "timeout": {"period": 5},
}


def _message(event_type: str, attrs: dict[str, JsonValue]) -> str:
    payload: dict[str, JsonValue] = {
        "event_id": f"ev-{event_type}",
        "event_time": "2026-11-12T20:00:00.000Z",
        "match_id": "bkb-0001",
        "team": "BOS",
        "event_type": event_type,
        "contract_version": "v1",
        "attrs": attrs,
    }
    return json.dumps(payload)


def test_every_basketball_event_type_has_its_variant() -> None:
    assert set(BASKETBALL_VARIANTS) == BASKETBALL_EVENT_TYPES == set(VALID_ATTRS)
    assert "basketball-events" in SCHEMAS


def test_the_same_envelope_round_trips() -> None:
    """El sobre es el del fútbol: el motor podrá deduplicar y reordenar igual."""
    event = MatchEvent(
        event_id="ev-1",
        event_time=T0,
        match_id="bkb-0001",
        team="BOS",
        event_type="shot",
        attrs=dict(VALID_ATTRS["shot"]),
    )

    assert parse_basketball_event(event.to_json()) == event


def test_each_sport_parses_only_its_own_vocabulary() -> None:
    """Un tiro libre no es fútbol y un gol no es baloncesto."""
    with pytest.raises(ContractViolationError, match="desconocido"):
        parse_match_event(_message("free_throw", VALID_ATTRS["free_throw"]))
    with pytest.raises(ContractViolationError, match="desconocido"):
        parse_basketball_event(_message("goal", {"x": 1.0, "y": 1.0, "xg": 0.1, "period": 1}))
