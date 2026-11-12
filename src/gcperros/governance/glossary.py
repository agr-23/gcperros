"""Glosario de negocio: cada término del dominio, definido una sola vez (historia #24).

Hasta ahora cada término se definía donde se usaba: la posesión en el docstring
de ``core/possession.py``, el margen en el de ``core/odds.py``, la señal en el de
``engine/signals.py``. Cada definición era correcta en su sitio y ninguna era
*la* definición, así que dos personas leyendo el mismo campo podían entender
cosas distintas sin que nada lo delatara.

El glosario es dato y no un documento aparte por la misma razón que el contrato
(sección 7 del documento de decisiones): lo que se declara como dato se puede
comprobar. Cada término nombra el módulo que lo implementa, y las pruebas exigen
que ese módulo exista; las cifras que aparecen en una definición —el umbral de la
señal, el margen de la marca de agua— se leen de la constante que el código usa,
no se copian. Una definición que se desfasa del código es peor que no tenerla.

Con el segundo deporte (#97), cada término dice a qué deportes se aplica. Lo
que no depende del deporte —el margen, el linaje— se define una vez para los
dos; lo que sí —la posesión, el xG— tiene su término en cada uno.
"""

from __future__ import annotations

from dataclasses import dataclass

from gcperros.core import basketball_odds, court, expected_points, xg
from gcperros.core.possession import MAX_IN_PLAY_GAP_S, POSSESSION_WINDOW_S
from gcperros.engine.basketball_market import BASKETBALL_THRESHOLD
from gcperros.engine.basketball_state import (
    BASKETBALL_ALLOWED_LATENESS_S,
    BASKETBALL_MAX_IN_PLAY_GAP_S,
)
from gcperros.engine.signals import DEFAULT_THRESHOLD
from gcperros.engine.watermark import DEFAULT_ALLOWED_LATENESS_S

FOOTBALL = "football"
BASKETBALL = "basketball"

#: Los deportes del sistema, con los mismos nombres que ``--sport``.
SPORTS: tuple[str, ...] = (FOOTBALL, BASKETBALL)


@dataclass(frozen=True, slots=True)
class Term:
    """Un término del dominio.

    Attributes:
        key: Identificador estable, el mismo con el que lo nombra el código.
        name: Cómo se dice en el equipo y en las pantallas.
        definition: Qué significa, en una frase que se pueda leer sin el código.
        unit: En qué se expresa. Sin unidad, «0,6» no dice si es una
            probabilidad, una proporción o un número de goles.
        implemented_in: Módulo que lo calcula. Es la referencia cuando la
            definición en prosa no basta.
        sports: Deportes a los que se aplica.
    """

    key: str
    name: str
    definition: str
    unit: str
    implemented_in: str
    sports: tuple[str, ...] = SPORTS


POSSESSION = Term(
    key="possession",
    name="Posesión",
    definition=(
        "Fracción del tiempo de juego en que un equipo tuvo el balón, no cuántas veces "
        f"lo recuperó. Un hueco de más de {MAX_IN_PLAY_GAP_S:g} s entre eventos es juego "
        "detenido y no cuenta para nadie. Se informa acumulada y en una ventana móvil "
        f"de {POSSESSION_WINDOW_S / 60:g} minutos."
    ),
    unit="proporción del tiempo en juego, entre 0 y 1",
    implemented_in="gcperros.core.possession",
    sports=(FOOTBALL,),
)

EXPECTED_GOALS = Term(
    key="xg",
    name="Goles esperados (xG)",
    definition=(
        "Probabilidad de que un remate acabe en gol según su distancia y su ángulo a la "
        f"portería, calculada con el modelo {xg.MODEL_VERSION}. El xG de un equipo es la "
        "suma de la de sus remates: mide la calidad de las ocasiones, no los goles."
    ),
    unit="goles; por remate, una probabilidad entre 0 y 1",
    implemented_in="gcperros.core.xg",
    sports=(FOOTBALL,),
)

OPERATOR_MARGIN = Term(
    key="operator_margin",
    name="Margen del operador (overround)",
    definition=(
        "Lo que la suma de los inversos de las cuotas de un mercado excede de 1. Es la "
        "comisión del operador, repartida entre todos los resultados."
    ),
    unit="proporción; 1,06 es un margen del 6 %",
    implemented_in="gcperros.core.odds",
)

IMPLIED_PROBABILITY = Term(
    key="implied_probability",
    name="Probabilidad implícita",
    definition=(
        "La probabilidad que una cuota da a un resultado, una vez descontado el margen "
        "del operador. No es 1 / cuota: eso es la probabilidad inflada por el margen."
    ),
    unit="probabilidad entre 0 y 1; las de un mercado suman 1",
    implemented_in="gcperros.core.odds",
)

