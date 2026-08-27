"""Esquema formal de los dos contratos de datos (HU-16).

``contracts.py`` describe la *forma* de los eventos y sabe serializarlos. Este
módulo declara qué hace que un mensaje sea **conforme**: qué campos son
obligatorios, de qué tipo son y qué valores admiten.

Se declara como dato y no como una cadena de comprobaciones porque el mismo
esquema tiene que servir para tres trabajos distintos: rechazar en la frontera
(HU-16), medir completitud (HU-17) y, cuando exista la capa Raw (HU-14),
derivar la tabla de destino. Tres implementaciones del mismo contrato acabarían
divergiendo; una única declaración no puede.

El vocabulario es deliberadamente corto —tipo, obligatoriedad, conjunto de
valores admisibles y rango— porque un esquema que puede expresar cualquier cosa
deja de ser legible, y este fichero es el documento que el equipo lee para saber
qué promete el proyecto a sus consumidores.

Lo que **no** se valida aquí, y es una decisión, no un olvido: la coherencia
entre eventos. Que un ``goal`` venga acompañado de su ``shot``, o que el reloj
avance, son propiedades del flujo completo, no de un mensaje suelto. La frontera
juzga mensajes de uno en uno, que es lo único que puede hacer antes de gastar
cómputo; el resto es trabajo del marco de calidad (HU-17).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from gcperros.core import pitch
from gcperros.core.contracts import (
    EVENT_TYPES,
    MARKET_OUTCOMES,
    MATCH_CONTRACT_VERSION,
    ODDS_CONTRACT_VERSION,
    ODDS_TRIGGERS,
    POSSESSION_REASONS,
)
from gcperros.core.odds import MAX_ODDS, MIN_ODDS

#: Identificadores de los dos flujos. Coinciden con los nombres de los topics
#: que declara la infraestructura y que usa el publicador: el contrato, el canal
#: y el código nombran lo mismo de la misma forma.
MATCH_EVENTS_STREAM = "match-events"
ODDS_UPDATES_STREAM = "odds-updates"

#: Periodos reglamentarios. Se declaran aquí y no se importan del generador
#: porque son valores del contrato: el consumidor los necesita sin tener acceso
#: a la implementación que los produjo.
FIRST_PERIOD = 1
LAST_PERIOD = 2

#: Jugadores en el campo. El mínimo es cero y no siete —el número con el que el
#: reglamento da un partido por terminado— porque el contrato describe lo que el
#: mensaje puede decir, no lo que el árbitro haría al respecto.
MIN_PLAYERS_ON_PITCH = 0
MAX_PLAYERS_ON_PITCH = 11


class FieldKind(StrEnum):
    """Tipos admitidos por el esquema.

    ``TIMESTAMP`` existe aparte de ``STRING`` porque el formato de la marca
    temporal es parte del contrato: una cadena cualquiera en ``event_time``
    rompe a todos los consumidores aguas abajo, y detectarlo en la frontera
    cuesta una comprobación.
    """

    STRING = "string"
    TIMESTAMP = "timestamp"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Declaración de un campo del contrato.

    Attributes:
        name: Nombre del campo tal como viaja en el mensaje.
        kind: Tipo esperado.
        required: Si su ausencia invalida el mensaje. Un campo opcional nuevo es
            el único cambio que no obliga a versionar el contrato.
        allowed: Conjunto cerrado de valores admisibles, si lo hay.
        minimum: Cota inferior inclusiva, para los tipos numéricos.
        maximum: Cota superior inclusiva, para los tipos numéricos.
    """

    name: str
    kind: FieldKind
    required: bool = True
    allowed: frozenset[str] | None = None
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True, slots=True)
class MarketOutcomesSpec:
    """Declaración de la lista de resultados de un mercado de cuotas.

    Se declara aparte de ``FieldSpec`` en lugar de estirar su vocabulario para
    describirla, porque no es un campo más: es una estructura cuyo contenido
    válido **depende de otro campo del mensaje**. El mercado ``1x2`` exige
    exactamente ``home``, ``draw`` y ``away``; ``over_under_2_5`` exige otros
    dos. Un mercado incompleto no es un mercado con un dato de menos, es un
    mercado que no se puede interpretar: sin todos sus resultados no se puede
    calcular el margen del operador, y sin margen la probabilidad implícita sale
    sesgada.

    Attributes:
        container: Campo que transporta la lista.
        discriminator: Campo que decide qué resultados son obligatorios.
        outcomes_by_value: Resultados exigidos por cada valor del discriminador.
        label_field: Nombre del resultado dentro de cada entrada.
        price_field: Cuota dentro de cada entrada.
        minimum_price: Cuota mínima publicable.
        maximum_price: Cuota máxima publicable.
    """

    container: str
    discriminator: str
    outcomes_by_value: Mapping[str, tuple[str, ...]]
    label_field: str
    price_field: str
    minimum_price: float
    maximum_price: float


