"""La demostración con baloncesto: el mismo servidor, otro reloj (#92)."""

from __future__ import annotations

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gcperros.core.contracts import JsonValue
from gcperros.demo import cli
from gcperros.demo.market import MarketTape
from gcperros.demo.replay import BasketballReplay, MatchReplay
from gcperros.demo.server import LiveSource, create_app
from gcperros.engine.basketball_market import BASKETBALL_THRESHOLD, BasketballMarketReader
from gcperros.generators.basketball import BasketballConfig, simulate_basketball
from gcperros.generators.basketball_odds import simulate_basketball_odds
from gcperros.generators.match import MatchConfig, simulate_match

TEAMS = ("BOS", "LAL")
EVENTS = simulate_basketball(65, BasketballConfig("demo-bkb-65", *TEAMS))


def _obj(value: JsonValue) -> dict[str, JsonValue]:
    assert isinstance(value, dict)
    return value


def _tape() -> MarketTape:
    odds = simulate_basketball_odds(65, EVENTS, TEAMS)
    return MarketTape(EVENTS, odds, BASKETBALL_THRESHOLD, BasketballMarketReader(*TEAMS))


def test_one_server_serves_both_sports() -> None:
    football = LiveSource(MatchReplay(simulate_match(65, MatchConfig("demo-65", "RMA", "BAR"))))
    now = [0.0]
    basketball = LiveSource(BasketballReplay(EVENTS), clock=lambda: now[0], market=_tape())
    client = TestClient(create_app([football, basketball]))

    assert client.get("/api/matches").json() == ["demo-65", "demo-bkb-65"]
    assert client.get("/api/sports").json() == [
        {"match_id": "demo-65", "sport": "football"},
        {"match_id": "demo-bkb-65", "sport": "basketball"},
    ]
    state = client.get("/api/matches/demo-bkb-65/state").json()
    assert state["sport"] == "basketball"
    assert state["market"]["model"] == {"home": 0.5, "away": 0.5}
    now[0] = 60.0  # a velocidad 30, media hora de pared: bien entrado el segundo cuarto
    assert client.get("/api/matches/demo-bkb-65/state").json()["clock"]["period"] >= 2
    assert client.get("/api/matches/demo-bkb-65/trace/points/BOS").json()["verified"]
    assert client.get("/api/matches/otro/state").status_code == 404


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--seed", "7"], ["demo-7", "demo-bkb-65", "demo-nfl-65"]),
        (["--sport", "ambos", "--seed", "7"], ["demo-7", "demo-bkb-65"]),
        (["--sport", "american_football", "--seed", "3"], ["demo-nfl-3"]),
        (["--sport", "basketball", "--seed", "3"], ["demo-bkb-3"]),
        (["--sport", "football", "--seed", "7"], ["demo-7"]),
    ],
)
def test_the_cli_serves_the_sports_it_is_asked_for(
    argv: list[str], expected: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    served: dict[str, object] = {}

    def fake_run(app: FastAPI, **_options: object) -> None:
        served["app"] = app

    monkeypatch.setattr(uvicorn, "run", fake_run)
    assert cli.main(argv) == 0
    app = served["app"]
    assert isinstance(app, FastAPI)
    assert TestClient(app).get("/api/matches").json() == expected
