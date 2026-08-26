"""Comportamiento del reordenador por marca de agua (HU-12)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gcperros.core.contracts import MatchEvent
from gcperros.engine.watermark import WatermarkReorderer

BASE = datetime(2026, 8, 26, 19, 0, 0, tzinfo=UTC)


def _event(second: float, event_id: str | None = None) -> MatchEvent:
    """Evento mínimo situado a ``second`` segundos del saque inicial."""
    return MatchEvent(
        event_id=event_id or f"e{second}",
        event_time=BASE + timedelta(seconds=second),
        match_id="match-0012",
        team="RMA",
        event_type="pass",
        attrs={},
    )


def _drain(reorderer: WatermarkReorderer, events: list[MatchEvent]) -> list[MatchEvent]:
    """Empuja todos los eventos y devuelve, en orden, los que se aplicaron."""
    applied: list[MatchEvent] = []
    for event in events:
        _, released = reorderer.push(event)
        applied.extend(released)
    applied.extend(reorderer.flush())
    return applied


###############################################################################
# La marca de agua en sí
###############################################################################


def test_there_is_no_watermark_before_the_first_event() -> None:
    assert WatermarkReorderer().watermark is None


def test_the_watermark_trails_the_newest_event_by_the_margin() -> None:
    reorderer = WatermarkReorderer(allowed_lateness_s=10.0)
    reorderer.push(_event(100))

    assert reorderer.watermark == BASE + timedelta(seconds=90)


def test_the_watermark_never_moves_backwards() -> None:
    """Si pudiera retroceder, una ventana ya cerrada volvería a abrirse."""
    reorderer = WatermarkReorderer(allowed_lateness_s=5.0)
    reorderer.push(_event(100))
    high = reorderer.watermark

    reorderer.push(_event(60))  # llega uno viejo, dentro de plazo o no
    assert reorderer.watermark == high


def test_an_event_waits_until_the_margin_has_passed() -> None:
    reorderer = WatermarkReorderer(allowed_lateness_s=10.0)

    _, released = reorderer.push(_event(0))
    assert released == []
    assert reorderer.buffered == 1

    # Todavía no: la marca de agua está en 5 - 10 = -5.
    _, released = reorderer.push(_event(5))
    assert released == []

    # Ahora la marca de agua llega a 12 - 10 = 2 y libera el primero.
    _, released = reorderer.push(_event(12))
    assert [event.event_id for event in released] == ["e0"]


###############################################################################
# Reordenamiento
###############################################################################


def test_events_are_applied_in_chronological_order() -> None:
    reorderer = WatermarkReorderer(allowed_lateness_s=30.0)
    shuffled = [_event(second) for second in (14, 3, 27, 1, 9, 22, 5)]

    applied = _drain(reorderer, shuffled)

    assert [event.event_time for event in applied] == sorted(e.event_time for e in shuffled)


def test_nothing_is_lost_when_the_margin_is_wide_enough() -> None:
    reorderer = WatermarkReorderer(allowed_lateness_s=60.0)
    events = [_event(second) for second in (30, 10, 50, 20, 40)]

    applied = _drain(reorderer, events)

    assert len(applied) == len(events)
    assert reorderer.stats.dropped_late == 0
    assert reorderer.stats.timeliness == 1.0


def test_events_sharing_an_instant_are_ordered_deterministically() -> None:
    """El contrato no ordena los empates; el desempate por id sí es estable."""
    first = [_event(10, "b"), _event(10, "a"), _event(10, "c")]
    second = [_event(10, "c"), _event(10, "b"), _event(10, "a")]

    ids_first = [e.event_id for e in _drain(WatermarkReorderer(), first)]
    ids_second = [e.event_id for e in _drain(WatermarkReorderer(), second)]

    assert ids_first == ids_second == ["a", "b", "c"]


###############################################################################
# Rezagados — contados, no perdidos
###############################################################################


def test_a_late_event_is_rejected_and_counted() -> None:
    reorderer = WatermarkReorderer(allowed_lateness_s=5.0)
    reorderer.push(_event(100))  # marca de agua en 95

    accepted, released = reorderer.push(_event(50))

    assert accepted is False
    assert released == []
    assert reorderer.stats.dropped_late == 1


def test_lateness_magnitude_is_recorded() -> None:
    reorderer = WatermarkReorderer(allowed_lateness_s=0.0)
    reorderer.push(_event(100))

    reorderer.push(_event(90))  # 10 s tarde
    reorderer.push(_event(70))  # 30 s tarde

    stats = reorderer.stats
    assert stats.dropped_late == 2
    assert stats.max_lateness_s == pytest.approx(30.0)
    assert stats.mean_lateness_s == pytest.approx(20.0)


def test_every_event_ends_up_in_exactly_one_of_the_two_counters() -> None:
    """Ni uno solo se evapora: es la distinción que pide la historia."""
    reorderer = WatermarkReorderer(allowed_lateness_s=5.0)
    events = [_event(second) for second in (0, 40, 10, 45, 20, 50, 30)]

    _drain(reorderer, events)

    stats = reorderer.stats
    assert stats.released + stats.dropped_late == len(events)
    assert stats.seen == len(events)


def test_timeliness_reflects_what_was_sacrificed() -> None:
    reorderer = WatermarkReorderer(allowed_lateness_s=0.0)
    _drain(reorderer, [_event(second) for second in (0, 100, 50, 200, 150)])

    stats = reorderer.stats
    assert 0.0 < stats.timeliness < 1.0
    assert stats.timeliness == stats.released / stats.seen


def test_timeliness_of_an_untouched_stream_is_one() -> None:
    assert WatermarkReorderer().stats.timeliness == 1.0


###############################################################################
# Vaciado y límites
###############################################################################


def test_flush_releases_everything_still_waiting() -> None:
    reorderer = WatermarkReorderer(allowed_lateness_s=1000.0)
    for second in (5, 1, 3):
        reorderer.push(_event(second))

    assert reorderer.buffered == 3

    remaining = reorderer.flush()
    assert [event.event_id for event in remaining] == ["e1", "e3", "e5"]
    assert reorderer.buffered == 0


def test_flush_on_an_empty_reorderer_is_harmless() -> None:
    assert WatermarkReorderer().flush() == []


def test_the_buffer_high_water_mark_is_tracked() -> None:
    """Cuánta memoria llegó a ocupar la espera, para dimensionar el motor."""
    reorderer = WatermarkReorderer(allowed_lateness_s=1000.0)
    for second in range(20):
        reorderer.push(_event(second))

    assert reorderer.stats.max_buffered == 20


def test_a_zero_margin_applies_immediately() -> None:
    reorderer = WatermarkReorderer(allowed_lateness_s=0.0)

    _, released = reorderer.push(_event(10))
    assert [event.event_id for event in released] == ["e10"]
    assert reorderer.buffered == 0


def test_a_negative_margin_is_rejected() -> None:
    with pytest.raises(ValueError, match="no puede ser negativo"):
        WatermarkReorderer(allowed_lateness_s=-1.0)
