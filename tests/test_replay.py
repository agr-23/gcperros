"""La repetición de un partido para la demostración en vivo (#30)."""

from __future__ import annotations

import pytest

from gcperros.core.contracts import MatchEvent
from gcperros.core.stats import summarize_events
from gcperros.demo.replay import MatchReplay, ReplayClock
from gcperros.generators.match import MatchConfig, simulate_match

CONFIG = MatchConfig(match_id="match-0030", home_team="RMA", away_team="BAR")
SEED = 20260826


@pytest.fixture(scope="module")
def match() -> list[MatchEvent]:
    return simulate_match(SEED, CONFIG)


def test_before_kickoff_nothing_has_happened(match: list[MatchEvent]) -> None:
    replay = MatchReplay(match)

    assert replay.clock() == ReplayClock(elapsed_s=0.0, period=1, minute=0, phase="previa")
    assert replay.engine.state.summary().event_count == 0
    assert replay.match_id == "match-0030"


def test_the_engine_only_counts_what_the_watermark_released(match: list[MatchEvent]) -> None:
    replay = MatchReplay(match)
    delivered = replay.advance_to(10 * 60)

    assert delivered == replay.engine.state.summary().event_count + replay.engine.pending
    assert replay.engine.pending > 0


def test_half_time_is_reported_as_such(match: list[MatchEvent]) -> None:
    replay = MatchReplay(match)
    replay.advance_to(52 * 60)

    assert (replay.clock().phase, replay.clock().minute) == ("descanso", 45)


def test_the_second_half_counts_from_minute_45(match: list[MatchEvent]) -> None:
    replay = MatchReplay(match)
    replay.advance_to(75 * 60)
    clock = replay.clock()

    assert (clock.period, clock.phase) == (2, "parte-2")
    assert 45 < clock.minute < 90


def test_the_final_whistle_matches_the_batch_result(match: list[MatchEvent]) -> None:
    replay = MatchReplay(match)
    replay.advance_to(10 * 3600)
    summary = replay.engine.state.summary()

    assert replay.finished
    assert replay.clock().phase == "final"
    assert replay.elapsed_s == replay.duration_s
    assert (summary.event_count, replay.engine.pending) == (len(match), 0)
    assert summary.goals == summarize_events(match).goals


def test_the_clock_never_goes_back(match: list[MatchEvent]) -> None:
    replay = MatchReplay(match)
    replay.advance_to(20 * 60)
    before = (replay.clock(), replay.engine.result())

    assert replay.advance_to(5 * 60) == 0
    assert (replay.clock(), replay.engine.result()) == before


def test_the_same_second_gives_the_same_state(match: list[MatchEvent]) -> None:
    """Llegar al minuto 30 de un salto o a pasos cortos no cambia nada."""
    jump, steps = MatchReplay(match), MatchReplay(match)
    jump.advance_to(30 * 60)
    for second in range(0, 30 * 60 + 1, 7):
        steps.advance_to(second)
    steps.advance_to(30 * 60)

    assert jump.clock() == steps.clock()
    assert jump.engine.result() == steps.engine.result()


def test_an_empty_match_is_rejected() -> None:
    with pytest.raises(ValueError, match="no hay eventos"):
        MatchReplay([])
