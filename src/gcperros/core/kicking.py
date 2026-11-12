"""Las patadas del fútbol americano: lo que vale de media un gol de campo o una conversión.

Es el xG del tercer deporte, y con la misma idea: una función cerrada que
comparten el generador, que decide cada patada muestreando ``Bernoulli(p)``, y
el motor, que acumula los puntos esperados de cada equipo. La probabilidad de
un gol de campo cae en línea recta con la distancia; las de las conversiones
son fijas. Valores de referencia de la NFL, que verifica
``tests/test_american_football_summary.py``:

    gol de campo de 30 yardas   -> ~0.89
    gol de campo de 50 yardas   -> ~0.65
    conversión pateada          ->  0.94
    conversión de dos puntos    ->  0.48
"""

from __future__ import annotations

from gcperros.core import gridiron

#: Versión del modelo: viaja con el indicador que lo usa, como la del xG.
MODEL_VERSION = "kick-1.0.0"

FIELD_GOAL_AT_ZERO = 1.25
FIELD_GOAL_DECAY_PER_YARD = 0.012
FIELD_GOAL_FLOOR = 0.05
FIELD_GOAL_CEILING = 0.98

EXTRA_POINT_PROBABILITY = 0.94
TWO_POINT_PROBABILITY = 0.48


def field_goal_probability(distance_yd: int) -> float:
    """Probabilidad de meter un gol de campo desde ``distance_yd`` yardas."""
    raw = FIELD_GOAL_AT_ZERO - FIELD_GOAL_DECAY_PER_YARD * distance_yd
    return round(min(max(raw, FIELD_GOAL_FLOOR), FIELD_GOAL_CEILING), 4)


def conversion_probability(kind: str) -> float:
    """Probabilidad de una conversión pateada (``kick``) o jugada (``two_point``)."""
    return EXTRA_POINT_PROBABILITY if kind == "kick" else TWO_POINT_PROBABILITY


def conversion_value(kind: str) -> int:
    """Lo que vale una conversión si entra."""
    return gridiron.EXTRA_POINT if kind == "kick" else gridiron.TWO_POINT
