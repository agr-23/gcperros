"""El canal en vivo de la demostración, por Server-Sent Events (#31)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from fastapi.testclient import TestClient

from gcperros.demo.replay import MatchReplay
from gcperros.demo.server import LiveSource, create_app
from gcperros.generators.match import MatchConfig, simulate_match

CONFIG = MatchConfig(match_id="match-0031", home_team="RMA", away_team="BAR")
EVENTS = simulate_match(20260826, CONFIG)


class FakeClock:
    """Reloj de pared que avanza sólo cuando el canal «duerme»."""

    def __init__(self) -> None:
        """Arranca en un instante arbitrario: sólo importan las diferencias."""
        self.now = 1000.0
        self.naps = 0

    def __call__(self) -> float:
        """El instante actual, en segundos."""
        return self.now

    async def sleep(self, seconds: float) -> None:
        """En vez de esperar, adelanta el reloj lo que se iba a esperar."""
        self.now += seconds
        self.naps += 1


@dataclass(frozen=True)
class Message:
    """Lo que las pruebas miran de cada mensaje del canal."""

    keys: frozenset[str]
    phase: str
    event_count: int


def _messages(poll_s: float, speed: float = 60.0) -> tuple[list[Message], FakeClock]:
    clock = FakeClock()
    source = LiveSource(MatchReplay(EVENTS), speed=speed, clock=clock)
    client = TestClient(create_app(source, poll_s=poll_s, sleep=clock.sleep))
    messages = []
    with client.stream("GET", "/api/matches/match-0031/stream") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
                messages.append(
                    Message(frozenset(data), str(data["clock"]["phase"]), int(data["event_count"]))
                )
    return messages, clock


def test_the_stream_follows_the_match_to_the_final_whistle() -> None:
    """A velocidad 60 y un envío cada diez segundos reales: diez minutos por mensaje."""
    messages, clock = _messages(poll_s=10.0)
    phases = [message.phase for message in messages]

    assert phases[0] == "previa"
    assert phases[-1] == "final"
    assert phases.count("final") == 1
    assert {"parte-1", "descanso", "parte-2"} <= set(phases)
    assert clock.naps == len(messages) - 1


def test_every_message_is_the_state_document() -> None:
    messages, _ = _messages(poll_s=20.0)

    for message in messages:
        assert {"match_id", "indicators", "clock", "possession", "pending"} <= message.keys
    counts = [message.event_count for message in messages]
    assert counts == sorted(counts)
    assert counts[-1] == len(EVENTS)


def test_an_unknown_match_has_no_stream() -> None:
    source = LiveSource(MatchReplay(EVENTS), clock=FakeClock())
    response = TestClient(create_app(source)).get("/api/matches/otro/stream")

    assert response.status_code == 404


def test_the_page_is_served_and_only_knows_the_api() -> None:
    client = TestClient(create_app(LiveSource(MatchReplay(EVENTS), clock=FakeClock())))
    page = client.get("/")
    script = client.get("/app.js")

    assert page.status_code == 200
    assert "<title>GCPerros · En vivo</title>" in page.text
    assert "EventSource" in script.text
    assert 'src="charts.js"' in page.text and 'id="xg-chart"' in page.text
    assert client.get("/charts.js").status_code == 200
    # Sin CDN ni fuentes externas: la demo tiene que funcionar sin internet.
    assert "http" not in page.text + client.get("/app.css").text
    assert client.get("/api/matches").json() == ["match-0031"]
