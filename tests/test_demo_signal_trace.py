"""De dónde sale una señal del feed, verificada en el panel (historia #25)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gcperros.core import odds
from gcperros.core.contracts import MatchEvent
from gcperros.demo import signal_trace
from gcperros.demo.market import MarketTape
from gcperros.demo.replay import MatchReplay
from gcperros.demo.server import LiveSource, create_app
from gcperros.demo.signal_trace import trace_signal
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.odds import simulate_odds

CONFIG = MatchConfig(match_id="match-0025", home_team="RMA", away_team="BAR")


@pytest.fixture(scope="module")
def match() -> list[MatchEvent]:
    return simulate_match(65, CONFIG)


def _tape_at_full_time(match: list[MatchEvent]) -> tuple[MarketTape, MatchReplay]:
    replay = MatchReplay(match)
    tape = MarketTape(match, simulate_odds(65, match))
    replay.advance_to(10 * 3600)
    tape.advance_to(replay.now)
    return tape, replay


def test_every_signal_of_the_match_is_verified(match: list[MatchEvent]) -> None:
    tape, replay = _tape_at_full_time(match)

    traces = [trace_signal(tape, i, replay.minute_at) for i in range(len(tape.signals))]

    assert traces
    for trace in traces:
        payload = trace.to_json()
        assert payload["verified"] is True
        assert payload["model_version"] == odds.MODEL_VERSION
        # Los eventos que se enseñan más la cuota son exactamente los plegados.
        assert trace.signal.lineage.event_count == len(trace.events) + 1


def test_a_wrong_reconstruction_is_not_passed_off_as_verified(
    match: list[MatchEvent], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si se olvidan los goles al reconstruir, la huella deja de cuadrar y se dice."""
    tape, replay = _tape_at_full_time(match)
    monkeypatch.setattr(signal_trace, "_fixes_the_state", lambda _event: False)

    assert not any(
        trace_signal(tape, i, replay.minute_at).verified for i in range(len(tape.signals))
    )


def test_the_feed_links_each_signal_to_its_provenance(match: list[MatchEvent]) -> None:
    now = [0.0]
    tape = MarketTape(match, simulate_odds(65, match))
    source = LiveSource(MatchReplay(match), speed=60.0, clock=lambda: now[0], market=tape)
    client = TestClient(create_app(source))
    client.get("/api/matches/match-0025/state")
    now[0] += 200.0
    feed = client.get("/api/matches/match-0025/state").json()["market"]

    newest = feed["signals"][0]
    assert newest["index"] == feed["total_signals"] - 1
    trace = client.get(f"/api/matches/match-0025/signals/{newest['index']}/trace").json()
    assert trace["verified"] is True
    assert (trace["operator"], trace["outcome"]) == (newest["operator"], newest["outcome"])
    assert client.get("/api/matches/match-0025/signals/9999/trace").status_code == 404
    assert client.get("/api/matches/otro/signals/0/trace").status_code == 404
    bare = TestClient(create_app(LiveSource(MatchReplay(match), clock=lambda: 0.0)))
    assert bare.get("/api/matches/match-0025/signals/0/trace").status_code == 404
    assert "dataset.signal" in bare.get("/market.js").text
