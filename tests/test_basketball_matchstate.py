"""La lectura del partido de baloncesto que comparten generador y señal (#90)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gcperros.core.basketball_matchstate import (
    RUN_POINTS,
    BasketballStateTracker,
    points_scored,
)
from gcperros.core.contracts import BasketballEventType, JsonValue, MatchEvent

T0 = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)


def _event(n: int, team: str, event_type: BasketballEventType, **attrs: JsonValue) -> MatchEvent:
    return MatchEvent(
        event_id=f"ev-{n}",
        event_time=T0 + timedelta(seconds=n),
        match_id="bkb-1",
        team=team,
        event_type=event_type,
        attrs={"period": 2, "clock_s": 500.0 - n, **attrs},
    )


def _three(n: int, team: str, *, made: bool = True) -> MatchEvent:
    return _event(n, team, "shot", points_value=3, made=made, make_probability=0.4)


def test_points_come_only_from_made_shots_and_free_throws() -> None:
    assert points_scored(_three(1, "BOS")) == 3
    assert points_scored(_three(2, "BOS", made=False)) == 0
    assert points_scored(_event(3, "BOS", "free_throw", made=True, make_probability=0.76)) == 1
    assert points_scored(_event(4, "BOS", "rebound", kind="defensive")) == 0


def test_the_tracker_reads_period_clock_and_score_from_the_stream() -> None:
    tracker = BasketballStateTracker("BOS", "LAL")
    for event in (_three(1, "BOS"), _three(2, "LAL"), _three(3, "BOS")):
        tracker.apply(event)

    state = tracker.state()
    assert (state.period, state.clock_s) == (2, 497.0)
    assert (state.points_home, state.points_away) == (6, 3)


def test_a_run_is_announced_once_when_it_crosses_the_threshold() -> None:
    tracker = BasketballStateTracker("BOS", "LAL")
    triggers = [tracker.apply(_three(n, "BOS")) for n in range(1, 6)]

    assert RUN_POINTS == 8
    assert triggers == [None, None, "run", None, None]  # 3, 6, 9: cruza en el tercero


def test_the_rival_scoring_resets_the_run_and_a_timeout_moves_the_market() -> None:
    tracker = BasketballStateTracker("BOS", "LAL")
    tracker.apply(_three(1, "BOS"))
    tracker.apply(_three(2, "BOS"))
    tracker.apply(_three(3, "LAL"))

    assert tracker.apply(_three(4, "BOS")) is None  # vuelve a empezar desde 3
    assert tracker.apply(_event(5, "LAL", "timeout")) == "timeout"
