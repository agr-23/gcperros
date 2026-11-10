"""El contrato de las cuotas del baloncesto y su frontera (#90)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from gcperros.core.contracts import (
    ContractViolationError,
    JsonValue,
    OddsUpdate,
    parse_basketball_odds_update,
    parse_odds_update,
)
from gcperros.core.schema import SCHEMAS
from gcperros.governance.gate import basketball_odds_gate, odds_update_gate
from gcperros.governance.quarantine import InMemoryInvalidStore

T0 = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)

MONEYLINE = OddsUpdate(
    event_id="od-1",
    event_time=T0,
    match_id="bkb-1",
    operator="OP-A",
    market="moneyline",
    odds={"home": 1.80, "away": 2.05},
    trigger="open",
)
TOTAL = OddsUpdate(
    event_id="od-2",
    event_time=T0,
    match_id="bkb-1",
    operator="OP-B",
    market="total_points",
    odds={"over": 1.90, "under": 1.90},
    trigger="run",
    line=161.5,
)


def _tampered(update: OddsUpdate, **changes: JsonValue) -> str:
    payload = update.to_dict()
    payload.update(changes)
    return json.dumps(payload)


def test_the_stream_is_declared_next_to_the_others() -> None:
    assert "basketball-odds" in SCHEMAS


@pytest.mark.parametrize("update", [MONEYLINE, TOTAL])
def test_a_valid_quote_crosses_the_gate_and_round_trips(update: OddsUpdate) -> None:
    gate = basketball_odds_gate(InMemoryInvalidStore(), clock=lambda: T0)

    assert gate.admit(update.to_json()) == update
    assert parse_basketball_odds_update(update.to_json()) == update


def test_only_the_total_carries_a_line() -> None:
    assert "line" not in MONEYLINE.to_dict()
    assert TOTAL.to_dict()["line"] == 161.5


def test_a_total_without_its_line_cannot_be_read() -> None:
    payload = TOTAL.to_dict()
    del payload["line"]

    with pytest.raises(ContractViolationError, match="línea"):
        parse_basketball_odds_update(json.dumps(payload))


@pytest.mark.parametrize(
    "message",
    [
        _tampered(MONEYLINE, market="1x2"),
        _tampered(MONEYLINE, trigger="goal"),
        _tampered(MONEYLINE, outcomes=[{"outcome": "home", "odds": 1.8}]),
        _tampered(TOTAL, line=-3.0),
    ],
    ids=["mercado del fútbol", "gol", "mercado incompleto", "línea negativa"],
)
def test_what_breaks_the_contract_is_rejected(message: str) -> None:
    gate = basketball_odds_gate(InMemoryInvalidStore(), clock=lambda: T0)

    assert gate.admit(message) is None
    assert gate.stats.rejected == 1


def test_the_two_sports_do_not_mix() -> None:
    """Un ganador sin empate no es fútbol, y una racha no mueve un 1X2."""
    football = odds_update_gate(InMemoryInvalidStore(), clock=lambda: T0)

    assert football.admit(MONEYLINE.to_json()) is None
    with pytest.raises(ContractViolationError, match="desconocido"):
        parse_odds_update(MONEYLINE.to_json())
