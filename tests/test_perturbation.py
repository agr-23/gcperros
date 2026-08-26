"""El inyector de duplicados que somete al motor a la adversidad del broker."""

from __future__ import annotations

import pytest

from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.perturbation import inject_duplicates

CONFIG = MatchConfig(match_id="match-0011", home_team="RMA", away_team="BAR")
EVENTS = simulate_match(20260826, CONFIG)


def test_injection_is_deterministic() -> None:
    first, report_a = inject_duplicates(EVENTS, seed=7)
    second, report_b = inject_duplicates(EVENTS, seed=7)

    assert [e.event_id for e in first] == [e.event_id for e in second]
    assert report_a == report_b


def test_different_seeds_degrade_the_stream_differently() -> None:
    first, _ = inject_duplicates(EVENTS, seed=1)
    second, _ = inject_duplicates(EVENTS, seed=2)

    assert [e.event_id for e in first] != [e.event_id for e in second]


def test_the_report_matches_what_was_delivered() -> None:
    delivered, report = inject_duplicates(EVENTS, seed=3, rate=0.1)

    assert report.original_count == len(EVENTS)
    assert report.delivered_count == len(delivered)
    assert report.delivered_count == report.original_count + report.injected


def test_duplicates_are_the_very_same_event() -> None:
    """Una reentrega no es un evento parecido: es el mismo `event_id`."""
    delivered, _ = inject_duplicates(EVENTS, seed=4, rate=0.2)
    original_ids = {event.event_id for event in EVENTS}

    assert {event.event_id for event in delivered} == original_ids


def test_every_original_is_still_delivered_once_and_in_order() -> None:
    delivered, _ = inject_duplicates(EVENTS, seed=8, rate=0.25)

    seen: list[str] = []
    already = set()
    for event in delivered:
        if event.event_id not in already:
            already.add(event.event_id)
            seen.append(event.event_id)

    assert seen == [event.event_id for event in EVENTS]


def test_a_rate_of_zero_leaves_the_stream_untouched() -> None:
    delivered, report = inject_duplicates(EVENTS, seed=9, rate=0.0)

    assert report.injected == 0
    assert delivered == EVENTS


def test_the_injected_share_is_close_to_the_requested_rate() -> None:
    _, report = inject_duplicates(EVENTS, seed=11, rate=0.1)
    observed = report.injected / report.original_count

    assert 0.07 <= observed <= 0.13


def test_invalid_parameters_are_rejected() -> None:
    with pytest.raises(ValueError, match="entre 0 y 1"):
        inject_duplicates(EVENTS, seed=1, rate=1.5)

    with pytest.raises(ValueError, match="entre 0 y 1"):
        inject_duplicates(EVENTS, seed=1, rate=-0.1)

    with pytest.raises(ValueError, match="al menos una posición"):
        inject_duplicates(EVENTS, seed=1, max_gap=0)
