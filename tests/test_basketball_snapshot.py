"""Lo que recibe la página del baloncesto: el documento, su deporte y sus cuartos (#92)."""

from __future__ import annotations

from gcperros.core import court
from gcperros.core.contracts import JsonValue
from gcperros.demo.replay import BasketballReplay, MatchReplay
from gcperros.demo.snapshot import take_snapshot
from gcperros.generators.basketball import BasketballConfig, simulate_basketball
from gcperros.generators.match import MatchConfig, simulate_match

TEAMS = ("BOS", "LAL")
EVENTS = simulate_basketball(65, BasketballConfig("demo-bkb-65", *TEAMS))


def _obj(value: JsonValue) -> dict[str, JsonValue]:
    assert isinstance(value, dict)
    return value


def test_the_snapshot_carries_the_sport_and_the_points_by_quarter() -> None:
    replay = BasketballReplay(EVENTS, TEAMS)
    replay.advance_to(replay.duration_s)

    payload = take_snapshot(replay).to_json()

    assert payload["sport"] == "basketball"
    assert _obj(payload["clock"])["phase"] == "final"
    indicators, periods = _obj(payload["indicators"]), _obj(payload["periods"])
    for team in TEAMS:
        quarters = periods[team]
        assert isinstance(quarters, list)
        assert len(quarters) >= court.REGULATION_PERIODS
        assert sum(q for q in quarters if isinstance(q, int)) == _obj(indicators[team])["points"]
    assert "goals" not in _obj(indicators["BOS"])


def test_the_home_team_comes_first_whoever_wins_the_jump_ball() -> None:
    """El primero en aparecer es quien gana el salto inicial, no el local."""
    first_to_appear = EVENTS[0].team
    replay = BasketballReplay(EVENTS, TEAMS)
    replay.advance_to(60)

    assert take_snapshot(replay).to_json()["teams"] == list(TEAMS)
    assert first_to_appear in TEAMS


def test_the_football_snapshot_gains_only_its_sport() -> None:
    replay = MatchReplay(simulate_match(65, MatchConfig("demo-65", "RMA", "BAR")))
    replay.advance_to(600)

    payload = take_snapshot(replay).to_json()

    assert payload["sport"] == "football"
    assert "periods" not in payload
    assert "game_clock_s" not in _obj(payload["clock"])
