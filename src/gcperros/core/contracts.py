"""Contratos de datos de los dos flujos de entrada.

Implementa los esquemas que todos los componentes —generadores, motor, cargador
de la capa Raw— acuerdan antes de escribir código, para que nadie invente su
propia interpretación de qué es un evento.

Los dos flujos se versionan por separado, igual que viajan por topics separados:
``match-events`` puede evolucionar sin obligar a los consumidores de
``odds-updates`` a cambiar nada.

Aquí vive únicamente la *forma* de los eventos y su serialización. El mecanismo
de validación y aislamiento de mensajes no conformes es la HU-16 y se implementa
por separado: esto describe los contratos, no los hace cumplir.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, TypeAlias, cast, get_args

MATCH_CONTRACT_VERSION = "v1"
ODDS_CONTRACT_VERSION = "v1"

#: Valor admisible dentro de ``attrs``. El contrato acepta JSON plano.
JsonValue: TypeAlias = str | int | float | bool | list["JsonValue"] | dict[str, "JsonValue"] | None

#: Tipos de evento del flujo. El gol se emite de forma **redundante** junto al
#: tiro que lo produjo (decisión deliberada de la HU-1): el tiro conserva su xG
#: para el modelo y el gol es un hecho de negocio autónomo, que los consumidores
#: pueden contar sin tener que entender la semántica de un remate.
EventType: TypeAlias = Literal["pass", "shot", "goal", "foul", "red_card", "possession_change"]

#: Los mismos valores en tiempo de ejecución, para validarlos al leer un mensaje.
#: Se derivan del propio Literal para que no puedan divergir de él.
EVENT_TYPES: frozenset[str] = frozenset(get_args(EventType))

#: Espacio de nombres fijo para derivar identificadores. Al ser constante, el
#: mismo partido con la misma semilla produce los mismos `event_id`, que es lo
#: que permite comparar dos ejecuciones byte a byte.
_EVENT_NAMESPACE = uuid.UUID("2f5c8a1e-6d4b-5c3a-9e7f-1a2b3c4d5e6f")


def new_event_id(match_id: str, sequence: int) -> str:
    """Deriva un identificador estable a partir del partido y el orden de emisión.

    Se usa UUID v5 en lugar de v4 porque ``uuid4`` es aleatorio y rompería la
    reproducibilidad: dos ejecuciones con la misma semilla generarían el mismo
    partido con identificadores distintos, y la comparación byte a byte de la
    HU-8 dejaría de tener sentido.
    """
    return str(uuid.uuid5(_EVENT_NAMESPACE, f"{match_id}:{sequence}"))


def format_event_time(moment: datetime) -> str:
    """Formatea un instante como ISO-8601 UTC con milisegundos.

    La precisión se fija en milisegundos para que la representación sea estable
    y comparable entre ejecuciones y entre lenguajes.
    """
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


@dataclass(frozen=True, slots=True)
class MatchEvent:
    """Un evento del flujo ``match-events``."""

    event_id: str
    event_time: datetime
    match_id: str
    team: str
    event_type: EventType
    attrs: dict[str, JsonValue]

    def to_dict(self) -> dict[str, JsonValue]:
        """Proyecta el evento a la estructura que viaja por el broker."""
        return {
            "event_id": self.event_id,
            "event_time": format_event_time(self.event_time),
            "match_id": self.match_id,
            "team": self.team,
            "event_type": self.event_type,
            "contract_version": MATCH_CONTRACT_VERSION,
            "attrs": self.attrs,
        }

    def to_json(self) -> str:
        """Serializa el evento como una línea JSON.

        ``sort_keys`` y separadores sin espacios no son cosmética: fijan una
        representación única por evento, de modo que dos ejecuciones con la
        misma semilla produzcan ficheros idénticos byte a byte.
        """
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )


###############################################################################
# Contrato del flujo `odds-updates`
###############################################################################

#: Mercados cubiertos. El identificador viaja en el evento y es la clave por la
#: que se agrupa la capa analítica (particionamiento por tiempo, agrupamiento
#: por partido y mercado).
Market: TypeAlias = Literal["1x2", "over_under_2_5"]

#: Resultados posibles de cada mercado, en orden fijo. El orden es parte del
#: contrato: mantenerlo estable hace que dos ejecuciones serialicen igual.
MARKET_OUTCOMES: dict[Market, tuple[str, ...]] = {
    "1x2": ("home", "draw", "away"),
    "over_under_2_5": ("over", "under"),
}

#: Por qué se publicó la actualización. No existe en un feed comercial: es
#: metadato del generador sintético, y sirve para auditar después si el pipeline
#: reaccionó a los eventos que debía.
OddsTrigger: TypeAlias = Literal["open", "goal", "red_card", "drift", "heartbeat"]

_ODDS_NAMESPACE = uuid.UUID("7b3e9d41-2a68-5f0c-8d17-4e6a9c2b5f83")


def new_odds_event_id(match_id: str, sequence: int) -> str:
    """Deriva el identificador de una actualización de cuotas.

    Usa un espacio de nombres distinto al de los eventos de partido para que un
    flujo no pueda colisionar con el otro: son dos topics independientes y su
    deduplicación es independiente.
    """
    return str(uuid.uuid5(_ODDS_NAMESPACE, f"{match_id}:{sequence}"))


@dataclass(frozen=True, slots=True)
class OddsUpdate:
    """Una actualización de cuotas de un operador sobre un mercado.

    Se publica el mercado completo y no un resultado suelto: las cuotas de un
    mercado solo tienen sentido juntas, porque es su conjunto el que codifica el
    margen del operador. Publicar `home` sin `draw` ni `away` obligaría al
    consumidor a reconstruir el mercado por su cuenta.

    Deliberadamente **no** se publica la probabilidad implícita ni el margen: un
    feed real entrega precios, no probabilidades. Derivarlos —descontando el
    margen, que no es dividir uno entre la cuota— es trabajo del motor (HU-19).
    """

    event_id: str
    event_time: datetime
    match_id: str
    operator: str
    market: Market
    odds: dict[str, float]
    trigger: OddsTrigger

    def to_dict(self) -> dict[str, JsonValue]:
        """Proyecta la actualización a la estructura que viaja por el broker."""
        return {
            "event_id": self.event_id,
            "event_time": format_event_time(self.event_time),
            "match_id": self.match_id,
            "contract_version": ODDS_CONTRACT_VERSION,
            "operator": self.operator,
            "market": self.market,
            "outcomes": [
                {"outcome": outcome, "odds": self.odds[outcome]}
                for outcome in MARKET_OUTCOMES[self.market]
            ],
            "trigger": self.trigger,
        }

    def to_json(self) -> str:
        """Serializa la actualización como una línea JSON estable."""
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )


###############################################################################
# Lectura: del mensaje del broker de vuelta al objeto
###############################################################################


class ContractViolationError(ValueError):
    """Un mensaje no cumple el contrato de su flujo.

    La HU-16 desviará estos mensajes a un repositorio de inválidos con la causa
    registrada. Aquí sólo se detectan y se nombran.
    """


def _require(payload: dict[str, JsonValue], field: str, expected: type) -> object:
    value = payload.get(field)
    if not isinstance(value, expected):
        raise ContractViolationError(f"falta el campo {field} o no es {expected.__name__}")
    return value


def parse_event_time(stamp: str) -> datetime:
    """Interpreta una marca temporal del contrato.

    Raises:
        ContractViolationError: Si no tiene el formato acordado.
    """
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise ContractViolationError(f"marca temporal no conforme: {stamp!r}") from error


def parse_match_event(message: bytes | str) -> MatchEvent:
    """Reconstruye un evento de partido a partir del mensaje publicado.

    Es la vuelta de ``MatchEvent.to_json``. La necesitan el motor, cuando consuma
    del broker, y el cargador de la capa Raw (HU-14).

    Raises:
        ContractViolationError: Si el mensaje no es JSON o le faltan campos.
    """
    try:
        payload = json.loads(message)
    except json.JSONDecodeError as error:
        raise ContractViolationError(f"el mensaje no es JSON válido: {error}") from error

    if not isinstance(payload, dict):
        raise ContractViolationError("el mensaje debe ser un objeto JSON")

    attrs = payload.get("attrs")
    if not isinstance(attrs, dict):
        raise ContractViolationError("falta el objeto attrs")

    event_type = _require(payload, "event_type", str)
    if event_type not in EVENT_TYPES:
        raise ContractViolationError(f"tipo de evento desconocido: {event_type!r}")

    return MatchEvent(
        event_id=str(_require(payload, "event_id", str)),
        event_time=parse_event_time(str(_require(payload, "event_time", str))),
        match_id=str(_require(payload, "match_id", str)),
        team=str(_require(payload, "team", str)),
        # Ya se comprobó contra EVENT_TYPES: el estrechamiento es seguro.
        event_type=cast(EventType, event_type),
        attrs=attrs,
    )


def parse_odds_update(message: bytes | str) -> OddsUpdate:
    """Reconstruye una actualización de cuotas a partir del mensaje publicado.

    Raises:
        ContractViolationError: Si el mensaje no es JSON o le faltan campos.
    """
    try:
        payload = json.loads(message)
    except json.JSONDecodeError as error:
        raise ContractViolationError(f"el mensaje no es JSON válido: {error}") from error

    if not isinstance(payload, dict):
        raise ContractViolationError("el mensaje debe ser un objeto JSON")

    market = _require(payload, "market", str)
    if market not in MARKET_OUTCOMES:
        raise ContractViolationError(f"mercado desconocido: {market!r}")

    outcomes = payload.get("outcomes")
    if not isinstance(outcomes, list):
        raise ContractViolationError("falta la lista de outcomes")

    odds: dict[str, float] = {}
    for entry in outcomes:
        if not isinstance(entry, dict) or "outcome" not in entry or "odds" not in entry:
            raise ContractViolationError("cada outcome necesita nombre y cuota")
        odds[str(entry["outcome"])] = float(str(entry["odds"]))

    if set(odds) != set(MARKET_OUTCOMES[market]):
        raise ContractViolationError(f"el mercado {market} llegó incompleto")

    return OddsUpdate(
        event_id=str(_require(payload, "event_id", str)),
        event_time=parse_event_time(str(_require(payload, "event_time", str))),
        match_id=str(_require(payload, "match_id", str)),
        operator=str(_require(payload, "operator", str)),
        market=market,
        odds=odds,
        trigger=cast(OddsTrigger, _require(payload, "trigger", str)),
    )
