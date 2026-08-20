"""Geometría del terreno de juego.

Las coordenadas de los eventos se emiten en un marco **normalizado por dirección
de ataque**: el equipo en posesión ataca siempre hacia ``x = LENGTH``. Sin esa
normalización, ``expected_goals(x, y)`` dependería de qué lado defiende cada
equipo, y tanto el motor como el plano batch tendrían que conocer el sorteo de
campos para interpretar un tiro.

Medidas en metros, según las dimensiones recomendadas por la IFAB para partidos
internacionales (105 x 68).
"""

from __future__ import annotations

LENGTH = 105.0
WIDTH = 68.0

GOAL_WIDTH = 7.32
GOAL_CENTER_Y = WIDTH / 2

# Postes vistos desde el equipo en posesión, es decir en la línea x = LENGTH.
LEFT_POST = (LENGTH, GOAL_CENTER_Y - GOAL_WIDTH / 2)
RIGHT_POST = (LENGTH, GOAL_CENTER_Y + GOAL_WIDTH / 2)

# Frontal del área grande y del área chica.
PENALTY_AREA_X = LENGTH - 16.5
GOAL_AREA_X = LENGTH - 5.5

CENTER_SPOT = (LENGTH / 2, WIDTH / 2)


def clamp_to_pitch(x: float, y: float) -> tuple[float, float]:
    """Devuelve el punto más cercano dentro de los límites del campo."""
    return (
        min(max(x, 0.0), LENGTH),
        min(max(y, 0.0), WIDTH),
    )


def mirror(x: float, y: float) -> tuple[float, float]:
    """Traduce un punto al marco del equipo contrario.

    Cuando la posesión cambia, el balón está físicamente en el mismo sitio pero
    el nuevo equipo ataca en sentido opuesto: lo que para uno era campo rival,
    para el otro es campo propio.
    """
    return LENGTH - x, WIDTH - y
