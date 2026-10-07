"""Latencia por evento: muestras, percentiles y el registro que las produce (#18)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gcperros.core.contracts import MatchEvent
from gcperros.engine.latency import (
    LatencyRecorder,
    LatencySample,
    LatencyStats,
    percentile,
)

T0 = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)


def _event(sequence: int, offset_s: float) -> MatchEvent:
    return MatchEvent(
        event_id=f"ev-{sequence}",
        event_time=T0 + timedelta(seconds=offset_s),
        match_id="match-0018",
        event_type="pass",
        team="RMA",
        attrs={},
    )


def _sample(transport_s: float, wait_s: float) -> LatencySample:
    arrived = T0 + timedelta(seconds=transport_s)
    return LatencySample("x", T0, arrived, arrived + timedelta(seconds=wait_s))


def test_a_sample_splits_the_journey_in_two() -> None:
    sample = _sample(transport_s=1.5, wait_s=10.0)

    assert (sample.transport_s, sample.wait_s, sample.total_s) == (1.5, 10.0, 11.5)


def test_percentile_is_nearest_rank_and_never_interpolates() -> None:
    values = [5.0, 1.0, 4.0, 2.0, 3.0]

    assert percentile(values, 0.50) == 3.0
    assert percentile(values, 0.95) == 5.0
    assert percentile(values, 0.0) == 1.0
    assert percentile([7.0], 0.95) == 7.0


def test_percentile_rejects_nothing_to_rank_or_a_bad_quantile() -> None:
    with pytest.raises(ValueError, match="no hay valores"):
        percentile([], 0.5)
    with pytest.raises(ValueError, match="entre 0 y 1"):
        percentile([1.0], 1.5)


def test_stats_separate_what_the_engine_added_from_the_total() -> None:
    samples = tuple(_sample(transport_s=2.0, wait_s=w) for w in (10.0, 12.0, 14.0, 40.0))
    stats = LatencyStats.from_samples(samples)

    assert stats.count == 4
    assert stats.mean_s == pytest.approx(21.0)
    assert stats.mean_wait_s == pytest.approx(19.0)
    assert (stats.p50_s, stats.p95_s, stats.max_s) == (14.0, 42.0, 42.0)


def test_no_samples_is_an_empty_summary_not_an_error() -> None:
    assert LatencyStats.from_samples(()) == LatencyStats.empty()
    assert LatencyStats.empty().count == 0


def test_the_recorder_closes_a_sample_when_the_event_is_applied() -> None:
    recorder = LatencyRecorder()
    event = _event(1, 0.0)

    recorder.arrived(event, T0 + timedelta(seconds=2))
    assert not recorder.samples

    recorder.applied(event, T0 + timedelta(seconds=12))
    (sample,) = recorder.samples
    assert sample.event_id == "ev-1"
    assert (sample.transport_s, sample.wait_s) == (2.0, 10.0)
    assert recorder.stats().p95_s == 12.0


def test_applying_what_never_arrived_is_a_bug_and_says_so() -> None:
    recorder = LatencyRecorder()

    with pytest.raises(KeyError):
        recorder.applied(_event(9, 0.0), T0)


def test_samples_keep_the_order_of_application() -> None:
    recorder = LatencyRecorder()
    first, second = _event(1, 0.0), _event(2, 1.0)
    recorder.arrived(first, T0)
    recorder.arrived(second, T0)

    recorder.applied(second, T0 + timedelta(seconds=5))
    recorder.applied(first, T0 + timedelta(seconds=6))

    assert [s.event_id for s in recorder.samples] == ["ev-2", "ev-1"]
