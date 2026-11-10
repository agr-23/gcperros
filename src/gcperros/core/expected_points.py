"""Puntos esperados: el xG del baloncesto (#88).

Lo que vale un tiro por la probabilidad de anotarlo. Como el xG del fútbol
(``core/xg.py``), es una función cerrada y no un modelo entrenado, y la comparten
el generador, que decide cada canasta muestreando ``Bernoulli(p)``, y el motor,
que acumula los puntos esperados de cada equipo (#89).

La probabilidad cae en línea recta con la distancia al aro, con un salto en la
línea de triple: un tiro de tres es más difícil que uno de dos desde el mismo
sitio porque se tira desde más lejos y más defendido. Valores de referencia, que
verifica ``tests/test_expected_points.py``:

    pegado al aro (0,5 m)       -> ~0.65
    media distancia (4 m)       -> ~0.49
    triple desde la línea       -> ~0.40
    tiro libre                  ->  0.76
"""

from __future__ import annotations

from gcperros.core import court

#: Versión del modelo. Viaja con cada indicador que lo usa, como la del xG:
#: tocar un coeficiente obliga a subirla.
MODEL_VERSION = "ep-1.0.0"

TWO_POINT_AT_RIM = 0.67
TWO_POINT_DECAY_PER_M = 0.045
THREE_POINT_AT_LINE = 0.40
THREE_POINT_DECAY_PER_M = 0.05

#: Sin defensa y siempre desde el mismo sitio: una sola probabilidad basta.
FREE_THROW_PROBABILITY = 0.76


def make_probability(points_value: int, distance_m: float) -> float:
    """Probabilidad de anotar un tiro de ``points_value`` desde ``distance_m`` del aro.

    Raises:
        ValueError: Si el tiro no vale dos ni tres, o si un triple se tira desde
            dentro de la línea.
    """
    if points_value == court.THREE_POINTS:
        if distance_m < court.THREE_POINT_DISTANCE:
            raise ValueError(f"un triple no se tira desde {distance_m} m")
        decay = THREE_POINT_DECAY_PER_M * (distance_m - court.THREE_POINT_DISTANCE)
        return round(max(THREE_POINT_AT_LINE - decay, 0.0), 4)
    if points_value == court.TWO_POINTS:
        return round(max(TWO_POINT_AT_RIM - TWO_POINT_DECAY_PER_M * distance_m, 0.0), 4)
    raise ValueError(f"un tiro de campo vale dos o tres, no {points_value}")


def expected_points(points_value: int, distance_m: float) -> float:
    """Lo que vale de media un tiro de ``points_value`` desde ``distance_m``."""
    return round(points_value * make_probability(points_value, distance_m), 4)
