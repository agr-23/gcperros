"""Los diálogos de trazabilidad dicen cuánto aportó cada evento (#99).

Cada evento se aplica solo a un estado vacío y se lee el indicador: lo que
mueve es su aportación. Sumadas dan el número, en los dos deportes, y eso es lo
que el diálogo enseña junto a la huella.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from gcperros.demo.market import MarketTape
from gcperros.demo.replay import BasketballReplay, MatchReplay, Replay
from gcperros.demo.signal_trace import trace_signal
from gcperros.demo.trace import trace_indicator
from gcperros.generators.basketball import BasketballConfig, simulate_basketball
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.odds import simulate_odds


def _finished(replay: Replay[object]) -> Replay[object]:
    replay.advance_to(10 * 3600)
    return replay


BASKETBALL = _finished(
    BasketballReplay(simulate_basketball(65, BasketballConfig("b", "BOS", "LAL")))
)
FOOTBALL = _finished(
    MatchReplay(simulate_match(65, MatchConfig(match_id="f", home_team="RMA", away_team="BAR")))
)


@pytest.mark.parametrize(
    ("replay", "indicator"),
    [
        (BASKETBALL, "points"),
        (BASKETBALL, "expected_points"),
        (BASKETBALL, "turnovers"),
        (FOOTBALL, "goals"),
        (FOOTBALL, "total_xg"),
        (FOOTBALL, "passes"),
    ],
)
def test_what_each_event_contributes_adds_up_to_the_number(
    replay: Replay[object], indicator: str
) -> None:
    team = replay.engine.state.teams[0]
    trace = trace_indicator(replay, indicator, team)

    contributions = [event.contribution for event in trace.events]
    assert trace.verified
    assert all(value is not None and value > 0 for value in contributions)
    assert math.isclose(sum(v for v in contributions if v is not None), trace.explanation.value)


def test_a_basket_is_worth_its_points_and_a_free_throw_one() -> None:
    trace = trace_indicator(BASKETBALL, "points", "BOS")
    by_type = {(e.event_type, e.contribution) for e in trace.events}

    assert by_type <= {("shot", 2.0), ("shot", 3.0), ("free_throw", 1.0)}
    assert ("shot", 3.0) in by_type


def test_the_payload_carries_the_contribution() -> None:
    events = trace_indicator(FOOTBALL, "total_xg", "RMA").to_json()["events"]

    assert isinstance(events, list) and isinstance(events[0], dict)
    contribution = events[0]["contribution"]
    assert isinstance(contribution, float) and 0.0 < contribution < 1.0


def test_the_signal_dialog_gets_both_probabilities() -> None:
    """Para dibujar el modelo frente al precio del operador (#99)."""
    match = simulate_match(65, MatchConfig(match_id="s", home_team="RMA", away_team="BAR"))
    replay = _finished(MatchReplay(match))
    tape = MarketTape(match, simulate_odds(65, match))
    tape.advance_to(replay.now)

    payload = trace_signal(tape, 0, replay.minute_at).to_json()

    assert payload["model_probability"] == tape.signals[0].model_probability
    assert payload["market_probability"] == tape.signals[0].market_probability


def test_the_dialog_shows_the_proof_the_facts_and_each_contribution() -> None:
    """El diálogo pinta lo que la traza trae: prueba, ficha, aportaciones y versus."""
    script = (
        Path(__file__).resolve().parent.parent / "src/gcperros/demo/static/trace.js"
    ).read_text(encoding="utf-8")

    for needle in ("function verdict", "function facts", "function timeline", "function versus"):
        assert needle in script
    assert "event.contribution" in script and "shortDigest" in script
    assert "trace.model_probability" in script and "GCP.config.threshold" in script
