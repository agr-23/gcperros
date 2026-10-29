"""De la frontera no sale ningún dato de usuario en claro (historia #27)."""

from __future__ import annotations

import hashlib
import json

import pytest

from gcperros.core.contracts import MARKET_OUTCOMES
from gcperros.governance.privacy import KEY_ENV, Pseudonymizer, UserActivityGate

KEY = bytes(range(32))
SESSION = "sess-7f3a-alejandra-movil"


def _message(**overrides: object) -> str:
    base: dict[str, object] = {
        "session_id": SESSION,
        "markets": ["1x2", "over_under_2_5"],
        "match_id": "match-0027",
        "event_time": "2026-08-26T19:10:00.000Z",
    }
    return json.dumps({**base, **overrides})


def test_nothing_personal_leaves_the_gate() -> None:
    gate = UserActivityGate(Pseudonymizer(KEY))

    activity = gate.admit(_message())

    assert activity is not None
    assert SESSION not in repr(activity)
    assert not {"1x2", "over_under_2_5"} & set(activity.markets)


def test_the_same_person_gets_the_same_pseudonym_so_it_can_be_counted() -> None:
    gate = UserActivityGate(Pseudonymizer(KEY))

    first, second = gate.admit(_message()), gate.admit(_message(markets=["1x2"]))

    assert first is not None and second is not None
    assert first.session == second.session
    assert set(second.markets) < set(first.markets)


def test_without_the_key_it_does_not_reverse_nor_link_across_fields() -> None:
    """Con dos mercados posibles, un SHA-256 sin clave se revierte probándolos."""
    activity = UserActivityGate(Pseudonymizer(KEY)).admit(_message())
    other = UserActivityGate(Pseudonymizer(bytes(32))).admit(_message())
    unkeyed = {hashlib.sha256(market.encode()).hexdigest() for market in MARKET_OUTCOMES}

    assert activity is not None and other is not None
    assert not unkeyed & set(activity.markets)
    assert other.session != activity.session
    pseudonymizer = Pseudonymizer(KEY)
    assert pseudonymizer.pseudonym("session", "1x2") != pseudonymizer.pseudonym("market", "1x2")


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        (_message(session_id=""), "session_id"),
        (_message(markets=["corners"]), "markets"),
        (_message(match_id=7), "match_id"),
        (_message(event_time="ayer"), "event_time"),
        ("{no es json", "malformed"),
        ('["una", "lista"]', "malformed"),
    ],
)
def test_a_rejection_is_counted_by_field_and_forgotten(message: str, reason: str) -> None:
    """La frontera deportiva archiva lo rechazado; esta no, o archivaría la sesión."""
    gate = UserActivityGate(Pseudonymizer(KEY))

    assert gate.admit(message) is None
    assert (gate.admitted, gate.rejected) == (0, {reason: 1})
    assert SESSION not in repr(gate.rejected)


def test_the_key_comes_from_the_environment_and_never_shows() -> None:
    pseudonymizer = Pseudonymizer.from_env({KEY_ENV: KEY.hex()})

    assert KEY.hex() not in repr(pseudonymizer)
    with pytest.raises(ValueError, match=KEY_ENV):
        Pseudonymizer.from_env({})
    with pytest.raises(ValueError, match="32 bytes"):
        Pseudonymizer(b"corta")
