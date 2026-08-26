"""Comportamiento del deduplicador (HU-11)."""

from __future__ import annotations

import pytest

from gcperros.engine.dedup import DEFAULT_CAPACITY, Deduplicator


def test_first_delivery_is_accepted() -> None:
    assert Deduplicator().accept("a") is True


def test_a_repeat_is_rejected() -> None:
    dedup = Deduplicator()
    assert dedup.accept("a") is True
    assert dedup.accept("a") is False
    assert dedup.accept("a") is False


def test_distinct_identifiers_are_all_accepted() -> None:
    dedup = Deduplicator()
    assert all(dedup.accept(f"event-{index}") for index in range(500))


def test_statistics_track_what_happened() -> None:
    dedup = Deduplicator()
    for event_id in ("a", "b", "a", "c", "b", "a"):
        dedup.accept(event_id)

    stats = dedup.stats
    assert stats.accepted == 3
    assert stats.duplicates == 3
    assert stats.seen == 6
    assert stats.duplicate_rate == pytest.approx(0.5)


def test_duplicate_rate_of_an_untouched_stream_is_zero() -> None:
    assert Deduplicator().stats.duplicate_rate == 0.0


###############################################################################
# Memoria acotada — la garantía es condicional y conviene tenerlo por escrito
###############################################################################


def test_memory_never_exceeds_capacity() -> None:
    dedup = Deduplicator(capacity=10)
    for index in range(1000):
        dedup.accept(f"event-{index}")

    assert dedup.remembered == 10
    assert dedup.stats.forgotten == 990


def test_a_duplicate_within_capacity_is_caught() -> None:
    dedup = Deduplicator(capacity=10)
    dedup.accept("target")
    for index in range(9):
        dedup.accept(f"filler-{index}")

    assert dedup.accept("target") is False


def test_a_duplicate_beyond_capacity_slips_through() -> None:
    """Límite conocido y asumido de la ventana acotada.

    Se comprueba explícitamente para que la garantía quede enunciada con
    precisión —se detecta el duplicado si entre original y repetición pasan
    menos de ``capacity`` eventos distintos— y no como una promesa absoluta que
    el componente no puede dar sobre un flujo no acotado.
    """
    dedup = Deduplicator(capacity=10)
    dedup.accept("target")
    for index in range(10):
        dedup.accept(f"filler-{index}")

    assert dedup.accept("target") is True


def test_default_capacity_covers_a_whole_match() -> None:
    """Un partido emite del orden de 1.300 eventos: la unidad de proceso cabe."""
    assert DEFAULT_CAPACITY > 1_300 * 10


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="al menos 1"):
        Deduplicator(capacity=0)

    with pytest.raises(ValueError, match="al menos 1"):
        Deduplicator(capacity=-5)


def test_capacity_of_one_still_deduplicates_immediate_repeats() -> None:
    """La reentrega inmediata es el caso más frecuente de Pub/Sub."""
    dedup = Deduplicator(capacity=1)
    assert dedup.accept("a") is True
    assert dedup.accept("a") is False