DISCREPANCY_SIGNAL = Term(
    key="discrepancy_signal",
    name="Señal de discrepancia",
    definition=(
        "Aviso de que la probabilidad del modelo propio y la probabilidad implícita del "
        f"precio vigente de un operador se separan {DEFAULT_THRESHOLD:g} o más en fútbol y "
        f"{BASKETBALL_THRESHOLD:g} o más en baloncesto, cada umbral elegido con la misma "
        "regla. Detecta sobre todo precios que se quedaron viejos tras un gol, una expulsión "
        "o una canasta, no operadores que valoran distinto."
    ),
    unit="diferencia de probabilidades, con signo",
    implemented_in="gcperros.engine.signals",
)

WATERMARK = Term(
    key="watermark",
    name="Marca de agua",
    definition=(
        "Instante del partido hasta el que el motor da por llegado todo lo que tenía que "
        "llegar: el evento más tardío visto, menos un margen de "
        f"{DEFAULT_ALLOWED_LATENESS_S:g} s en fútbol y {BASKETBALL_ALLOWED_LATENESS_S:g} s en "
        "baloncesto. Lo que llega por detrás de ella se descarta y se cuenta."
    ),
    unit="instante del partido",
    implemented_in="gcperros.engine.watermark",
)

LINEAGE = Term(
    key="lineage",
    name="Linaje",
    definition=(
        "Los eventos que formaron un número, plegados en una huella que se puede "
        "volver a calcular desde los flujos crudos y comparar."
    ),
    unit="huella SHA-256 y número de eventos",
    implemented_in="gcperros.core.lineage",
)

BASKETBALL_POSSESSION = Term(
    key="basketball_possession",
    name="Posesión en baloncesto",
    definition=(
        "Fracción del tiempo de juego en que un equipo tuvo el balón, como en fútbol, con "
        f"otro corte: un hueco de más de {BASKETBALL_MAX_IN_PLAY_GAP_S:g} s entre eventos es "
        f"juego detenido, porque ninguna posesión viva supera el reloj de {court.SHOT_CLOCK_S}"
        " s. Cuántas veces tuvo el balón es otra cosa: el ritmo."
    ),
    unit="proporción del tiempo en juego, entre 0 y 1",
    implemented_in="gcperros.engine.basketball_state",
    sports=(BASKETBALL,),
)

EXPECTED_POINTS = Term(
    key="expected_points",
    name="Puntos esperados",
    definition=(
        "Lo que vale de media un tiro: su valor, 2 o 3, por la probabilidad de anotarlo "
        f"según su distancia al aro, con el modelo {expected_points.MODEL_VERSION}. Un tiro "
        f"libre vale 1 y entra con probabilidad {expected_points.FREE_THROW_PROBABILITY:g}. "
        "Los de un equipo son la suma: el xG del baloncesto."
    ),
    unit="puntos; por tiro, entre 0 y 3",
    implemented_in="gcperros.core.expected_points",
    sports=(BASKETBALL,),
)

PACE = Term(
    key="pace",
    name="Ritmo",
    definition=(
        "Cuántas posesiones tiene un equipo en un partido: cuántas veces tuvo el balón, no "
        f"cuánto tiempo. El reglamentario son {court.REGULATION_PERIODS} cuartos de "
        f"{court.PERIOD_DURATION_S // 60} minutos; con prórroga hay más posesiones."
    ),
    unit="posesiones por partido",
    implemented_in="gcperros.core.basketball_stats",
    sports=(BASKETBALL,),
)

MONEYLINE = Term(
    key="moneyline",
    name="Ganador sin empate",
    definition=(
        "Mercado de dos resultados, local o visitante. No hay empate porque la prórroga "
        f"decide: su probabilidad sale del modelo {basketball_odds.MODEL_VERSION}."
    ),
    unit="probabilidad entre 0 y 1; las dos suman 1",
    implemented_in="gcperros.core.basketball_odds",
    sports=(BASKETBALL,),
)

TOTAL_POINTS = Term(
    key="total_points",
    name="Total de puntos",
    definition=(
        "Mercado de si los dos equipos sumarán más o menos puntos que la línea que trae la "
        "propia cuota. Una cuota de este mercado sin línea incumple el contrato."
    ),
    unit="puntos de los dos equipos; la probabilidad, entre 0 y 1",
    implemented_in="gcperros.core.basketball_odds",
    sports=(BASKETBALL,),
)

#: El glosario completo, en el orden en que se presenta.
GLOSSARY: tuple[Term, ...] = (
    POSSESSION,
    EXPECTED_GOALS,
    OPERATOR_MARGIN,
    IMPLIED_PROBABILITY,
    DISCREPANCY_SIGNAL,
    WATERMARK,
    LINEAGE,
    BASKETBALL_POSSESSION,
    EXPECTED_POINTS,
    PACE,
    MONEYLINE,
    TOTAL_POINTS,
)


def term(key: str) -> Term:
    """Busca un término por su identificador.

    Raises:
        KeyError: Si el término no está en el glosario. Usar un término sin
            definir es justo lo que el glosario existe para impedir.
    """
    for entry in GLOSSARY:
        if entry.key == key:
            return entry
    raise KeyError(f"{key!r} no está en el glosario")
