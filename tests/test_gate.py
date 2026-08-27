"""La frontera de ingestión (HU-16).

La promesa de la historia, literal: que lo que incumple el contrato se aparte
con su causa registrada **antes** de llegar al motor. Las dos primeras pruebas
son las que dan sentido a todo lo demás: enseñan el fallo que había y enseñan
que la frontera lo evita.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from gcperros.core.contracts import MatchEvent, OddsUpdate, parse_match_event
from gcperros.core.schema import MATCH_EVENT_SCHEMA
from gcperros.core.stats import summarize_events
from gcperros.engine.pipeline import MatchEngine
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.odds import simulate_odds
from gcperros.governance.gate import IngestionGate, match_event_gate, odds_update_gate
from gcperros.governance.quarantine import InMemoryInvalidStore

CONFIG = MatchConfig(match_id="match-0016", home_team="RMA", away_team="BAR")
SEED = 20260826
REJECTED_AT = datetime(2026, 8, 26, 19, 30, 15, 250000, tzinfo=UTC)


def _clock() -> datetime:
    return REJECTED_AT


def _wire(events: Sequence[MatchEvent] | Sequence[OddsUpdate]) -> list[str]:
    """Los mensajes tal como viajan.

    Se compara sobre el cable y no sobre el objeto de Python porque la marca
    temporal del contrato tiene precisión de milisegundos y el objeto en memoria
    guarda microsegundos. Es una decisión del contrato, no un defecto, y
    `tests/test_pipeline.py` ya la deja por escrito.
    """
    return [event.to_json() for event in events]


@pytest.fixture(scope="module")
def match() -> list[MatchEvent]:
    return simulate_match(SEED, CONFIG)


@pytest.fixture(scope="module")
def shot_without_xg(match: list[MatchEvent]) -> str:
    """Un remate al que le falta su xG: conforme para el lector, veneno para el motor."""
    shot = json.loads(next(e for e in match if e.event_type == "shot").to_json())
    shot["attrs"] = {key: value for key, value in shot["attrs"].items() if key != "xg"}
    return json.dumps(shot)


###############################################################################
# Por qué existe esta historia
###############################################################################


def test_without_the_gate_the_engine_chokes_on_it(shot_without_xg: str) -> None:
    """El lector acepta el mensaje y el fallo aparece mucho después, al agregar."""
    event = parse_match_event(shot_without_xg)

    with pytest.raises(KeyError):
        MatchEngine().process_all([event])


def test_with_the_gate_the_engine_never_sees_it(shot_without_xg: str) -> None:
    store = InMemoryInvalidStore()
    gate = match_event_gate(store, clock=_clock)

    assert gate.admit(shot_without_xg) is None
    assert len(store.records) == 1


###############################################################################
# Lo conforme pasa
###############################################################################


def test_a_conforming_message_comes_back_as_the_contract_object(match: list[MatchEvent]) -> None:
    gate = match_event_gate(InMemoryInvalidStore(), clock=_clock)

    admitted = gate.admit(match[0].to_json())

    assert admitted is not None
    assert admitted.to_json() == match[0].to_json()


def test_a_whole_clean_match_crosses_untouched(match: list[MatchEvent]) -> None:
    store = InMemoryInvalidStore()
    gate = match_event_gate(store, clock=_clock)

    admitted = gate.admit_all(_wire(match))

    assert _wire(admitted) == _wire(match)
    assert store.records == []
    assert gate.stats.conformity == 1.0


def test_the_gate_accepts_the_bytes_the_broker_delivers(match: list[MatchEvent]) -> None:
    """Pub/Sub entrega bytes, no cadenas."""
    gate = match_event_gate(InMemoryInvalidStore(), clock=_clock)

    admitted = gate.admit(match[0].to_json().encode("utf-8"))

    assert admitted is not None
    assert admitted.to_json() == match[0].to_json()


def test_a_clean_stream_reaches_the_same_indicators_through_the_gate(
    match: list[MatchEvent],
) -> None:
    """La frontera filtra; no altera lo que deja pasar."""
    gate = match_event_gate(InMemoryInvalidStore(), clock=_clock)
    admitted = gate.admit_all(_wire(match))

    assert MatchEngine().process_all(admitted).summary == summarize_events(match)


###############################################################################
# Lo no conforme se aparta, con su causa
###############################################################################


def test_the_rejected_message_is_archived_with_its_cause(shot_without_xg: str) -> None:
    store = InMemoryInvalidStore()
    gate = match_event_gate(store, clock=_clock)
    gate.admit(shot_without_xg)

    (record,) = store.records

    assert record.payload == shot_without_xg
    assert record.rules == ("missing_field",)
    assert record.causes == ("attrs.xg: missing_field — campo obligatorio ausente",)
    assert record.rejected_at == REJECTED_AT


def test_garbage_that_is_not_even_utf8_is_archived_too() -> None:
    """Un repositorio que se cae ante la peor basura es el que menos sirve."""
    store = InMemoryInvalidStore()
    gate = match_event_gate(store, clock=_clock)

    assert gate.admit(b"\xff\xfe no soy texto") is None
    assert len(store.records) == 1


def test_a_hostile_stream_only_lets_the_good_ones_through(match: list[MatchEvent]) -> None:
    store = InMemoryInvalidStore()
    gate = match_event_gate(store, clock=_clock)
    delivered: list[bytes | str] = [
        match[0].to_json(),
        "{no cierra",
        "[1, 2, 3]",
        match[1].to_json(),
        '{"event_id": "huerfano"}',
    ]

    admitted = gate.admit_all(delivered)

    assert _wire(admitted) == _wire([match[0], match[1]])
    assert len(store.records) == 3


###############################################################################
# Los contadores
###############################################################################


def test_statistics_start_empty() -> None:
    stats = match_event_gate(InMemoryInvalidStore()).stats

    assert stats.seen == 0
    assert stats.rejected == 0


def test_an_empty_stream_counts_as_conforming() -> None:
    """Devolver cero haría que un arranque en frío pareciera una avería."""
    assert match_event_gate(InMemoryInvalidStore()).stats.conformity == 1.0


def test_statistics_report_what_crossed_and_what_did_not(match: list[MatchEvent]) -> None:
    gate = match_event_gate(InMemoryInvalidStore(), clock=_clock)
    gate.admit_all([match[0].to_json(), "{no cierra", match[1].to_json()])

    stats = gate.stats

    assert (stats.seen, stats.admitted, stats.rejected) == (3, 2, 1)
    assert stats.conformity == pytest.approx(2 / 3)


def test_statistics_break_the_rejections_down_by_cause() -> None:
    """Es lo que el marco de calidad (HU-17) necesita para decir qué falla."""
    gate = match_event_gate(InMemoryInvalidStore(), clock=_clock)
    gate.admit_all(["{no cierra", "[1, 2]", '{"event_id": "huerfano"}'])

    assert gate.stats.by_rule == {
        "malformed_json": 1,
        "not_an_object": 1,
        "missing_field": 1,
    }


def test_a_message_with_several_defects_counts_in_each_of_them() -> None:
    gate = match_event_gate(InMemoryInvalidStore(), clock=_clock)
    gate.admit('{"event_id": "", "event_time": "ayer"}')

    assert set(gate.stats.by_rule) == {"empty_string", "bad_timestamp", "missing_field"}


###############################################################################
# El desacuerdo interno
###############################################################################


def test_a_schema_the_reader_disagrees_with_is_data_not_a_crash(
    match: list[MatchEvent],
) -> None:
    """Si el esquema aprueba y el lector no puede, el defecto es nuestro, no del productor."""

    def refuses(_message: bytes | str) -> MatchEvent:
        raise ValueError("el lector no supo construirlo")

    store = InMemoryInvalidStore()
    gate: IngestionGate[MatchEvent] = IngestionGate(
        MATCH_EVENT_SCHEMA, refuses, store, clock=_clock
    )

    assert gate.admit(match[0].to_json()) is None
    assert store.records[0].rules == ("unreadable",)
    assert gate.stats.rejected == 1


###############################################################################
# El otro flujo
###############################################################################


def test_the_odds_gate_admits_its_own_stream(match: list[MatchEvent]) -> None:
    updates = simulate_odds(SEED, match)
    gate = odds_update_gate(InMemoryInvalidStore(), clock=_clock)

    assert _wire(gate.admit_all(_wire(updates))) == _wire(updates)


def test_a_match_event_is_not_a_valid_quote(match: list[MatchEvent]) -> None:
    """Dos contratos distintos: lo que vale en un topic no vale en el otro."""
    store = InMemoryInvalidStore()
    gate = odds_update_gate(store, clock=_clock)

    assert gate.admit(match[0].to_json()) is None
    assert store.records[0].stream == "odds-updates"


def test_an_incomplete_market_never_reaches_the_engine(match: list[MatchEvent]) -> None:
    updates = simulate_odds(SEED, match)
    quote: dict[str, Any] = json.loads(updates[0].to_json())
    quote["outcomes"] = quote["outcomes"][:1]

    store = InMemoryInvalidStore()
    gate = odds_update_gate(store, clock=_clock)

    assert gate.admit(json.dumps(quote)) is None
    assert store.records[0].rules == ("market_incomplete",)


###############################################################################
# Cierre
###############################################################################


def test_closing_the_gate_closes_the_store() -> None:
    store = InMemoryInvalidStore()
    match_event_gate(store).close()

    assert store.closed
