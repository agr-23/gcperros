"""El servidor local de la demostración y su línea de comandos (#30)."""

from __future__ import annotations

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gcperros.demo import cli
from gcperros.demo.replay import MatchReplay
from gcperros.demo.server import LiveSource, create_app
from gcperros.generators.match import MatchConfig, simulate_match

CONFIG = MatchConfig(match_id="match-0030", home_team="RMA", away_team="BAR")
EVENTS = simulate_match(20260826, CONFIG)


class FakeClock:
    """Reloj de pared que sólo avanza cuando la prueba lo dice."""

    def __init__(self) -> None:
        """Arranca en un instante arbitrario: sólo importan las diferencias."""
        self.now = 1000.0

    def __call__(self) -> float:
        """El instante actual, en segundos."""
        return self.now


def _client(speed: float = 60.0) -> tuple[TestClient, FakeClock]:
    clock = FakeClock()
    source = LiveSource(MatchReplay(EVENTS), speed=speed, clock=clock)
    return TestClient(create_app(source)), clock


def test_wall_time_becomes_match_time() -> None:
    """A velocidad 60, diez segundos reales son diez minutos de partido."""
    client, clock = _client(speed=60.0)

    assert client.get("/api/matches/match-0030/state").json()["clock"]["phase"] == "previa"
    clock.now += 10.0
    state = client.get("/api/matches/match-0030/state").json()

    assert state["clock"]["minute"] == 10
    assert state["event_count"] > 0
    assert state["teams"] == ["RMA", "BAR"]


def test_the_match_ends_and_stays_ended() -> None:
    client, clock = _client()
    client.get("/api/matches/match-0030/state")
    clock.now += 3600.0

    first = client.get("/api/matches/match-0030/state").json()
    clock.now += 60.0
    second = client.get("/api/matches/match-0030/state").json()

    assert first["clock"]["phase"] == "final"
    assert first == second


def test_the_match_list_and_an_unknown_match() -> None:
    client, _ = _client()

    assert client.get("/api/matches").json() == ["match-0030"]
    response = client.get("/api/matches/otro/state")
    assert response.status_code == 404
    assert "otro" in response.json()["detail"]


def test_the_match_starts_when_someone_looks() -> None:
    """Lanzar el servidor y abrir la página un minuto después no salta media parte."""
    client, clock = _client(speed=30.0)
    clock.now += 60.0

    assert client.get("/api/matches/match-0030/state").json()["clock"]["phase"] == "previa"


def test_speed_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positiva"):
        LiveSource(MatchReplay(EVENTS), speed=0.0)


def test_the_cli_serves_the_match_of_the_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    served: dict[str, object] = {}

    def fake_run(app: FastAPI, host: str, port: int, log_level: str) -> None:
        served.update(app=app, host=host, port=port, log_level=log_level)

    monkeypatch.setattr(uvicorn, "run", fake_run)

    assert cli.main(["--seed", "7", "--port", "8123", "--speed", "90"]) == 0
    assert (served["host"], served["port"]) == ("127.0.0.1", 8123)
    app = served["app"]
    assert isinstance(app, FastAPI)
    assert TestClient(app).get("/api/matches").json() == ["demo-7"]


def test_the_cli_rejects_a_stopped_clock(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--speed", "0"])

    assert exit_info.value.code == 2
    assert "positiva" in capsys.readouterr().err
