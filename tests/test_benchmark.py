"""El banco de carga: costes medidos, cola simulada y punto de saturación (#18)."""

from __future__ import annotations

import pytest

from gcperros.core.contracts import MatchEvent
from gcperros.engine.benchmark import (
    BenchmarkReport,
    RateResult,
    measure_costs,
    run_benchmark,
    simulate_queue,
)
from gcperros.generators.match import MatchConfig, simulate_match

CONFIG = MatchConfig(match_id="match-0018", home_team="RMA", away_team="BAR")

#: Un milisegundo por evento: capacidad de 1.000 eventos por segundo.
FLAT_COSTS = [0.001] * 200


@pytest.fixture(scope="module")
def clean() -> list[MatchEvent]:
    return simulate_match(20260826, CONFIG)


###############################################################################
# La cola simulada, con costes conocidos
###############################################################################


def test_under_capacity_nothing_waits() -> None:
    result = simulate_queue(FLAT_COSTS, rate_events_per_s=100.0)

    assert result.utilization == pytest.approx(0.1)
    assert not result.saturated
    assert result.max_backlog == 1
    assert (result.p50_s, result.p95_s, result.max_s) == pytest.approx((0.001, 0.001, 0.001))


def test_over_capacity_the_backlog_grows_for_as_long_as_it_lasts() -> None:
    result = simulate_queue(FLAT_COSTS, rate_events_per_s=2_000.0)

    assert result.utilization == pytest.approx(2.0)
    assert result.saturated
    # A doble ritmo del que se atiende, la mitad de lo emitido sigue en cola.
    assert result.final_backlog == result.max_backlog == pytest.approx(100, abs=1)
    assert result.p50_s < result.p95_s < result.max_s
    assert result.max_s == pytest.approx(0.1, abs=0.002)


def test_saturation_starts_exactly_at_full_utilization() -> None:
    assert simulate_queue(FLAT_COSTS, rate_events_per_s=1_000.0).saturated
    assert not simulate_queue(FLAT_COSTS, rate_events_per_s=999.0).saturated


def test_a_spike_is_absorbed_when_there_is_slack() -> None:
    """Un evento caro retrasa a los que vienen detrás, pero la cola se vacía."""
    costs = [0.001] * 10 + [0.05] + [0.001] * 50
    result = simulate_queue(costs, rate_events_per_s=500.0)

    assert not result.saturated
    assert result.max_backlog > 1
    assert result.final_backlog == 1


def test_the_queue_rejects_nothing_to_simulate_or_a_bad_rate() -> None:
    with pytest.raises(ValueError, match="no hay costes"):
        simulate_queue([], rate_events_per_s=1.0)
    with pytest.raises(ValueError, match="positiva"):
        simulate_queue(FLAT_COSTS, rate_events_per_s=0.0)


###############################################################################
# Los costes medidos con el motor real
###############################################################################


def test_every_event_gets_a_cost(clean: list[MatchEvent]) -> None:
    costs = measure_costs(clean[:100], repeats=2)

    assert len(costs) == 100
    assert all(cost >= 0.0 for cost in costs)


def test_measuring_rejects_an_empty_stream_or_no_repeats(clean: list[MatchEvent]) -> None:
    with pytest.raises(ValueError, match="no hay eventos"):
        measure_costs([])
    with pytest.raises(ValueError, match="repetici"):
        measure_costs(clean[:5], repeats=0)


###############################################################################
# El barrido
###############################################################################


def test_the_sweep_locates_the_saturation_point(clean: list[MatchEvent]) -> None:
    report = run_benchmark(clean, rates=(1.0, 1e9), repeats=1)

    assert report.events == len(clean)
    assert report.capacity_events_per_s == pytest.approx(1.0 / report.mean_cost_s)
    assert [r.saturated for r in report.results] == [False, True]
    assert report.saturation_rate == 1e9


def test_utilization_grows_with_the_rate(clean: list[MatchEvent]) -> None:
    rates = (10.0, 100.0, 1_000.0)
    report = run_benchmark(clean[:200], rates=rates, repeats=1)

    utilizations = [r.utilization for r in report.results]
    assert utilizations == sorted(utilizations)
    assert [r.rate_events_per_s for r in report.results] == list(rates)


def test_no_saturation_is_reported_as_none() -> None:
    steady = RateResult(1.0, 0.5, 0.0, 0.0, 0.0, 1, 1)
    report = BenchmarkReport("m", 1, 0.5, (steady,))

    assert report.saturation_rate is None
