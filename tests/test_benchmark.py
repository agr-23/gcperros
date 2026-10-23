"""El banco de carga: la cola simulada con costes conocidos (#18)."""

from __future__ import annotations

import pytest

from gcperros.engine.benchmark import simulate_queue

#: Un milisegundo por evento: capacidad de 1.000 eventos por segundo.
FLAT_COSTS = [0.001] * 200


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
