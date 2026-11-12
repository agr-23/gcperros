"""Quien abre la página tarde ve el partido entero, no desde que llegó (#96).

Las gráficas de la página se dibujaban con lo que llegaba por el canal en vivo,
así que entrar en el minuto 60 dejaba en blanco sesenta minutos. El servidor
guarda ahora un punto por minuto de partido, también cuando el reloj salta.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from gcperros.demo.market import MarketTape
from gcperros.demo.replay import MatchReplay
from gcperros.demo.server import HISTORY_STEP_S, LiveSource, create_app
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.odds import simulate_odds

CONFIG = MatchConfig(match_id="match-0096", home_team="RMA", away_team="BAR")
EVENTS = simulate_match(65, CONFIG)


class FakeClock:
    """Reloj de pared que sólo avanza cuando la prueba lo dice."""

    def __init__(self) -> None:
        """Arranca en un instante arbitrario: sólo importan las diferencias."""
        self.now = 1000.0

    def __call__(self) -> float:
        """El instante actual, en segundos."""
        return self.now


def _late_client(minutes: float, market: bool = False) -> tuple[TestClient, LiveSource]:
    clock = FakeClock()
    tape = MarketTape(EVENTS, simulate_odds(65, EVENTS)) if market else None
    source = LiveSource(MatchReplay(EVENTS), speed=60.0, clock=clock, market=tape)
    source.current()
    clock.now += minutes  # a velocidad 60, un segundo real es un minuto de partido
    return TestClient(create_app(source)), source


def test_joining_late_still_gets_every_minute_already_played() -> None:
    client, _ = _late_client(30.0)
    state = client.get("/api/matches/match-0096/state").json()

    points = client.get("/api/matches/match-0096/history").json()

    minutes = [point["minute"] for point in points]
    assert len(points) == 30
    assert minutes == sorted(minutes)
    assert minutes[0] <= 1 and minutes[-1] == state["clock"]["minute"]
    assert set(points[-1]["indicators"]) == {"RMA", "BAR"}


def test_the_history_matches_what_the_live_state_said_at_that_minute() -> None:
    client, _ = _late_client(30.0)
    state = client.get("/api/matches/match-0096/state").json()

    (last,) = client.get("/api/matches/match-0096/history").json()[-1:]

    assert last["indicators"] == state["indicators"]


def test_the_history_stops_at_the_final_whistle() -> None:
    client, source = _late_client(600.0)
    client.get("/api/matches/match-0096/state")
    length = len(source.history())
    client.get("/api/matches/match-0096/state")

    assert length == int(MatchReplay(EVENTS).duration_s // HISTORY_STEP_S)
    assert len(source.history()) == length


def test_with_a_market_each_point_carries_the_model_and_the_operators() -> None:
    client, _ = _late_client(20.0, market=True)
    client.get("/api/matches/match-0096/state")

    point = client.get("/api/matches/match-0096/history").json()[-1]

    assert set(point["model"]) == {"home", "draw", "away"}
    assert point["operators"] and all(set(book) >= {"home"} for book in point["operators"].values())


def test_the_page_seeds_its_charts_from_the_history() -> None:
    client, _ = _late_client(0.0)

    assert "/history" in client.get("/app.js").text
    for script in ("/charts.js", "/market.js"):
        assert "gcperros:history" in client.get(script).text
