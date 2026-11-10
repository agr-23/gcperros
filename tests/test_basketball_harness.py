"""El baloncesto, medido con la misma vara que el fútbol (#91)."""

from __future__ import annotations

import pytest

from gcperros.engine.sport_harness import BASKETBALL, FOOTBALL, SPORTS, run_sport_harness


@pytest.mark.parametrize("seed", range(4))
def test_basketball_holds_every_committed_scenario_with_its_margin(seed: int) -> None:
    results = run_sport_harness(BASKETBALL, BASKETBALL.simulate(seed), seed)

    assert all(result.passed for result in results), [
        r.scenario.name for r in results if not r.passed
    ]


def test_each_sport_declares_its_indicators_and_the_margin_its_data_chose() -> None:
    assert SPORTS == {"football": FOOTBALL, "basketball": BASKETBALL}
    assert (FOOTBALL.allowed_lateness_s, BASKETBALL.allowed_lateness_s) == (10.0, 15.0)
    assert (BASKETBALL.exact_label, BASKETBALL.estimate_label) == ("points", "expected_points")


def test_a_margin_too_short_for_basketball_drops_events_and_is_caught() -> None:
    """Con 2 s, el evento que adelanta a otro ya le saca más del margen."""
    failed = [
        result
        for seed in range(6)
        for result in run_sport_harness(
            BASKETBALL, BASKETBALL.simulate(seed), seed, allowed_lateness_s=2.0
        )
        if not result.passed
    ]

    assert failed
    assert all(r.run.plane.dropped_late > 0 for r in failed)


def test_basketball_waits_longer_than_football_for_its_watermark() -> None:
    """Llegan menos eventos por minuto, así que la marca de agua avanza menos a menudo."""

    def p95(sport_name: str) -> float:
        sport = SPORTS[sport_name]
        results = run_sport_harness(sport, sport.simulate(65), 65)
        return next(r for r in results if r.scenario.name == "desorden-medio").run.latency.p95_s

    assert p95("basketball") > p95("football")