@dataclass(frozen=True, slots=True)
class StreamSchema:
    """Contrato completo de un flujo.

    Un mensaje conforme tiene todos los campos de ``envelope`` y, si el flujo
    define variantes, los campos que su discriminador exige dentro del
    contenedor. El sobre es lo que **todo** mensaje del flujo comparte y lo que
    permite enrutarlo, auditarlo y particionarlo sin abrir su carga útil.

    Attributes:
        stream: Identificador del flujo.
        contract_version: Versión que este esquema describe.
        envelope: Campos de nivel superior, comunes a todo el flujo.
        discriminator: Campo del sobre que decide la variante, si la hay.
        variant_container: Campo que transporta los atributos de la variante.
        variants: Campos exigidos por cada valor del discriminador.
        market_outcomes: Declaración de la lista de resultados, si el flujo la
            tiene.
    """

    stream: str
    contract_version: str
    envelope: tuple[FieldSpec, ...]
    discriminator: str | None = None
    variant_container: str | None = None
    variants: Mapping[str, tuple[FieldSpec, ...]] = field(default_factory=dict)
    market_outcomes: MarketOutcomesSpec | None = None

    def required_field_names(self, variant: str | None = None) -> tuple[str, ...]:
        """Campos obligatorios del sobre y, si se indica, de una variante.

        Los de la variante se devuelven con el prefijo de su contenedor
        (``attrs.xg``), que es como los nombran los rechazos y como los medirá
        el marco de calidad (HU-17).

        Args:
            variant: Valor del discriminador cuya variante se quiere incluir.

        Returns:
            Nombres en el mismo orden en que están declarados.
        """
        names = [spec.name for spec in self.envelope if spec.required]

        if variant is None or self.variant_container is None:
            return tuple(names)

        names.extend(
            f"{self.variant_container}.{spec.name}"
            for spec in self.variants.get(variant, ())
            if spec.required
        )
        return tuple(names)


###############################################################################
# Piezas repetidas
#
# Las coordenadas, las probabilidades y los identificadores de equipo aparecen
# en casi todos los eventos. Se construyen con estas ayudas para que la cota de
# un campo se declare una vez: si el campo se ensancha, se ensancha en todas
# partes a la vez.
###############################################################################


def _length_coordinate(name: str) -> FieldSpec:
    return FieldSpec(name, FieldKind.NUMBER, minimum=0.0, maximum=pitch.LENGTH)


def _width_coordinate(name: str) -> FieldSpec:
    return FieldSpec(name, FieldKind.NUMBER, minimum=0.0, maximum=pitch.WIDTH)


def _probability(name: str) -> FieldSpec:
    return FieldSpec(name, FieldKind.NUMBER, minimum=0.0, maximum=1.0)


def _team_reference(name: str) -> FieldSpec:
    return FieldSpec(name, FieldKind.STRING)


_PERIOD = FieldSpec(
    "period",
    FieldKind.INTEGER,
    minimum=FIRST_PERIOD,
    maximum=LAST_PERIOD,
)


###############################################################################
# Flujo `match-events`
###############################################################################

#: Campos que comparten todos los eventos del partido. Son los que permiten
#: deduplicar, ordenar y particionar sin abrir `attrs`, que es exactamente el
#: motivo por el que están en el sobre y no dentro.
MATCH_ENVELOPE: tuple[FieldSpec, ...] = (
    FieldSpec("event_id", FieldKind.STRING),
    FieldSpec("event_time", FieldKind.TIMESTAMP),
    FieldSpec("match_id", FieldKind.STRING),
    FieldSpec("team", FieldKind.STRING),
    FieldSpec("event_type", FieldKind.STRING, allowed=EVENT_TYPES),
    FieldSpec("contract_version", FieldKind.STRING, allowed=frozenset({MATCH_CONTRACT_VERSION})),
    FieldSpec("attrs", FieldKind.OBJECT),
)

