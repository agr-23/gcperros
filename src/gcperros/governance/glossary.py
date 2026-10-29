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
"""

from __future__ import annotations

from dataclasses import dataclass

from gcperros.core import xg
from gcperros.core.possession import MAX_IN_PLAY_GAP_S, POSSESSION_WINDOW_S
from gcperros.engine.signals import DEFAULT_THRESHOLD
from gcperros.engine.watermark import DEFAULT_ALLOWED_LATENESS_S


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
    """

    key: str
    name: str
    definition: str
    unit: str
    implemented_in: str


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
        f"precio vigente de un operador se separan {DEFAULT_THRESHOLD:g} o más. Al umbral "
        "declarado detecta sobre todo precios que se quedaron viejos tras un gol o una "
        "expulsión, no operadores que valoran distinto."
    ),
    unit="diferencia de probabilidades, con signo",
    implemented_in="gcperros.engine.signals",
)

WATERMARK = Term(
    key="watermark",
    name="Marca de agua",
    definition=(
        "Instante del partido hasta el que el motor da por llegado todo lo que tenía que "
        f"llegar: el evento más tardío visto, menos un margen de {DEFAULT_ALLOWED_LATENESS_S:g}"
        " s. Lo que llega por detrás de ella se descarta y se cuenta."
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

#: El glosario completo, en el orden en que se presenta.
GLOSSARY: tuple[Term, ...] = (
    POSSESSION,
    EXPECTED_GOALS,
    OPERATOR_MARGIN,
    IMPLIED_PROBABILITY,
    DISCREPANCY_SIGNAL,
    WATERMARK,
    LINEAGE,
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
