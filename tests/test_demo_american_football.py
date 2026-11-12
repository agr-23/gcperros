"""El fútbol americano en la demo: el tercer deporte también se ve en vivo (sección 22).

No tiene cuotas, así que la página esconde el mercado y las señales en vez de
enseñarlos vacíos; lo demás —marcador por cuartos, posesión, lo esperado,
estadísticas y trazabilidad— es lo mismo que en los otros dos deportes.
"""

from __future__ import annotations

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gcperros.demo import cli
from gcperros.demo.replay import AmericanFootballReplay
from gcperros.demo.server import LiveSource, create_app
from gcperros.generators.american_football import (
    AmericanFootballConfig,
    simulate_american_football,
)

EVENTS = simulate_american_football(65, AmericanFootballConfig("demo-nfl-65", "KC", "BUF"))


def _client() -> TestClient:
    """El primer vistazo arranca el partido; el segundo llega cuando ya terminó."""
    ticks = iter([0.0])
    source = LiveSource(
        AmericanFootballReplay(EVENTS, ("KC", "BUF")), clock=lambda: next(ticks, 10_000.0)
    )
    return TestClient(create_app(source))


def test_the_final_state_has_quarters_and_a_score_that_adds_up() -> None:
    client = _client()
    client.get("/api/matches/demo-nfl-65/state")
    state = client.get("/api/matches/demo-nfl-65/state").json()

    assert state["sport"] == "american_football" and state["clock"]["phase"] == "final"
    assert "market" not in state
    for team in ("KC", "BUF"):
        assert sum(state["periods"][team]) == state["indicators"][team]["points"]
    assert state["clock"]["minute"] == 60


def test_a_score_is_traceable_to_its_touchdowns_and_kicks() -> None:
    client = _client()
    client.get("/api/matches/demo-nfl-65/state")
    client.get("/api/matches/demo-nfl-65/state")

    trace = client.get("/api/matches/demo-nfl-65/trace/points/BUF").json()

    assert trace["verified"]
    assert sum(e["contribution"] for e in trace["events"]) == trace["value"]
    assert {e["event_type"] for e in trace["events"]} <= {
        "touchdown",
        "conversion",
        "field_goal",
        "safety",
    }


def test_by_default_the_demo_serves_the_three_sports(monkeypatch: pytest.MonkeyPatch) -> None:
    served: list[str] = []

    def fake_run(app: FastAPI, **_: object) -> None:
        served.extend(entry["sport"] for entry in TestClient(app).get("/api/sports").json())

    monkeypatch.setattr(uvicorn, "run", fake_run)
    cli.main([])

    assert served == ["football", "basketball", "american_football"]


def test_the_page_knows_the_third_sport_and_hides_what_it_does_not_have() -> None:
    client = _client()
    sport = client.get("/sport.js").text

    assert "SPORTS.american_football" in sport and "market: false" in sport
    assert "config.market === false" in client.get("/app.js").text
    assert 'body[data-sport="american_football"] .board' in client.get("/app.css").text
