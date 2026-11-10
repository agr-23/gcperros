"""El harness de #17 para cualquier deporte, y lo que se recalibró con él (#91)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from gcperros.engine.harness import run_harness
from gcperros.engine.sport_harness import FOOTBALL, measure, run_sport_harness


@pytest.mark.parametrize("seed", [1, 65])
def test_with_the_football_profile_it_measures_exactly_what_the_old_harness_did(seed: int) -> None:
    """Es lo que permite poner los dos deportes lado a lado con la misma vara."""
    events = FOOTBALL.simulate(seed)

    old = run_harness(events, seed).results
    new = run_sport_harness(FOOTBALL, events, seed)

    for before, after in zip(old, new, strict=True):
        assert after.divergence.possession_share == before.divergence.possession_share
        assert after.divergence.estimate == before.divergence.total_xg
        assert after.divergence.exact == before.divergence.goals
        assert after.divergence.events == before.divergence.events
        assert after.run.plane.dropped_late == before.dropped_late
        assert after.passed == before.passed


def test_the_divergence_needs_the_exact_indicator_and_the_events_to_match() -> None:
    events = FOOTBALL.simulate(2)
    reference = FOOTBALL.batch(events)

    assert measure(reference, reference).passes()
    missing_goal = replace(reference, exact=reference.exact - 1)
    assert not measure(reference, missing_goal).passes()
    lost_event = replace(reference, event_count=reference.event_count - 1)
    assert not measure(reference, lost_event).passes()
    counted_late = replace(reference, event_count=reference.event_count - 1, dropped_late=1)
    assert measure(reference, counted_late).passes(), "un tardío contado no es una pérdida"
