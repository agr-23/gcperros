"""Repositorio de eventos inválidos (HU-16).

Lo que se archiva es evidencia: tiene que reproducir exactamente lo que el
productor mandó, sobrevivir a varias sesiones y poder compararse entre
ejecuciones. Estas pruebas defienden esas tres propiedades.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gcperros.core.schema import MATCH_EVENT_SCHEMA
from gcperros.governance.quarantine import (
    InMemoryInvalidStore,
    InvalidRecord,
    JsonlInvalidStore,
    build_record,
    new_rejection_id,
    payload_digest,
    utc_now,
)
from gcperros.governance.validation import ValidationResult, validate_message

REJECTED_AT = datetime(2026, 8, 26, 19, 30, 15, 250000, tzinfo=UTC)
GARBAGE = '{"event_id": "x"}'


def _verdict(message: str = GARBAGE) -> ValidationResult:
    return validate_message(message, MATCH_EVENT_SCHEMA)


def _record(message: str = GARBAGE, sequence: int = 1) -> InvalidRecord:
    return build_record(_verdict(message), message, sequence, REJECTED_AT)


###############################################################################
# El registro
###############################################################################


def test_the_record_keeps_the_message_exactly_as_it_arrived() -> None:
    """Normalizarlo destruiría la evidencia por la que se archiva."""
    ugly = '  {"event_id" :  "x" ,   "team":"RMA"}  '

    record = build_record(_verdict(ugly), ugly, 1, REJECTED_AT)

    assert record.payload == ugly


def test_the_record_names_the_contract_it_was_judged_against() -> None:
    """El mismo mensaje puede ser inválido bajo v1 y válido bajo v2."""
    record = _record()

    assert record.stream == MATCH_EVENT_SCHEMA.stream
    assert record.contract_version == MATCH_EVENT_SCHEMA.contract_version


def test_the_record_carries_both_the_machine_reason_and_the_human_one() -> None:
    record = _record()

    assert record.rules == ("missing_field",)
    assert any("missing_field" in cause for cause in record.causes)


def test_the_record_serialises_to_a_stable_line() -> None:
    line = _record().to_json()

    assert json.loads(line)["payload"] == GARBAGE
    assert line == _record().to_json()


def test_the_serialised_record_keeps_its_keys_sorted() -> None:
    payload = json.loads(_record().to_json())

    assert list(payload) == sorted(payload)


def test_the_rejection_timestamp_uses_the_contract_format() -> None:
    payload = json.loads(_record().to_json())

    assert payload["rejected_at"] == "2026-08-26T19:30:15.250Z"


###############################################################################
# Identificadores y huellas
###############################################################################


def test_the_same_rejection_gets_the_same_identifier_every_run() -> None:
    """Con `uuid4`, comparar dos corridas del repositorio no significaría nada."""
    assert new_rejection_id("match-events", GARBAGE, 7) == new_rejection_id(
        "match-events", GARBAGE, 7
    )


def test_the_same_garbage_at_a_different_position_is_a_different_rejection() -> None:
    assert new_rejection_id("match-events", GARBAGE, 1) != new_rejection_id(
        "match-events", GARBAGE, 2
    )


def test_the_two_streams_never_share_a_rejection_identifier() -> None:
    assert new_rejection_id("match-events", GARBAGE, 1) != new_rejection_id(
        "odds-updates", GARBAGE, 1
    )


def test_identical_garbage_shares_a_digest() -> None:
    """Es la señal de un productor averiado, no de un mensaje con mala suerte."""
    assert payload_digest(GARBAGE) == payload_digest(GARBAGE)
    assert payload_digest(GARBAGE) != payload_digest(GARBAGE + " ")


###############################################################################
# El repositorio en memoria
###############################################################################


def test_the_in_memory_store_keeps_what_it_is_given() -> None:
    store = InMemoryInvalidStore()
    store.record(_record())

    assert len(store.records) == 1
    assert not store.closed

    store.close()
    assert store.closed


###############################################################################
# El repositorio en fichero
###############################################################################


def test_nothing_rejected_leaves_no_file_behind(tmp_path: Path) -> None:
    """Un fichero vacío haría dudar de si el mecanismo llegó a correr."""
    target = tmp_path / "invalidos.jsonl"
    store = JsonlInvalidStore(target)
    store.close()

    assert not target.exists()


def test_each_rejection_is_one_line(tmp_path: Path) -> None:
    target = tmp_path / "invalidos.jsonl"
    store = JsonlInvalidStore(target)
    for sequence in (1, 2, 3):
        store.record(_record(sequence=sequence))
    store.close()

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert all(json.loads(line)["stream"] == "match-events" for line in lines)


def test_a_second_session_continues_the_first_instead_of_erasing_it(tmp_path: Path) -> None:
    """Un registro archivado es evidencia, y la evidencia no se sobrescribe."""
    target = tmp_path / "invalidos.jsonl"

    first = JsonlInvalidStore(target)
    first.record(_record(sequence=1))
    first.close()

    second = JsonlInvalidStore(target)
    second.record(_record(sequence=2))
    second.close()

    assert len(target.read_text(encoding="utf-8").splitlines()) == 2


def test_the_directory_is_created_if_it_does_not_exist(tmp_path: Path) -> None:
    target = tmp_path / "cuarentena" / "invalidos.jsonl"
    store = JsonlInvalidStore(target)
    store.record(_record())
    store.close()

    assert target.exists()
    assert store.path == target


def test_closing_twice_is_harmless(tmp_path: Path) -> None:
    store = JsonlInvalidStore(tmp_path / "invalidos.jsonl")
    store.record(_record())
    store.close()
    store.close()


def test_the_file_uses_line_feeds_on_every_platform(tmp_path: Path) -> None:
    """El repositorio tiene que salir idéntico byte a byte en Windows y en Linux."""
    target = tmp_path / "invalidos.jsonl"
    store = JsonlInvalidStore(target)
    store.record(_record())
    store.close()

    assert b"\r\n" not in target.read_bytes()


###############################################################################
# El reloj
###############################################################################


def test_the_default_clock_is_timezone_aware() -> None:
    """Una marca sin zona no se puede comparar con las del contrato."""
    assert utc_now().tzinfo is not None


def test_the_clock_can_be_pinned_so_the_archive_is_reproducible() -> None:
    assert _record().rejected_at == REJECTED_AT


@pytest.mark.parametrize("message", ["", "null", "[]"])
def test_even_the_least_message_like_input_can_be_archived(message: str) -> None:
    record = build_record(_verdict(message), message, 1, REJECTED_AT)

    assert record.payload == message
    assert record.causes
