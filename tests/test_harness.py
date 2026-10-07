"""El harness que somete el motor a perturbaciones (#17)."""

from __future__ import annotations

import pytest

from gcperros.core.divergence import Thresholds
from gcperros.engine.harness import (
    DEFAULT_SCENARIOS,
    STRESS_SCENARIOS,
    Scenario,
    run_harness,
)
from gcperros.generators.match import MatchConfig, simulate_match

CONFIG = MatchConfig(match_id="match-0017", home_team="RMA", away_team="BAR")
EVENTS = simulate_match(20260826, CONFIG)


def test_the_committed_scenarios_all_pass() -> None:
    """Lo que el diseño se compromete a resistir, con su margen por defecto."""
    report = run_harness(EVENTS, seed=7)

    assert report.passed, [r.scenario.name for r in report.failures]
    assert [r.scenario.name for r in report.results] == [s.name for s in DEFAULT_SCENARIOS]


def test_duplicates_are_removed_and_nothing_is_lost() -> None:
    result = next(
        r for r in run_harness(EVENTS, seed=7).results if r.scenario.name == "duplicados-20"
    )

    assert result.duplicates_removed > 0
    assert result.delivered == len(EVENTS) + result.duplicates_removed
    assert result.divergence.events == 0


def test_late_events_are_counted_not_lost() -> None:
    """Con desorden realista la marca de agua descarta algo, y la cuenta cierra."""
    result = next(r for r in run_harness(EVENTS, seed=7).results if r.scenario.name == "hostil")

    assert result.dropped_late > 0
    assert result.divergence.events == 0
    assert result.timeliness < 1.0


def test_stress_finds_where_the_design_breaks() -> None:
    """Los escenarios de estrés existen para fallar en algún punto."""
    report = run_harness(EVENTS, seed=7, scenarios=STRESS_SCENARIOS)

    assert not report.passed
    worst = report.results[-1]
    assert worst.timeliness < 0.95
    assert "total_xg" in {b.indicator for b in worst.divergence.breaches()}


def test_a_wider_margin_rescues_a_failing_scenario() -> None:
    """La perilla de latencia contra completitud, vista desde el harness."""
    extreme = (STRESS_SCENARIOS[-1],)

    assert not run_harness(EVENTS, seed=7, scenarios=extreme).passed
    assert run_harness(EVENTS, seed=7, scenarios=extreme, allowed_lateness_s=200.0).passed


def test_the_report_is_deterministic() -> None:
    first = run_harness(EVENTS, seed=7)
    second = run_harness(EVENTS, seed=7)

    assert first == second


def test_a_different_seed_degrades_differently() -> None:
    first = run_harness(EVENTS, seed=7)
    second = run_harness(EVENTS, seed=8)

    assert [r.delivered for r in first.results] != [r.delivered for r in second.results]


def test_thresholds_can_be_overridden() -> None:
    strict = Thresholds(possession_share=0.0001)
    report = run_harness(EVENTS, seed=7, thresholds=strict)

    assert not report.passed
    assert any(r.scenario.name == "desorden-medio" for r in report.failures)


def test_a_custom_scenario_runs() -> None:
    only = (Scenario("mio", duplicate_rate=0.5),)
    report = run_harness(EVENTS, seed=1, scenarios=only)

    assert [r.scenario.name for r in report.results] == ["mio"]
    assert report.results[0].duplicates_removed > len(EVENTS) * 0.4


def test_an_empty_stream_is_rejected() -> None:
    with pytest.raises(ValueError, match="no hay eventos"):
        run_harness([], seed=1)
