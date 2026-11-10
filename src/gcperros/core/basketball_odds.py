"""El modelo de mercado del baloncesto: ganador y total de puntos (#90).

Es a ``core/odds.py`` lo que el baloncesto al fútbol. El Poisson sirve para
pocos goles; con unos 160 puntos por partido, la suma de muchas canastas pequeñas
se comporta como una **normal**. Los puntos que faltan por anotar se modelan así:
la diferencia y el total de lo que queda son normales, con media proporcional al
tiempo restante y varianza también proporcional a él.

Que la varianza crezca con el tiempo no es un supuesto cómodo: se midió sobre el
generador (#88). La desviación de la diferencia al descanso es 0,71 veces la
final, y la raíz de un medio es 0,707.

=========================== ========
Medido en 400 partidos       Valor
=========================== ========
Puntos por equipo (40 min)     80,6
Desviación de la diferencia    13,6
Desviación del total           15,8
=========================== ========

No hay empate: si el partido acaba igualado, la prórroga lo decide. Por eso el
mercado de ganador sólo tiene dos resultados, y un empate al final del tiempo
reglamentario vale lo mismo para los dos.

El margen del operador, su conversión a cuotas y su descuento son los mismos del
fútbol (``core/odds.py``): no dependen del deporte.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from gcperros.core import court

#: Versión del modelo. Viaja con cada señal que lo usa, como la del fútbol.
MODEL_VERSION = "basketball-odds-1.0.0"

REGULATION_S = court.REGULATION_PERIODS * court.PERIOD_DURATION_S

#: Puntos esperados por equipo en los 40 minutos. El generador no da ventaja de
#: campo, así que el modelo base tampoco: el sesgo lo pone cada operador.
BASE_POINTS = 80.6

#: Desviación de la diferencia y del total sobre un partido completo.
MARGIN_SD = 13.6
TOTAL_SD = 15.8

#: Por debajo de esta desviación lo que queda ya no cambia nada: el resultado
#: es el del marcador.
_NEGLIGIBLE_SD = 1e-6


@dataclass(frozen=True, slots=True)
class BasketballState:
    """El partido visto desde el mercado: periodo, reloj y marcador."""

    period: int
    clock_s: float
    points_home: int
    points_away: int


def seconds_left(state: BasketballState) -> float:
    """Tiempo de juego que queda: lo del periodo más los cuartos por jugar."""
    pending = max(court.REGULATION_PERIODS - state.period, 0) * court.PERIOD_DURATION_S
    return max(state.clock_s, 0.0) + pending


def remaining_fraction(state: BasketballState) -> float:
    """Proporción de un partido reglamentario que queda por jugar."""
    return seconds_left(state) / REGULATION_S


def point_rates(state: BasketballState, home_strength: float = 1.0) -> tuple[float, float]:
    """Puntos esperados de cada equipo en lo que queda.

    Args:
        state: Periodo, reloj y marcador.
        home_strength: Cómo valora el operador al local, como en el fútbol.
    """
    expected = BASE_POINTS * remaining_fraction(state)
    return expected * home_strength, expected


def _phi(z: float) -> float:
    """Función de distribución de la normal estándar."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def moneyline_probabilities(state: BasketballState, home_strength: float = 1.0) -> dict[str, float]:
    """Probabilidad de que gane cada equipo. Sin empate: lo decide la prórroga."""
    home_rate, away_rate = point_rates(state, home_strength)
    lead = state.points_home - state.points_away
    sd = MARGIN_SD * math.sqrt(remaining_fraction(state))

    if sd < _NEGLIGIBLE_SD:
        # Sin tiempo: gana quien va por delante, y un empate va a la prórroga.
        home = 1.0 if lead > 0 else 0.0 if lead < 0 else 0.5
    else:
        home = _phi((lead + home_rate - away_rate) / sd)
    return {"home": home, "away": 1.0 - home}


def total_points_probabilities(
    state: BasketballState, line: float, home_strength: float = 1.0
) -> dict[str, float]:
    """Probabilidad de que el total de puntos supere o no la línea."""
    home_rate, away_rate = point_rates(state, home_strength)
    scored = state.points_home + state.points_away
    sd = TOTAL_SD * math.sqrt(remaining_fraction(state))

    if sd < _NEGLIGIBLE_SD:
        over = 1.0 if scored > line else 0.0
    else:
        over = 1.0 - _phi((line - scored - home_rate - away_rate) / sd)
    return {"over": over, "under": 1.0 - over}


def opening_line(home_strength: float = 1.0) -> float:
    """La línea de puntos con que abre el mercado: el total esperado, en medio punto.

    Siempre termina en ,5 para que no haya apuestas devueltas: un total entero
    no puede caer justo en la línea.
    """
    expected = BASE_POINTS * (1.0 + home_strength)
    return math.floor(expected) + 0.5
