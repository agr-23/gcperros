"""El resumen batch del baloncesto: la referencia contra la que se medirá el motor (#88)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gcperros.core.basketball_stats import summarize_basketball
from gcperros.core.contracts import BasketballEventType, JsonValue, MatchEvent

T0 = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)


def _event(n: int, team: str, event_type: BasketballEventType, **attrs: JsonValue) -> MatchEvent:
    return MatchEvent(
        event_id=f"ev-{n}",
        event_time=T0 + timedelta(seconds=n),
        match_id="bkb-0001",
        team=team,
        event_type=event_type,
        attrs={**attrs, "period": 1},
    )


EVENTS = [
    _event(1, "BOS", "possession_change", from_team="LAL", to_team="BOS", reason="jump_ball"),
    _event(2, "BOS", "shot", x=21.0, y=7.5, points_value=3, made=True, make_probability=0.4),
    _event(3, "LAL", "possession_change", from_team="BOS", to_team="LAL", reason="made_shot"),
    _event(4, "LAL", "shot", x=26.0, y=7.5, points_value=2, made=False, make_probability=0.6),
    _event(5, "LAL", "rebound", kind="offensive"),
    _event(6, "BOS", "foul", against_team="LAL", free_throws=2),
    _event(7, "LAL", "free_throw", made=True, make_probability=0.76),
    _event(8, "LAL", "free_throw", made=False, make_probability=0.76),
    _event(9, "BOS", "rebound", kind="defensive"),
    _event(
        10, "BOS", "possession_change", from_team="LAL", to_team="BOS", reason="defensive_rebound"
    ),
    _event(11, "BOS", "turnover", kind="steal"),
    _event(12, "LAL", "timeout"),
]


def test_points_come_from_made_shots_and_free_throws() -> None:
    summary = summarize_basketball(EVENTS)

    assert summary.points == {"BOS": 3, "LAL": 1}
    assert summary.event_count == len(EVENTS)


def test_expected_points_weigh_each_attempt_by_its_value() -> None:
    summary = summarize_basketball(EVENTS)

    # BOS: un triple de 0,40. LAL: un tiro de dos de 0,60 y dos libres de 0,76.
    assert summary.expected_points["BOS"] == pytest.approx(1.2)
    assert summary.expected_points["LAL"] == pytest.approx(2.72)


def test_every_counter_is_split_by_team() -> None:
    summary = summarize_basketball(EVENTS)

    assert (summary.three_attempted, summary.three_made) == ({"BOS": 1, "LAL": 0},) * 2
    assert summary.two_attempted == {"BOS": 0, "LAL": 1}
    assert summary.two_made == {"BOS": 0, "LAL": 0}
    assert summary.free_throws_attempted == {"BOS": 0, "LAL": 2}
    assert summary.free_throws_made == {"BOS": 0, "LAL": 1}
    assert summary.offensive_rebounds == {"BOS": 0, "LAL": 1}
    assert summary.defensive_rebounds == {"BOS": 1, "LAL": 0}
    assert summary.turnovers == {"BOS": 1, "LAL": 0}
    assert summary.fouls == {"BOS": 1, "LAL": 0}
    assert summary.timeouts == {"BOS": 0, "LAL": 1}
    assert summary.possessions == {"BOS": 2, "LAL": 1}


def test_an_empty_stream_summarizes_to_nothing() -> None:
    summary = summarize_basketball([])

    assert summary.event_count == 0
    assert summary.points == {}
