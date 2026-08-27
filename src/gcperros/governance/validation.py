"""Comprobación de un mensaje contra el esquema de su flujo (HU-16).

Juzga mensajes de uno en uno, que es lo único que se puede hacer en la frontera:
decidir si un mensaje merece cómputo antes de gastárselo.

Dos propiedades que no son casuales:

**Se recogen todas las violaciones, no la primera.** Un rechazo que solo informa
del primer problema obliga a quien produce el mensaje a reenviarlo tantas veces
como defectos tenga, descubriéndolos de uno en uno. Con el mensaje delante, la
frontera ya sabe todo lo que está mal: decirlo entero cuesta lo mismo.

**Una violación por campo, todos los campos.** Un campo que está vacío tampoco
está entre los valores admitidos, y reportar las dos cosas no añade información:
la primera causa ya explica qué hay que arreglar. Lo que sí importa es que no se
oculte ningún campo defectuoso detrás de otro.

Un mensaje ilegible —que no es JSON, o que ni siquiera es UTF-8— no levanta
excepción: se convierte en una violación como cualquier otra. Que la frontera se
caiga ante el primer byte corrupto sería exactamente el fallo que existe para
evitar.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypeAlias

from gcperros.core.contracts import EVENT_TIME_FORMAT, JsonValue
from gcperros.core.schema import FieldKind, FieldSpec, MarketOutcomesSpec, StreamSchema

#: Nombre con el que se reporta una violación del mensaje entero, cuando no se
#: puede atribuir a ningún campo porque el mensaje no llegó a leerse.
WHOLE_MESSAGE = "<mensaje>"


class ViolationRule(StrEnum):
    """Motivos por los que un mensaje puede ser rechazado.

    Son un conjunto cerrado y estable a propósito: el marco de calidad (HU-17)
    los agrega por motivo, y un motivo redactado libremente en cada sitio no se
    podría contar. La causa legible acompaña al motivo, no lo sustituye.
    """

    MALFORMED_JSON = "malformed_json"
    NOT_AN_OBJECT = "not_an_object"
    MISSING_FIELD = "missing_field"
    WRONG_TYPE = "wrong_type"
    EMPTY_STRING = "empty_string"
    BAD_TIMESTAMP = "bad_timestamp"
    VALUE_NOT_ALLOWED = "value_not_allowed"
    OUT_OF_RANGE = "out_of_range"
    MALFORMED_OUTCOME = "malformed_outcome"
    MARKET_INCOMPLETE = "market_incomplete"

    #: El esquema aprobó el mensaje pero el lector no pudo construir el objeto.
    #: No debería ocurrir nunca: si ocurre, el esquema y el lector discrepan y
    #: el defecto es del proyecto, no del productor. Se registra como dato en
    #: lugar de romper el proceso, porque un motor que se cae ante un mensaje
    #: que él mismo aprobó es peor que uno que lo aparta y sigue.
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class Violation:
    """Un incumplimiento concreto del contrato."""

    field: str
    rule: ViolationRule
    detail: str

    def describe(self) -> str:
        """Redacta la causa tal como queda archivada en el repositorio."""
        return f"{self.field}: {self.rule.value} — {self.detail}"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Veredicto sobre un mensaje.

    ``payload`` viene relleno solo cuando el mensaje se pudo leer, de modo que
    quien valida no tiene que volver a interpretarlo para usarlo.
    """

    stream: str
    contract_version: str
    violations: tuple[Violation, ...]
    payload: dict[str, JsonValue] | None = None

    @property
    def is_valid(self) -> bool:
        """Indica si el mensaje puede pasar la frontera."""
        return not self.violations

    @property
    def rules(self) -> tuple[str, ...]:
        """Motivos de rechazo, en orden de aparición y sin repetir."""
        seen: dict[str, None] = {}
        for violation in self.violations:
            seen.setdefault(violation.rule.value, None)
        return tuple(seen)

    @property
    def causes(self) -> tuple[str, ...]:
        """Causas legibles, una por violación."""
        return tuple(violation.describe() for violation in self.violations)


###############################################################################
# Comprobación de un campo
###############################################################################

_Checker: TypeAlias = Callable[[str, object, FieldSpec], "Violation | None"]


