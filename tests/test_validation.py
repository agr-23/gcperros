"""Comprobación de mensajes contra el contrato (HU-16).

Cada motivo de rechazo tiene aquí la prueba que lo dispara. Un motivo que no se
puede provocar es un motivo que nadie ha visto funcionar, y en la frontera eso
significa un agujero por el que pasaría basura.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from gcperros.core.schema import (
    MATCH_EVENT_SCHEMA,
    ODDS_UPDATE_SCHEMA,
    FieldKind,
    FieldSpec,
    StreamSchema,
)
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.odds import simulate_odds
from gcperros.governance.validation import (
    ViolationRule,
    validate_message,
    validate_payload,
)

CONFIG = MatchConfig(match_id="match-0016", home_team="RMA", away_team="BAR")
SEED = 20260826


@pytest.fixture(scope="module")
def shot() -> dict[str, Any]:
    """Un remate real del generador, del que partir para romper cosas."""
    events = simulate_match(SEED, CONFIG)
    payload: dict[str, Any] = json.loads(
        next(e for e in events if e.event_type == "shot").to_json()
    )
    return payload


@pytest.fixture(scope="module")
def quote() -> dict[str, Any]:
    """Una cotización real del generador."""
    events = simulate_match(SEED, CONFIG)
    updates = simulate_odds(SEED, events)
    payload: dict[str, Any] = json.loads(next(u for u in updates if u.market == "1x2").to_json())
    return payload


def _rules(payload: dict[str, Any]) -> tuple[str, ...]:
    return validate_payload(payload, MATCH_EVENT_SCHEMA).rules


def _fields(payload: dict[str, Any]) -> list[str]:
    return [v.field for v in validate_payload(payload, MATCH_EVENT_SCHEMA).violations]


###############################################################################
# El caso base
###############################################################################


def test_an_untouched_event_is_conforming(shot: dict[str, Any]) -> None:
    result = validate_payload(shot, MATCH_EVENT_SCHEMA)

    assert result.is_valid
    assert result.violations == ()
    assert result.causes == ()


def test_the_verdict_carries_the_payload_it_approved(shot: dict[str, Any]) -> None:
    """Quien valida no debería tener que volver a interpretar el mensaje."""
    result = validate_message(json.dumps(shot), MATCH_EVENT_SCHEMA)

    assert result.payload == shot


def test_the_verdict_names_the_stream_and_version_it_applied(shot: dict[str, Any]) -> None:
    result = validate_payload(shot, MATCH_EVENT_SCHEMA)

    assert result.stream == MATCH_EVENT_SCHEMA.stream
    assert result.contract_version == MATCH_EVENT_SCHEMA.contract_version


###############################################################################
# Un motivo por cada forma de incumplir
###############################################################################


def test_a_message_that_is_not_json_is_a_violation_not_an_exception() -> None:
    result = validate_message("{esto no cierra", MATCH_EVENT_SCHEMA)

    assert result.rules == (ViolationRule.MALFORMED_JSON.value,)


def test_bytes_that_are_not_even_utf8_are_a_violation_too() -> None:
    result = validate_message(b"\xff\xfe basura binaria", MATCH_EVENT_SCHEMA)

    assert not result.is_valid
    assert result.rules == (ViolationRule.MALFORMED_JSON.value,)


def test_a_json_array_is_not_a_message() -> None:
    result = validate_message("[1, 2, 3]", MATCH_EVENT_SCHEMA)

    assert result.rules == (ViolationRule.NOT_AN_OBJECT.value,)


def test_a_missing_envelope_field_is_caught(shot: dict[str, Any]) -> None:
    broken = {key: value for key, value in shot.items() if key != "event_id"}

    assert _rules(broken) == (ViolationRule.MISSING_FIELD.value,)
    assert _fields(broken) == ["event_id"]


def test_a_missing_attribute_is_caught(shot: dict[str, Any]) -> None:
    """El defecto que motivó la historia: un remate sin su xG."""
    broken = dict(shot, attrs={k: v for k, v in shot["attrs"].items() if k != "xg"})

    assert _rules(broken) == (ViolationRule.MISSING_FIELD.value,)
    assert _fields(broken) == ["attrs.xg"]


def test_a_field_of_the_wrong_type_is_caught(shot: dict[str, Any]) -> None:
    broken = dict(shot, attrs=dict(shot["attrs"], xg="mucho"))

    assert _rules(broken) == (ViolationRule.WRONG_TYPE.value,)


def test_a_boolean_does_not_pass_for_a_number(shot: dict[str, Any]) -> None:
    """`bool` es subclase de `int`: sin cuidado explícito, `True` valdría 1."""
    broken = dict(shot, attrs=dict(shot["attrs"], xg=True))

    assert _rules(broken) == (ViolationRule.WRONG_TYPE.value,)


def test_a_number_does_not_pass_for_a_boolean(shot: dict[str, Any]) -> None:
    broken = dict(shot, attrs=dict(shot["attrs"], is_goal=1))

    assert _rules(broken) == (ViolationRule.WRONG_TYPE.value,)


def test_an_empty_string_is_not_an_identifier(shot: dict[str, Any]) -> None:
    broken = dict(shot, match_id="")

    assert _rules(broken) == (ViolationRule.EMPTY_STRING.value,)


def test_a_malformed_timestamp_is_caught(shot: dict[str, Any]) -> None:
    broken = dict(shot, event_time="ayer por la tarde")

    assert _rules(broken) == (ViolationRule.BAD_TIMESTAMP.value,)


def test_a_timestamp_without_milliseconds_is_not_the_agreed_format(shot: dict[str, Any]) -> None:
    broken = dict(shot, event_time="2026-08-26T19:00:00Z")

    assert _rules(broken) == (ViolationRule.BAD_TIMESTAMP.value,)


def test_an_unknown_event_type_is_caught(shot: dict[str, Any]) -> None:
    broken = dict(shot, event_type="chilena")

    assert _rules(broken) == (ViolationRule.VALUE_NOT_ALLOWED.value,)


def test_a_foreign_contract_version_is_caught(shot: dict[str, Any]) -> None:
    """Un `v2` que nadie acordó no puede colarse como si fuera el contrato vigente."""
    broken = dict(shot, contract_version="v2")

    assert _rules(broken) == (ViolationRule.VALUE_NOT_ALLOWED.value,)


def test_a_reason_outside_the_closed_vocabulary_is_caught() -> None:
    events = simulate_match(SEED, CONFIG)
    change = json.loads(next(e for e in events if e.event_type == "possession_change").to_json())
    broken = dict(change, attrs=dict(change["attrs"], reason="se aburrieron"))

    assert _rules(broken) == (ViolationRule.VALUE_NOT_ALLOWED.value,)


@pytest.mark.parametrize(("field", "value"), [("x", 999.0), ("y", -3.0), ("xg", 1.5)])
def test_a_value_outside_its_range_is_caught(
    shot: dict[str, Any], field: str, value: float
) -> None:
    """Una coordenada imposible es la firma de un dato corrompido en el transporte."""
    broken = dict(shot, attrs=dict(shot["attrs"], **{field: value}))

    assert _rules(broken) == (ViolationRule.OUT_OF_RANGE.value,)


def test_attrs_that_are_not_an_object_are_caught(shot: dict[str, Any]) -> None:
    broken = dict(shot, attrs="nada")

    assert ViolationRule.WRONG_TYPE.value in _rules(broken)


###############################################################################
# Cómo se acumulan las violaciones
###############################################################################


def test_every_broken_field_is_reported_not_just_the_first(shot: dict[str, Any]) -> None:
    """Un rechazo que informa de un problema por vez obliga a reenviar N veces."""
    broken = dict(shot, event_id="", event_time="cuando sea", attrs={})

    fields = _fields(broken)

    assert "event_id" in fields
    assert "event_time" in fields
    assert {"attrs.x", "attrs.y", "attrs.xg", "attrs.is_goal", "attrs.period"} <= set(fields)


def test_one_violation_per_field_and_no_more(shot: dict[str, Any]) -> None:
    """Un campo vacío tampoco está entre los admitidos; decirlo dos veces no informa."""
    broken = dict(shot, event_type="")

    assert _fields(broken) == ["event_type"]


def test_violations_come_out_in_the_order_the_schema_declares() -> None:
    """Un informe cuyo orden cambia entre ejecuciones no se puede comparar."""
    broken: dict[str, Any] = {"attrs": {}}

    declared = [spec.name for spec in MATCH_EVENT_SCHEMA.envelope]
    reported = [field for field in _fields(broken) if "." not in field]

    assert reported == [name for name in declared if name != "attrs"]


def test_an_unusable_discriminator_does_not_invent_attribute_causes(
    shot: dict[str, Any],
) -> None:
    """Sin saber qué evento es, exigir unos atributos u otros sería adivinar."""
    broken = dict(shot, event_type="chilena", attrs={})

    assert _fields(broken) == ["event_type"]


def test_the_causes_read_like_something_a_person_can_act_on(shot: dict[str, Any]) -> None:
    broken = dict(shot, attrs={k: v for k, v in shot["attrs"].items() if k != "xg"})

    (cause,) = validate_payload(broken, MATCH_EVENT_SCHEMA).causes

    assert cause.startswith("attrs.xg: missing_field")


def test_repeated_rules_are_listed_once(shot: dict[str, Any]) -> None:
    broken = dict(shot, attrs={})

    assert _rules(broken) == (ViolationRule.MISSING_FIELD.value,)


###############################################################################
# El flujo de cuotas
###############################################################################


def test_an_untouched_quote_is_conforming(quote: dict[str, Any]) -> None:
    assert validate_payload(quote, ODDS_UPDATE_SCHEMA).is_valid


def test_an_incomplete_market_is_rejected(quote: dict[str, Any]) -> None:
    """Sin todos sus resultados no se puede descontar el margen del operador."""
    broken = dict(quote, outcomes=quote["outcomes"][:2])

    result = validate_payload(broken, ODDS_UPDATE_SCHEMA)

    assert result.rules == (ViolationRule.MARKET_INCOMPLETE.value,)


def test_a_market_with_a_repeated_outcome_is_rejected(quote: dict[str, Any]) -> None:
    """Un conjunto daría esto por bueno: tres entradas y tres resultados."""
    first = quote["outcomes"][0]
    broken = dict(quote, outcomes=[first, first, quote["outcomes"][2]])

    result = validate_payload(broken, ODDS_UPDATE_SCHEMA)

    assert result.rules == (ViolationRule.MARKET_INCOMPLETE.value,)


def test_an_outcome_without_a_price_is_rejected(quote: dict[str, Any]) -> None:
    broken = dict(quote, outcomes=[{"outcome": "home"}, *quote["outcomes"][1:]])

    result = validate_payload(broken, ODDS_UPDATE_SCHEMA)

    assert ViolationRule.MALFORMED_OUTCOME.value in result.rules


def test_an_outcome_that_is_not_even_an_object_is_rejected(quote: dict[str, Any]) -> None:
    broken = dict(quote, outcomes=["home", *quote["outcomes"][1:]])

    result = validate_payload(broken, ODDS_UPDATE_SCHEMA)

    assert ViolationRule.MALFORMED_OUTCOME.value in result.rules


def test_an_unpublishable_price_is_rejected(quote: dict[str, Any]) -> None:
    """Ninguna casa publica una cuota de 500: si llega, algo se corrompió."""
    outcomes = [dict(entry) for entry in quote["outcomes"]]
    outcomes[0]["odds"] = 500.0
    broken = dict(quote, outcomes=outcomes)

    result = validate_payload(broken, ODDS_UPDATE_SCHEMA)

    assert result.rules == (ViolationRule.OUT_OF_RANGE.value,)


def test_an_unknown_market_does_not_invent_outcome_causes(quote: dict[str, Any]) -> None:
    broken = dict(quote, market="quiniela")

    result = validate_payload(broken, ODDS_UPDATE_SCHEMA)

    assert result.rules == (ViolationRule.VALUE_NOT_ALLOWED.value,)


def test_outcomes_that_are_not_a_list_are_caught(quote: dict[str, Any]) -> None:
    broken = dict(quote, outcomes={"home": 2.1})

    result = validate_payload(broken, ODDS_UPDATE_SCHEMA)

    assert ViolationRule.WRONG_TYPE.value in result.rules


def test_an_unknown_trigger_is_caught(quote: dict[str, Any]) -> None:
    broken = dict(quote, trigger="corazonada")

    result = validate_payload(broken, ODDS_UPDATE_SCHEMA)

    assert result.rules == (ViolationRule.VALUE_NOT_ALLOWED.value,)


###############################################################################
# Tipos equivocados en campos que no son números
###############################################################################


def test_a_number_where_an_identifier_belongs_is_caught(shot: dict[str, Any]) -> None:
    broken = dict(shot, match_id=42)

    assert _rules(broken) == (ViolationRule.WRONG_TYPE.value,)


def test_a_number_where_a_timestamp_belongs_is_caught(shot: dict[str, Any]) -> None:
    broken = dict(shot, event_time=1756234815)

    assert _rules(broken) == (ViolationRule.WRONG_TYPE.value,)


def test_a_string_where_an_integer_belongs_is_caught(shot: dict[str, Any]) -> None:
    broken = dict(shot, attrs=dict(shot["attrs"], period="segundo"))

    assert _rules(broken) == (ViolationRule.WRONG_TYPE.value,)


def test_a_period_outside_the_two_halves_is_caught(shot: dict[str, Any]) -> None:
    broken = dict(shot, attrs=dict(shot["attrs"], period=3))

    assert _rules(broken) == (ViolationRule.OUT_OF_RANGE.value,)


def test_an_outcome_whose_name_is_not_a_string_is_caught(quote: dict[str, Any]) -> None:
    broken = dict(quote, outcomes=[{"outcome": 1, "odds": 2.1}, *quote["outcomes"][1:]])

    result = validate_payload(broken, ODDS_UPDATE_SCHEMA)

    assert ViolationRule.MALFORMED_OUTCOME.value in result.rules


###############################################################################
# Campos opcionales
###############################################################################

#: Un contrato de mentira con un campo opcional. Es el único cambio que la
#: política de versionado admite sin subir la versión, así que conviene tener
#: escrito que el mecanismo lo soporta antes de necesitarlo.
_WITH_OPTIONAL = StreamSchema(
    stream="prueba",
    contract_version="v1",
    envelope=(
        FieldSpec("event_id", FieldKind.STRING),
        FieldSpec("comentario", FieldKind.STRING, required=False),
    ),
)


def test_an_absent_optional_field_does_not_invalidate_the_message() -> None:
    assert validate_payload({"event_id": "x"}, _WITH_OPTIONAL).is_valid


def test_an_optional_field_that_does_arrive_still_has_to_be_well_formed() -> None:
    result = validate_payload({"event_id": "x", "comentario": 7}, _WITH_OPTIONAL)

    assert result.rules == (ViolationRule.WRONG_TYPE.value,)


def test_an_optional_field_is_not_listed_among_the_required_ones() -> None:
    assert _WITH_OPTIONAL.required_field_names() == ("event_id",)
