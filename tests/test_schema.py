"""El esquema formal describe lo que los generadores emiten de verdad (HU-16).

Un contrato que nadie contrasta contra la realidad es un documento, no un
contrato. Estas pruebas son las que impiden que el esquema y los productores se
separen sin que nadie se entere: si el generador cambia lo que emite, o el
esquema exige algo que nadie manda, alguna de ellas falla.
"""

from __future__ import annotations

import json

import pytest

from gcperros.core.contracts import EVENT_TYPES, MARKET_OUTCOMES, POSSESSION_REASONS, MatchEvent
from gcperros.core.schema import (
    MATCH_EVENT_SCHEMA,
    MATCH_EVENTS_STREAM,
    ODDS_UPDATE_SCHEMA,
    ODDS_UPDATES_STREAM,
    SCHEMAS,
    FieldKind,
)
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.odds import simulate_odds
from gcperros.governance.validation import validate_message
from gcperros.publishing.publisher import MATCH_EVENTS_TOPIC, ODDS_UPDATES_TOPIC

CONFIG = MatchConfig(match_id="match-0016", home_team="RMA", away_team="BAR")
SEED = 20260826

#: Una expulsión ocurre en uno de cada cuatro partidos, así que un solo encuentro
#: no basta para ejercitar los seis tipos de evento. Estas semillas los cubren
#: entre todas, y se fijan aquí para no depender de la suerte en cada ejecución.
COVERING_SEEDS = tuple(range(11))


@pytest.fixture(scope="module")
def match() -> list[MatchEvent]:
    return simulate_match(SEED, CONFIG)


@pytest.fixture(scope="module")
def sample() -> list[MatchEvent]:
    return [event for seed in COVERING_SEEDS for event in simulate_match(seed, CONFIG)]


###############################################################################
# El esquema contra lo que realmente se emite
###############################################################################


def test_every_generated_match_event_is_conforming(match: list[MatchEvent]) -> None:
    for event in match:
        result = validate_message(event.to_json(), MATCH_EVENT_SCHEMA)
        assert result.is_valid, f"{event.event_type}: {result.causes}"


def test_every_generated_odds_update_is_conforming(match: list[MatchEvent]) -> None:
    for update in simulate_odds(SEED, match):
        result = validate_message(update.to_json(), ODDS_UPDATE_SCHEMA)
        assert result.is_valid, f"{update.market}: {result.causes}"


def test_the_sample_exercises_every_event_type(sample: list[MatchEvent]) -> None:
    """Sin esto, un tipo nunca emitido pasaría por validado sin haberse mirado."""
    assert {event.event_type for event in sample} == EVENT_TYPES


def test_every_event_of_the_sample_is_conforming(sample: list[MatchEvent]) -> None:
    for event in sample:
        result = validate_message(event.to_json(), MATCH_EVENT_SCHEMA)
        assert result.is_valid, f"{event.event_type}: {result.causes}"


###############################################################################
# El esquema no puede tener huecos
###############################################################################


def test_every_event_type_declares_its_attributes() -> None:
    """Un tipo sin variante declarada pasaría la frontera sin que nadie mire dentro."""
    assert set(MATCH_EVENT_SCHEMA.variants) == EVENT_TYPES


def test_every_market_declares_its_outcomes() -> None:
    spec = ODDS_UPDATE_SCHEMA.market_outcomes
    assert spec is not None
    assert set(spec.outcomes_by_value) == set(MARKET_OUTCOMES)


def test_the_generator_only_uses_reasons_the_contract_admits(sample: list[MatchEvent]) -> None:
    """El vocabulario de `reason` es cerrado: ampliarlo obliga a versionar."""
    emitted = {event.attrs["reason"] for event in sample if event.event_type == "possession_change"}
    assert emitted <= POSSESSION_REASONS


###############################################################################
# El sobre
###############################################################################


def test_the_envelope_carries_what_lets_us_route_without_opening_the_payload() -> None:
    names = {spec.name for spec in MATCH_EVENT_SCHEMA.envelope}
    assert {"event_id", "event_time", "match_id", "team", "event_type"} <= names


def test_both_streams_stamp_their_contract_version() -> None:
    for schema in SCHEMAS.values():
        version = next(spec for spec in schema.envelope if spec.name == "contract_version")
        assert version.allowed == frozenset({schema.contract_version})


def test_the_timestamp_is_typed_as_such_and_not_as_a_plain_string() -> None:
    for schema in SCHEMAS.values():
        stamp = next(spec for spec in schema.envelope if spec.name == "event_time")
        assert stamp.kind is FieldKind.TIMESTAMP


def test_stream_names_match_the_topics_they_travel_through() -> None:
    """El contrato, el canal y el código nombran lo mismo de la misma forma."""
    assert MATCH_EVENTS_STREAM == MATCH_EVENTS_TOPIC
    assert ODDS_UPDATES_STREAM == ODDS_UPDATES_TOPIC


###############################################################################
# Campos obligatorios
###############################################################################


def test_required_fields_include_the_variant_with_its_container_prefix() -> None:
    required = MATCH_EVENT_SCHEMA.required_field_names("shot")

    assert "event_id" in required
    assert "attrs.xg" in required
    assert "attrs.is_goal" in required


def test_required_fields_without_a_variant_are_just_the_envelope() -> None:
    required = MATCH_EVENT_SCHEMA.required_field_names()

    assert required == tuple(spec.name for spec in MATCH_EVENT_SCHEMA.envelope)


def test_required_fields_of_a_stream_without_variants_ignore_the_argument() -> None:
    with_variant = ODDS_UPDATE_SCHEMA.required_field_names("1x2")
    assert with_variant == ODDS_UPDATE_SCHEMA.required_field_names()


def test_the_declared_attributes_are_exactly_the_ones_emitted(sample: list[MatchEvent]) -> None:
    """Ni de menos —se colaría basura— ni de más —se rechazaría lo bueno."""
    seen: dict[str, set[str]] = {}
    for event in sample:
        payload = json.loads(event.to_json())
        seen.setdefault(event.event_type, set()).update(payload["attrs"])

    for event_type, specs in MATCH_EVENT_SCHEMA.variants.items():
        assert {spec.name for spec in specs} == seen[event_type], event_type
