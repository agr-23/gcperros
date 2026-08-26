"""Pruebas de la tubería completa, de extremo a extremo.

Las demás pruebas comprueban cada pieza por separado. Estas comprueban que
encajan: generar, serializar, publicar, leer de vuelta y procesar, cerrando el
mismo circuito que recorrerá el dato en producción.

Son las que hacen difícil romper algo sin enterarse, porque un cambio en
cualquier eslabón —el formato del mensaje, el orden de los pasos del motor, la
calibración de un generador— rompe alguna de ellas.
"""

from __future__ import annotations

import hashlib

import pytest

from gcperros.core.contracts import (
    ContractViolationError,
    MatchEvent,
    parse_match_event,
    parse_odds_update,
)
from gcperros.core.stats import summarize_events
from gcperros.engine.pipeline import MatchEngine
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.odds import simulate_odds
from gcperros.generators.perturbation import inject_disorder, inject_duplicates
from gcperros.publishing.publisher import (
    MATCH_EVENTS_TOPIC,
    ODDS_UPDATES_TOPIC,
    StreamPublisher,
)
from gcperros.publishing.transport import InMemoryTransport

CONFIG = MatchConfig(match_id="match-e2e", home_team="RMA", away_team="BAR")
SEED = 20260826

#: Margen amplio: aquí se comprueba que el circuito cierra, no dónde está el
#: punto de corte entre latencia y completitud (eso lo mide `test_engine.py`).
WIDE_MARGIN_S = 30.0


@pytest.fixture(scope="module")
def match() -> list[MatchEvent]:
    return simulate_match(SEED, CONFIG)


def _publish_and_collect(events: list[MatchEvent]) -> list[MatchEvent]:
    """Publica el flujo y lo recupera leyendo lo que llegó al transporte."""
    transport = InMemoryTransport()
    StreamPublisher(transport).publish_match_events(events)
    return [parse_match_event(payload) for _, payload, _ in transport.messages]


###############################################################################
# El circuito completo
###############################################################################


def test_the_full_circuit_preserves_the_indicators(match: list[MatchEvent]) -> None:
    """Generar, publicar, leer y procesar da lo mismo que el plano batch."""
    engine = MatchEngine(allowed_lateness_s=WIDE_MARGIN_S)
    result = engine.process_all(_publish_and_collect(match))

    assert result.summary == summarize_events(match)


def test_the_full_circuit_survives_a_hostile_broker(match: list[MatchEvent]) -> None:
    """Con duplicados y desorden a la vez, que es lo que hace un broker real."""
    duplicated, duplication = inject_duplicates(match, seed=3, rate=0.15)
    delivered, disorder = inject_disorder(duplicated, seed=11)

    assert duplication.injected > 0
    assert not disorder.is_ordered

    engine = MatchEngine(allowed_lateness_s=WIDE_MARGIN_S)
    result = engine.process_all(_publish_and_collect(delivered))

    assert result.summary == summarize_events(match)
    assert result.dedup.duplicates == duplication.injected


def test_both_streams_travel_without_mixing(match: list[MatchEvent]) -> None:
    """Dos contratos, dos topics: ninguno puede leerse con el parser del otro."""
    transport = InMemoryTransport()
    publisher = StreamPublisher(transport)
    publisher.publish_match_events(match)
    publisher.publish_odds_updates(simulate_odds(SEED, match))

    by_topic: dict[str, list[bytes]] = {}
    for topic, payload, _ in transport.messages:
        by_topic.setdefault(topic, []).append(payload)

    for payload in by_topic[MATCH_EVENTS_TOPIC]:
        parse_match_event(payload)
        with pytest.raises(ContractViolationError):
            parse_odds_update(payload)

    for payload in by_topic[ODDS_UPDATES_TOPIC]:
        parse_odds_update(payload)
        with pytest.raises(ContractViolationError):
            parse_match_event(payload)


###############################################################################
# El mensaje sobrevive al viaje
###############################################################################


def test_reading_a_message_and_writing_it_again_changes_nothing(
    match: list[MatchEvent],
) -> None:
    """El contrato declara milisegundos, así que la vuelta es exacta en el cable.

    No se compara el objeto de Python: la marca temporal pierde lo que hay por
    debajo del milisegundo, y eso es una decisión del contrato, no un defecto.
    Lo que tiene que ser idéntico es el mensaje.
    """
    for event in match:
        assert parse_match_event(event.to_json()).to_json() == event.to_json()


def test_odds_messages_also_survive_the_round_trip(match: list[MatchEvent]) -> None:
    for update in simulate_odds(SEED, match):
        assert parse_odds_update(update.to_json()).to_json() == update.to_json()


@pytest.mark.parametrize(
    "broken",
    [
        "",
        "no soy json",
        "[]",
        '{"event_id": "x"}',
        '{"event_id":"x","event_time":"ayer","match_id":"m","team":"A","event_type":"pass","attrs":{}}',
        '{"event_id":"x","event_time":"2026-08-26T19:00:00.000Z","match_id":"m","team":"A","event_type":"volea","attrs":{}}',
    ],
)
def test_a_malformed_message_is_rejected_with_its_reason(broken: str) -> None:
    """Rechazar en la frontera es la premisa de la HU-16."""
    with pytest.raises(ContractViolationError):
        parse_match_event(broken)


###############################################################################
# Reproducibilidad congelada
###############################################################################

#: Huella del partido y de las cuotas de la semilla de referencia. Si cambia,
#: es que cambió la salida del generador. Puede ser legítimo —una recalibración,
#: un tipo de evento nuevo— pero nunca debe pasar sin querer: hay que venir aquí
#: y actualizarla a propósito, explicando por qué en el mensaje del commit.
GOLDEN_SEED = 20260826
GOLDEN_MATCH_DIGEST = "cc1dea50c09409d1f02c5dca0bc735db27b69f6fae0fd0e2b25a3cbe1a66efd1"
GOLDEN_ODDS_DIGEST = "d064aca99546a8aacb6cde9528bc5e09629097036fe899187e231cd8d01b39bf"


def _digest(lines: list[str]) -> str:
    payload = "".join(line + "\n" for line in lines).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_the_reference_match_has_not_drifted() -> None:
    events = simulate_match(GOLDEN_SEED, CONFIG)
    assert _digest([event.to_json() for event in events]) == GOLDEN_MATCH_DIGEST, (
        "la salida del generador de partidos cambió. Si es intencionado, "
        "actualiza GOLDEN_MATCH_DIGEST y explica el motivo en el commit."
    )


def test_the_reference_odds_have_not_drifted() -> None:
    events = simulate_match(GOLDEN_SEED, CONFIG)
    updates = simulate_odds(GOLDEN_SEED, events)
    assert _digest([update.to_json() for update in updates]) == GOLDEN_ODDS_DIGEST, (
        "la salida del generador de cuotas cambió. Si es intencionado, "
        "actualiza GOLDEN_ODDS_DIGEST y explica el motivo en el commit."
    )