#: Atributos exigidos por cada tipo de evento. Es la parte que hoy no se
#: comprobaba: un `shot` sin `xg` atravesaba el lector sin protestar y reventaba
#: más tarde, al agregarlo, que es precisamente gastar cómputo en basura.
MATCH_VARIANTS: Mapping[str, tuple[FieldSpec, ...]] = {
    "pass": (
        _length_coordinate("start_x"),
        _width_coordinate("start_y"),
        _length_coordinate("end_x"),
        _width_coordinate("end_y"),
        FieldSpec("completed", FieldKind.BOOLEAN),
        FieldSpec("left_the_field", FieldKind.BOOLEAN),
        _probability("completion_probability"),
        _PERIOD,
    ),
    "shot": (
        _length_coordinate("x"),
        _width_coordinate("y"),
        _probability("xg"),
        FieldSpec("is_goal", FieldKind.BOOLEAN),
        _PERIOD,
    ),
    "goal": (
        _length_coordinate("x"),
        _width_coordinate("y"),
        _probability("xg"),
        _PERIOD,
    ),
    "foul": (
        _length_coordinate("x"),
        _width_coordinate("y"),
        _team_reference("against_team"),
        _PERIOD,
    ),
    "red_card": (
        _length_coordinate("x"),
        _width_coordinate("y"),
        FieldSpec(
            "players_remaining",
            FieldKind.INTEGER,
            minimum=MIN_PLAYERS_ON_PITCH,
            maximum=MAX_PLAYERS_ON_PITCH,
        ),
        _PERIOD,
    ),
    "possession_change": (
        _team_reference("from_team"),
        _team_reference("to_team"),
        FieldSpec("reason", FieldKind.STRING, allowed=POSSESSION_REASONS),
        _length_coordinate("start_x"),
        _width_coordinate("start_y"),
        _PERIOD,
    ),
}

MATCH_EVENT_SCHEMA = StreamSchema(
    stream=MATCH_EVENTS_STREAM,
    contract_version=MATCH_CONTRACT_VERSION,
    envelope=MATCH_ENVELOPE,
    discriminator="event_type",
    variant_container="attrs",
    variants=MATCH_VARIANTS,
)


###############################################################################
# Flujo `odds-updates`
###############################################################################

ODDS_ENVELOPE: tuple[FieldSpec, ...] = (
    FieldSpec("event_id", FieldKind.STRING),
    FieldSpec("event_time", FieldKind.TIMESTAMP),
    FieldSpec("match_id", FieldKind.STRING),
    FieldSpec("contract_version", FieldKind.STRING, allowed=frozenset({ODDS_CONTRACT_VERSION})),
    FieldSpec("operator", FieldKind.STRING),
    FieldSpec("market", FieldKind.STRING, allowed=frozenset(MARKET_OUTCOMES)),
    FieldSpec("outcomes", FieldKind.ARRAY),
    FieldSpec("trigger", FieldKind.STRING, allowed=ODDS_TRIGGERS),
)

# `MARKET_OUTCOMES` indexa por el `Literal` de mercados y el esquema indexa por
# cadena, porque juzga lo que llegó y todavía no sabe si es un mercado válido.
# La conversión ensancha la clave sin duplicar la tabla.
_OUTCOMES_BY_MARKET: Mapping[str, tuple[str, ...]] = {
    str(market): outcomes for market, outcomes in MARKET_OUTCOMES.items()
}

ODDS_UPDATE_SCHEMA = StreamSchema(
    stream=ODDS_UPDATES_STREAM,
    contract_version=ODDS_CONTRACT_VERSION,
    envelope=ODDS_ENVELOPE,
    market_outcomes=MarketOutcomesSpec(
        container="outcomes",
        discriminator="market",
        outcomes_by_value=_OUTCOMES_BY_MARKET,
        label_field="outcome",
        price_field="odds",
        minimum_price=MIN_ODDS,
        maximum_price=MAX_ODDS,
    ),
)


#: Los dos contratos, indexados por flujo. Es lo que consulta la frontera para
#: saber contra qué juzgar un mensaje según el topic del que salió.
SCHEMAS: Mapping[str, StreamSchema] = {
    MATCH_EVENTS_STREAM: MATCH_EVENT_SCHEMA,
    ODDS_UPDATES_STREAM: ODDS_UPDATE_SCHEMA,
}
