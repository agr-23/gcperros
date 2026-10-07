"""El motor fecha cada aplicación y mide su propia latencia (#18).

Aquí se pone en números la tensión de la sección 3 del documento de
decisiones: cuánto espera de verdad un evento por culpa de la marca de agua.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from gcperros.core.contracts import MatchEvent
from gcperros.engine.pipeline import MatchEngine, Outcome
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.perturbation import inject_duplicates

CONFIG = MatchConfig(match_id="match-0018", home_team="RMA", away_team="BAR")
SEED = 20260826
HALF_TIME_S = 15 * 60


@pytest.fixture(scope="module")
def clean() -> list[MatchEvent]:
    return simulate_match(SEED, CONFIG)


def _with_arrivals(
    events: list[MatchEvent], seed: int, mean_delay_s: float
) -> list[tuple[MatchEvent, datetime]]:
    """Cada evento con su instante de llegada, en orden de llegada."""
    rng = random.Random(seed)
    delivered = [
        (event, event.event_time + timedelta(seconds=rng.expovariate(1.0 / mean_delay_s)))
        for event in events
    ]
    return sorted(delivered, key=lambda item: item[1])


def _event(sequence: int, offset_s: float) -> MatchEvent:
    return MatchEvent(
        event_id=f"ev-{sequence}",
        event_time=datetime(2026, 8, 26, 20, 0, tzinfo=UTC) + timedelta(seconds=offset_s),
        match_id="match-0018",
        team="RMA",
        event_type="foul",
        attrs={},
    )


###############################################################################
# La tensión de la sección 3, medida
###############################################################################


def test_every_applied_event_leaves_a_sample(clean: list[MatchEvent]) -> None:
    result = MatchEngine().process_all(clean)

    assert result.latency.count == len(clean) == result.watermark.released


def test_the_margin_is_a_floor_not_the_wait(clean: list[MatchEvent]) -> None:
    """Un evento no espera «el margen»: espera a que llegue algo más allá de él."""
    result = MatchEngine(allowed_lateness_s=10.0).process_all(clean)

    assert result.latency.p50_s >= 10.0
    assert result.latency.p95_s > 20.0
    # Sin llegadas, toda la latencia la puso el motor.
    assert result.latency.mean_wait_s == result.latency.mean_s


def test_a_wider_margin_costs_latency_in_seconds(clean: list[MatchEvent]) -> None:
    tight = MatchEngine(allowed_lateness_s=2.0).process_all(clean).latency
    wide = MatchEngine(allowed_lateness_s=10.0).process_all(clean).latency

    assert tight.p50_s < wide.p50_s
    assert tight.p95_s < wide.p95_s


def test_the_watermark_only_moves_when_something_arrives(clean: list[MatchEvent]) -> None:
    """El último evento del primer tiempo espera todo el descanso."""
    result = MatchEngine().process_all(clean)

    assert result.latency.max_s > HALF_TIME_S


def test_transport_and_wait_add_up(clean: list[MatchEvent]) -> None:
    engine = MatchEngine()
    for event, arrived_at in _with_arrivals(clean, seed=7, mean_delay_s=2.0):
        engine.process(event, arrived_at=arrived_at)
    engine.flush()
    stats = engine.latency

    assert stats.count == len(clean) - engine.watermark_stats.dropped_late
    assert stats.mean_s > stats.mean_wait_s
    assert stats.mean_s - stats.mean_wait_s == pytest.approx(2.0, abs=0.5)


###############################################################################
# Lo que no deja muestra
###############################################################################


def test_duplicates_and_late_events_leave_no_sample(clean: list[MatchEvent]) -> None:
    delivered, report = inject_duplicates(clean, seed=3, rate=0.2)
    result = MatchEngine(allowed_lateness_s=0.0).process_all(delivered)

    assert report.injected > 0
    assert result.watermark.dropped_late > 0
    assert result.latency.count == result.watermark.released


def test_the_clock_never_goes_back() -> None:
    """Una llegada fechada antes que la anterior se aplica con el reloj actual."""
    engine = MatchEngine(allowed_lateness_s=0.0)
    first, second = _event(1, 0.0), _event(2, 1.0)

    engine.process(first, arrived_at=first.event_time + timedelta(seconds=5))
    outcome = engine.process(second, arrived_at=second.event_time + timedelta(seconds=1))

    assert outcome is Outcome.ACCEPTED
    # Ambos se fechan con el reloj en +5 s: totales de 5 s y 4 s, no de 5 s y 2 s.
    assert (engine.latency.mean_s, engine.latency.max_s) == (4.5, 5.0)


def test_flush_dates_the_remainder_with_the_last_clock() -> None:
    engine = MatchEngine(allowed_lateness_s=60.0)
    events = [_event(i, float(i)) for i in range(3)]
    for event in events:
        engine.process(event)
    assert engine.latency.count == 0

    engine.flush()

    assert engine.latency.count == 3
    assert engine.latency.max_s == 2.0


def test_an_empty_stream_has_no_latency() -> None:
    engine = MatchEngine()
    engine.flush()

    assert engine.latency.count == 0