def _wrong_type(name: str, value: object, expected: FieldKind) -> Violation:
    return Violation(
        name,
        ViolationRule.WRONG_TYPE,
        f"se esperaba {expected.value} y llegó {type(value).__name__}",
    )


def _as_number(value: object) -> float | None:
    """Lee un valor numérico del mensaje, o ``None`` si no lo es.

    Los booleanos se rechazan explícitamente porque ``bool`` es subclase de
    ``int`` en Python y ``True`` pasaría por número. Es el mismo cuidado que
    toma ``core.stats.as_float``, y por el mismo motivo: un agregador que sume
    ``True`` como 1 produce un indicador plausible pero falso.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _check_string(name: str, value: object, spec: FieldSpec) -> Violation | None:
    if not isinstance(value, str):
        return _wrong_type(name, value, spec.kind)
    if not value:
        return Violation(name, ViolationRule.EMPTY_STRING, "la cadena está vacía")
    if spec.allowed is not None and value not in spec.allowed:
        admitted = ", ".join(sorted(spec.allowed))
        return Violation(
            name,
            ViolationRule.VALUE_NOT_ALLOWED,
            f"{value!r} no está entre los valores admitidos ({admitted})",
        )
    return None


def _check_timestamp(name: str, value: object, spec: FieldSpec) -> Violation | None:
    if not isinstance(value, str):
        return _wrong_type(name, value, spec.kind)
    try:
        datetime.strptime(value, EVENT_TIME_FORMAT)
    except ValueError:
        return Violation(
            name,
            ViolationRule.BAD_TIMESTAMP,
            f"{value!r} no sigue el formato {EVENT_TIME_FORMAT}",
        )
    return None


def _check_bounds(name: str, value: float, spec: FieldSpec) -> Violation | None:
    if spec.minimum is not None and value < spec.minimum:
        return Violation(
            name,
            ViolationRule.OUT_OF_RANGE,
            f"{value} es menor que el mínimo {spec.minimum}",
        )
    if spec.maximum is not None and value > spec.maximum:
        return Violation(
            name,
            ViolationRule.OUT_OF_RANGE,
            f"{value} supera el máximo {spec.maximum}",
        )
    return None


def _check_integer(name: str, value: object, spec: FieldSpec) -> Violation | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return _wrong_type(name, value, spec.kind)
    return _check_bounds(name, value, spec)


def _check_number(name: str, value: object, spec: FieldSpec) -> Violation | None:
    number = _as_number(value)
    if number is None:
        return _wrong_type(name, value, spec.kind)
    return _check_bounds(name, number, spec)


def _check_boolean(name: str, value: object, spec: FieldSpec) -> Violation | None:
    return None if isinstance(value, bool) else _wrong_type(name, value, spec.kind)


def _check_object(name: str, value: object, spec: FieldSpec) -> Violation | None:
    return None if isinstance(value, dict) else _wrong_type(name, value, spec.kind)


def _check_array(name: str, value: object, spec: FieldSpec) -> Violation | None:
    return None if isinstance(value, list) else _wrong_type(name, value, spec.kind)


_CHECKERS: Mapping[FieldKind, _Checker] = {
    FieldKind.STRING: _check_string,
    FieldKind.TIMESTAMP: _check_timestamp,
    FieldKind.INTEGER: _check_integer,
    FieldKind.NUMBER: _check_number,
    FieldKind.BOOLEAN: _check_boolean,
    FieldKind.OBJECT: _check_object,
    FieldKind.ARRAY: _check_array,
}


def _collect_fields(
    container: Mapping[str, object],
    specs: Sequence[FieldSpec],
    prefix: str,
    violations: list[Violation],
) -> None:
    """Comprueba un grupo de campos y acumula lo que encuentre."""
    for spec in specs:
        name = f"{prefix}{spec.name}"
        if spec.name not in container:
            if spec.required:
                violations.append(
                    Violation(name, ViolationRule.MISSING_FIELD, "campo obligatorio ausente")
                )
            continue

        found = _CHECKERS[spec.kind](name, container[spec.name], spec)
        if found is not None:
            violations.append(found)


def _collect_variant(
    payload: Mapping[str, object], schema: StreamSchema, violations: list[Violation]
) -> None:
    """Comprueba los atributos que exige el tipo concreto del mensaje."""
    if schema.discriminator is None or schema.variant_container is None:
        return

    variant = payload.get(schema.discriminator)
    if not isinstance(variant, str) or variant not in schema.variants:
        # El sobre ya reportó que el discriminador no sirve. Sin él no se puede
        # decidir qué atributos exigir, y adivinarlos produciría causas falsas.
        return

    container = payload.get(schema.variant_container)
    if not isinstance(container, dict):
        return

    _collect_fields(container, schema.variants[variant], f"{schema.variant_container}.", violations)


def _collect_market(
    payload: Mapping[str, object], spec: MarketOutcomesSpec, violations: list[Violation]
) -> None:
    """Comprueba que el mercado viaje completo y con precios publicables."""
    market = payload.get(spec.discriminator)
    entries = payload.get(spec.container)
    if not isinstance(market, str) or market not in spec.outcomes_by_value:
        return
    if not isinstance(entries, list):
        return

    labels: list[str] = []
    for index, entry in enumerate(entries):
        where = f"{spec.container}[{index}]"
        if not isinstance(entry, dict) or spec.label_field not in entry:
            violations.append(
                Violation(where, ViolationRule.MALFORMED_OUTCOME, "falta el nombre del resultado")
            )
            continue

        label = entry[spec.label_field]
        if not isinstance(label, str):
            violations.append(
                Violation(where, ViolationRule.MALFORMED_OUTCOME, "el nombre no es una cadena")
            )
            continue
        labels.append(label)

        price = _as_number(entry.get(spec.price_field))
        if price is None:
            violations.append(
                Violation(
                    f"{where}.{spec.price_field}",
                    ViolationRule.MALFORMED_OUTCOME,
                    f"la cuota de {label!r} no es un número",
                )
            )
        elif not spec.minimum_price <= price <= spec.maximum_price:
            violations.append(
                Violation(
                    f"{where}.{spec.price_field}",
                    ViolationRule.OUT_OF_RANGE,
                    f"la cuota de {label!r} queda fuera de "
                    f"[{spec.minimum_price}, {spec.maximum_price}]",
                )
            )

    expected = spec.outcomes_by_value[market]
    # Se comparan listas ordenadas y no conjuntos: un conjunto daría por bueno
    # un mercado con el mismo resultado repetido dos veces y otro ausente.
    if sorted(labels) != sorted(expected):
        violations.append(
            Violation(
                spec.container,
                ViolationRule.MARKET_INCOMPLETE,
                f"el mercado {market} exige {list(expected)} y llegó {labels}",
            )
        )


###############################################################################
# API pública
###############################################################################


def validate_payload(payload: object, schema: StreamSchema) -> ValidationResult:
    """Juzga un mensaje ya interpretado contra el contrato de su flujo.

    Args:
        payload: Estructura leída del mensaje.
        schema: Contrato contra el que se juzga.

    Returns:
        El veredicto, con todas las violaciones encontradas en orden estable.
    """
    if not isinstance(payload, dict):
        return ValidationResult(
            stream=schema.stream,
            contract_version=schema.contract_version,
            violations=(
                Violation(
                    WHOLE_MESSAGE,
                    ViolationRule.NOT_AN_OBJECT,
                    f"se esperaba un objeto JSON y llegó {type(payload).__name__}",
                ),
            ),
        )

    violations: list[Violation] = []
    _collect_fields(payload, schema.envelope, "", violations)
    _collect_variant(payload, schema, violations)
    if schema.market_outcomes is not None:
        _collect_market(payload, schema.market_outcomes, violations)

    return ValidationResult(
        stream=schema.stream,
        contract_version=schema.contract_version,
        violations=tuple(violations),
        payload=payload,
    )


def validate_message(message: bytes | str, schema: StreamSchema) -> ValidationResult:
    """Juzga un mensaje tal como salió del broker.

    Args:
        message: Carga útil recibida, sin interpretar.
        schema: Contrato contra el que se juzga.

    Returns:
        El veredicto. Un mensaje ilegible sale como una violación más, no como
        una excepción: la frontera no puede permitirse caerse ante basura.
    """
    try:
        payload = json.loads(message)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        return ValidationResult(
            stream=schema.stream,
            contract_version=schema.contract_version,
            violations=(Violation(WHOLE_MESSAGE, ViolationRule.MALFORMED_JSON, str(error)),),
        )
    return validate_payload(payload, schema)
