"""Pliegue del linaje de un indicador (HU-18).

La propiedad que estas pruebas defienden es que la huella **conmuta**: dos
derivaciones del mismo número a partir de los mismos eventos coinciden aunque
esos eventos hayan llegado en órdenes distintos. Sin ella, el linaje
introduciría una dependencia del orden que el propio indicador no tiene.
"""

from __future__ import annotations

import json

from gcperros.core.lineage import (
    EMPTY_DIGEST,
    SAMPLE_SIZE,
    LineageAccumulator,
    event_fingerprint,
)

IDS = ("evento-c", "evento-a", "evento-d", "evento-b")


def _folded(*event_ids: str) -> LineageAccumulator:
    accumulator = LineageAccumulator()
    for event_id in event_ids:
        accumulator.add(event_id)
    return accumulator


###############################################################################
# La huella
###############################################################################


def test_nothing_folded_yet_has_the_empty_digest() -> None:
    accumulator = LineageAccumulator()

    assert accumulator.count == 0
    assert accumulator.digest == EMPTY_DIGEST
    assert accumulator.sample == ()


def test_folding_an_event_changes_the_digest() -> None:
    assert _folded("evento-a").digest != EMPTY_DIGEST


def test_the_digest_does_not_depend_on_the_order() -> None:
    """Es la propiedad que hace comparable el streaming con cualquier reproceso."""
    assert _folded(*IDS).digest == _folded(*reversed(IDS)).digest


def test_the_same_events_always_give_the_same_digest() -> None:
    assert _folded(*IDS).digest == _folded(*IDS).digest


def test_different_events_give_different_digests() -> None:
    assert _folded("evento-a").digest != _folded("evento-b").digest


def test_a_repeated_identifier_does_not_cancel_out() -> None:
    """Con un XOR desaparecería sin dejar rastro; con una suma, no.

    La deduplicación (HU-11) debería impedir que llegue repetido, pero un
    mecanismo de auditoría no puede apoyarse en que otro no falle.
    """
    once = _folded("evento-a")
    twice = _folded("evento-a", "evento-a")

    assert once.digest != twice.digest
    assert twice.count == 2


def test_the_digest_is_sixty_four_hexadecimal_characters() -> None:
    digest = _folded(*IDS).digest

    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_the_fingerprint_of_an_identifier_is_stable() -> None:
    assert event_fingerprint("evento-a") == event_fingerprint("evento-a")
    assert event_fingerprint("evento-a") != event_fingerprint("evento-b")


###############################################################################
# La muestra
###############################################################################


def test_the_sample_is_bounded() -> None:
    accumulator = _folded(*(f"evento-{index:04d}" for index in range(500)))

    assert len(accumulator.sample) == SAMPLE_SIZE
    assert accumulator.count == 500


def test_the_sample_keeps_the_smallest_identifiers() -> None:
    """No «los primeros»: sin orden, «primero» no significaría lo mismo dos veces."""
    assert _folded(*IDS).sample == ("evento-a", "evento-b", "evento-c")


def test_the_sample_does_not_depend_on_the_order_either() -> None:
    assert _folded(*IDS).sample == _folded(*reversed(IDS)).sample


def test_a_short_stream_keeps_everything_it_saw() -> None:
    assert _folded("evento-b", "evento-a").sample == ("evento-a", "evento-b")


###############################################################################
# El registro
###############################################################################


def test_the_record_names_what_it_explains() -> None:
    record = _folded(*IDS).record("total_xg", "RMA")

    assert record.indicator == "total_xg"
    assert record.scope == "RMA"
    assert record.event_count == len(IDS)


def test_the_record_serialises_to_a_stable_line() -> None:
    record = _folded(*IDS).record("goals", "RMA")

    assert record.to_json() == _folded(*reversed(IDS)).record("goals", "RMA").to_json()


def test_the_serialised_record_keeps_its_keys_sorted() -> None:
    payload = json.loads(_folded(*IDS).record("goals", "RMA").to_json())

    assert list(payload) == sorted(payload)
    assert payload["event_count"] == 4
    assert payload["sample"] == ["evento-a", "evento-b", "evento-c"]
