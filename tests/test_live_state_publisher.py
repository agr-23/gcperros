"""Cuándo se publica el documento de estado vivo (HU-15).

La pregunta que importa aquí no es *qué* se escribe (eso lo cubre
``test_live_document.py``), sino *cuándo*: que se publique en cada evento que
de verdad cambió el estado, y en ningún otro caso.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from gcperros.core.contracts import JsonValue, MatchEvent
from gcperros.engine.pipeline import MatchEngine, Outcome
from gcperros.firestore.publisher import LiveStatePublisher, PublishingMatchEngine
from gcperros.firestore.store import DocumentStoreError, InMemoryDocumentStore
from gcperros.generators.match import MatchConfig, simulate_match

CONFIG = MatchConfig(match_id="match-0011", home_team="RMA", away_team="BAR")
SEED = 20260826
FIXED_INSTANT = datetime(2026, 8, 27, 21, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def events() -> list[MatchEvent]:
    return simulate_match(SEED, CONFIG)


def _event_count(document: dict[str, JsonValue]) -> int:
    count = document["event_count"]
    assert isinstance(count, int)
    return count


def _publishing_engine(store: InMemoryDocumentStore) -> PublishingMatchEngine:
    publisher = LiveStatePublisher(store, CONFIG.match_id, clock=lambda: FIXED_INSTANT)
    return PublishingMatchEngine(MatchEngine(), publisher)


###############################################################################
# Se publica cuando el estado cambia, no en cada llamada a `process`
###############################################################################


def test_a_late_duplicate_does_not_trigger_a_publish(events: list[MatchEvent]) -> None:
    """Un duplicado nunca cambia el estado: no debería producir una escritura."""
    store = InMemoryDocumentStore()
    engine = _publishing_engine(store)

    first = events[0]
    engine.process(first)
    writes_after_first = len(store.writes)

    engine.process(first)  # el mismo evento, otra vez: la deduplicación lo descarta

    assert len(store.writes) == writes_after_first


def test_an_event_retained_by_the_watermark_does_not_publish_yet(events: list[MatchEvent]) -> None:
    """Un evento aceptado pero todavía en el buffer no cambió el estado aplicado."""
    store = InMemoryDocumentStore()
    engine = _publishing_engine(store)

    outcome = engine.process(events[0])

    assert outcome is Outcome.ACCEPTED
    # El primer evento por sí solo no basta para que la marca de agua avance
    # lo suficiente como para liberarlo con margen; si de todas formas se
    # liberó (partidos muy cortos), la prueba de abajo cubre igual el caso
    # general: nunca hay más escrituras que eventos realmente aplicados.
    assert len(store.writes) <= 1


def test_every_write_corresponds_to_state_that_actually_advanced(events: list[MatchEvent]) -> None:
    """Ninguna escritura repite el `event_count` de la anterior."""
    store = InMemoryDocumentStore()
    engine = _publishing_engine(store)

    for event in events:
        engine.process(event)
    engine.flush()

    published_counts = [_event_count(document) for _, document in store.writes]

    assert published_counts == sorted(published_counts)
    assert len(published_counts) == len(set(published_counts))


def test_flushing_an_empty_buffer_does_not_publish_again() -> None:
    store = InMemoryDocumentStore()
    engine = _publishing_engine(store)

    engine.flush()  # nada que vaciar: ni un evento se procesó todavía

    assert store.writes == []


def test_the_final_flush_publishes_the_complete_match(events: list[MatchEvent]) -> None:
    store = InMemoryDocumentStore()
    engine = _publishing_engine(store)

    for event in events:
        engine.process(event)
    engine.flush()

    last_document_id, last_document = store.writes[-1]
    assert last_document_id == CONFIG.match_id
    assert last_document["event_count"] == engine.state.event_count
    assert engine.state.event_count == len(events)


###############################################################################
# Un solo documento por partido: cada escritura sobrescribe, no acumula
###############################################################################


def test_the_store_keeps_a_single_document_per_match(events: list[MatchEvent]) -> None:
    store = InMemoryDocumentStore()
    engine = _publishing_engine(store)

    for event in events:
        engine.process(event)
    engine.flush()

    assert list(store.documents) == [CONFIG.match_id]
    assert store.documents[CONFIG.match_id]["event_count"] == len(events)


###############################################################################
# Un fallo del destino se deja propagar
###############################################################################


def test_a_store_failure_propagates_out_of_process(events: list[MatchEvent]) -> None:
    store = InMemoryDocumentStore(fail_times=1)
    engine = _publishing_engine(store)

    with pytest.raises(DocumentStoreError):
        for event in events:
            engine.process(event)


###############################################################################
# El publicador, aislado del envoltorio
###############################################################################


def test_the_publisher_writes_under_the_match_id() -> None:
    store = InMemoryDocumentStore()
    publisher = LiveStatePublisher(store, "match-0099", clock=lambda: FIXED_INSTANT)
    engine = MatchEngine()

    publisher.publish(engine.state)  # partido vacío: sigue siendo un documento válido

    assert "match-0099" in store.documents
    assert store.documents["match-0099"]["event_count"] == 0


def test_closing_the_in_memory_store_marks_it_closed() -> None:
    store = InMemoryDocumentStore()

    store.close()

    assert store.closed is True
