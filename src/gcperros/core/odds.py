"""Conversión entre estado del partido, probabilidades y cuotas decimales.

Este módulo es a la HU-9 lo que ``xg.py`` es a la HU-8: la pieza que comparten
el generador y el motor. El generador la usa para fabricar precios plausibles;
el motor la usará (HU-19) para recorrer el camino inverso —de la cuota publicada
a la probabilidad implícita— y contrastarla contra su propio modelo.

El modelo de resultado
----------------------
Los goles que quedan por marcar se modelan como dos Poisson independientes, una
por equipo, con intensidad proporcional al tiempo que resta. Es el modelo clásico
del dominio y tiene la propiedad que necesitamos: reacciona a la vez al marcador,
al reloj y a las expulsiones. Un 0-0 al minuto 10 y un 0-0 al minuto 85 son el
mismo marcador y probabilidades de victoria muy distintas.

Sobre el margen del operador
----------------------------
Las cuotas publicadas **no** son el inverso de la probabilidad. El operador
reparte su margen sobre todos los resultados, de modo que la suma de los
inversos pasa de 1: ese exceso es el *overround*. Calcular la probabilidad
implícita como ``1 / cuota`` es el error que la HU-19 debe evitar explícitamente,
y por eso este módulo expone las dos operaciones por separado.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

FULL_TIME_MINUTES = 90.0

# Goles esperados por partido completo. El local marca más: la ventaja de campo
# es uno de los efectos mejor documentados del fútbol.
BASE_GOALS_HOME = 1.50
BASE_GOALS_AWAY = 1.20

# Efecto de una expulsión sobre la intensidad de gol. Jugar con uno menos reduce
# la propia y aumenta la del rival; con dos expulsados el efecto se compone.
RED_CARD_OWN_MULTIPLIER = 0.70
RED_CARD_RIVAL_MULTIPLIER = 1.25

# Truncamiento de la Poisson. La probabilidad de que un equipo marque más de
# ocho goles en lo que resta es despreciable frente al redondeo de la cuota.
MAX_GOALS = 8

# Límites de precio. Ningún operador publica cuotas fuera de este rango: por
# debajo no compensa el riesgo y por encima el mercado se considera cerrado.
MIN_ODDS = 1.01
MAX_ODDS = 200.0
ODDS_DECIMALS = 2

OVER_UNDER_LINE = 2.5


@dataclass(frozen=True, slots=True)
class MatchState:
    """Estado del partido en un instante, visto desde el mercado."""

    minute: float
    goals_home: int
    goals_away: int
    red_cards_home: int = 0
    red_cards_away: int = 0


def _poisson_pmf(k: int, rate: float) -> float:
    """Probabilidad de observar exactamente ``k`` sucesos con intensidad ``rate``."""
    if rate <= 0.0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-rate) * rate**k / math.factorial(k)


def remaining_fraction(minute: float) -> float:
    """Proporción del partido que queda por jugar, en ``[0, 1]``."""
    return min(max((FULL_TIME_MINUTES - minute) / FULL_TIME_MINUTES, 0.0), 1.0)


def scoring_rates(state: MatchState, home_strength: float = 1.0) -> tuple[float, float]:
    """Intensidad de gol de cada equipo para lo que resta de partido.

    Args:
        state: Marcador, minuto y expulsiones.
        home_strength: Sesgo del operador sobre la fuerza del local. Cada casa
            valora los equipos algo distinto, y de ahí nacen las discrepancias
            entre mercados que el sistema busca detectar.

    Returns:
        Par ``(intensidad local, intensidad visitante)``.
    """
    share = remaining_fraction(state.minute)

    home = BASE_GOALS_HOME * share * home_strength
    away = BASE_GOALS_AWAY * share

    home *= RED_CARD_OWN_MULTIPLIER**state.red_cards_home
    home *= RED_CARD_RIVAL_MULTIPLIER**state.red_cards_away
    away *= RED_CARD_OWN_MULTIPLIER**state.red_cards_away
    away *= RED_CARD_RIVAL_MULTIPLIER**state.red_cards_home

    return home, away


def _remaining_goal_grid(state: MatchState, home_strength: float) -> list[list[float]]:
    """Distribución conjunta de los goles que aún se marcarán."""
    rate_home, rate_away = scoring_rates(state, home_strength)
    home_pmf = [_poisson_pmf(i, rate_home) for i in range(MAX_GOALS + 1)]
    away_pmf = [_poisson_pmf(j, rate_away) for j in range(MAX_GOALS + 1)]
    return [[home * away for away in away_pmf] for home in home_pmf]


def _normalise(probabilities: dict[str, float]) -> dict[str, float]:
    """Reescala a suma uno, compensando la cola perdida por el truncamiento."""
    total = sum(probabilities.values())
    if total <= 0.0:
        share = 1.0 / len(probabilities)
        return dict.fromkeys(probabilities, share)
    return {key: value / total for key, value in probabilities.items()}


def match_result_probabilities(state: MatchState, home_strength: float = 1.0) -> dict[str, float]:
    """Probabilidad real de cada resultado del mercado 1X2."""
    grid = _remaining_goal_grid(state, home_strength)
    result = {"home": 0.0, "draw": 0.0, "away": 0.0}

    for extra_home, row in enumerate(grid):
        for extra_away, joint in enumerate(row):
            margin = (state.goals_home + extra_home) - (state.goals_away + extra_away)
            if margin > 0:
                result["home"] += joint
            elif margin == 0:
                result["draw"] += joint
            else:
                result["away"] += joint

    return _normalise(result)


def total_goals_probabilities(state: MatchState, home_strength: float = 1.0) -> dict[str, float]:
    """Probabilidad real de superar o no la línea de 2,5 goles."""
    grid = _remaining_goal_grid(state, home_strength)
    scored = state.goals_home + state.goals_away
    result = {"over": 0.0, "under": 0.0}

    for extra_home, row in enumerate(grid):
        for extra_away, joint in enumerate(row):
            total = scored + extra_home + extra_away
            if total > OVER_UNDER_LINE:
                result["over"] += joint
            else:
                result["under"] += joint

    return _normalise(result)


def probabilities_to_odds(
    probabilities: dict[str, float], overround_target: float
) -> dict[str, float]:
    """Convierte probabilidades reales en cuotas publicables con margen.

    El margen se reparte de forma proporcional: cada probabilidad se infla por
    el mismo factor. Es el método más simple y el que deja al motor una vuelta
    exacta al normalizar, que es justamente lo que la HU-19 tiene que demostrar
    que sabe hacer.
    """
    return {
        outcome: round(
            min(max(1.0 / max(probability * overround_target, 1.0 / MAX_ODDS), MIN_ODDS), MAX_ODDS),
            ODDS_DECIMALS,
        )
        for outcome, probability in probabilities.items()
    }


def overround(odds: dict[str, float]) -> float:
    """Suma de los inversos de las cuotas: 1,0 sería un mercado sin margen."""
    return sum(1.0 / value for value in odds.values())


def implied_probabilities(odds: dict[str, float]) -> dict[str, float]:
    """Probabilidad implícita en un mercado, ya descontado el margen.

    Es la operación que la HU-19 necesita. Ojo con el atajo: ``1 / cuota`` no es
    la probabilidad implícita, es la probabilidad *inflada por el margen*, y
    usarla sesga sistemáticamente la comparación contra el modelo propio.
    """
    book = overround(odds)
    return {outcome: (1.0 / value) / book for outcome, value in odds.items()}
