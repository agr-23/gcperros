"""De dónde sale un número del marcador, con la huella verificada (#34)."""

from __future__ import annotations

import pytest

from gcperros.core.contracts import MatchEvent
from gcperros.demo.replay import MatchReplay
from gcperros.demo.trace import trace_indicator
from gcperros.engine.state import WHOLE_MATCH
from gcperros.generators.match import MatchConfig, simulate_match

CONFIG = MatchConfig(match_id="match-0034", home_team="RMA", away_team="BAR")


@pytest.fixture(scope="module")
def match() -> list[MatchEvent]:
    return simulate_match(65, CONFIG)


def _replay_at(match: list[MatchEvent], minutes: float) -> MatchReplay:
    replay = MatchReplay(match)
    replay.advance_to(minutes * 60)
    return replay


def test_the_goals_of_a_team_are_its_goal_events(match: list[MatchEvent]) -> None:
    trace = trace_indicator(_replay_at(match, 200), "goals", "RMA")
    goals = [e for e in match if e.event_type == "goal" and e.team == "RMA"]

    assert trace.verified
    assert trace.explanation.value == len(goals) == len(trace.events)
    assert [e.event_id for e in trace.events] == [e.event_id for e in goals]
    assert all(e.event_type == "goal" and 0 <= e.minute <= 100 for e in trace.events)


def test_mid_match_it_traces_only_what_the_engine_applied(match: list[MatchEvent]) -> None:
    """Con eventos retenidos por la marca de agua, la huella sigue cuadrando."""
    replay = _replay_at(match, 30)
    trace = trace_indicator(replay, "passes", "BAR")

    assert replay.engine.pending > 0
    assert trace.verified
    assert len(trace.events) == trace.explanation.value > 0


def test_a_count_the_engine_never_touched_is_empty_and_verified(match: list[MatchEvent]) -> None:
    trace = trace_indicator(_replay_at(match, 5), "red_cards", "RMA")

    assert (trace.explanation.value, trace.events, trace.verified) == (0.0, (), True)


def test_the_payload_is_the_hu18_explanation_plus_the_events(match: list[MatchEvent]) -> None:
    trace = trace_indicator(_replay_at(match, 200), "event_count", WHOLE_MATCH)
    payload = trace.to_json()

    assert payload["verified"] is True
    assert payload["value"] == len(match)
    assert {"indicator", "scope", "contract_version", "model_versions", "lineage"} <= set(payload)
    assert isinstance(payload["events"], list) and len(payload["events"]) == len(match)


def test_unknown_indicators_and_wrong_scopes_are_refused(match: list[MatchEvent]) -> None:
    replay = _replay_at(match, 10)

    with pytest.raises(AttributeError):
        trace_indicator(replay, "corners", "RMA")
    with pytest.raises(KeyError):
        trace_indicator(replay, "goals", WHOLE_MATCH)
