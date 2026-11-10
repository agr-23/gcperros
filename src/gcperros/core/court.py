"""La cancha y el reglamento del baloncesto, el segundo deporte (#87).

Reglas FIBA: cuatro cuartos de diez minutos, prórrogas de cinco hasta que haya
ganador, un reloj de posesión de 24 segundos y el triple desde 6,75 m. Se elige
FIBA y no la NBA porque es el reglamento del baloncesto internacional y porque
sus partidos, más cortos, dejan una demostración más ágil. Se cambia sólo aquí.

Medidas en metros. Las coordenadas siguen la misma convención que en el fútbol
(``core/pitch.py``): normalizadas por dirección de ataque, con el equipo en
posesión atacando siempre hacia ``x = LENGTH``.
"""

from __future__ import annotations

LENGTH = 28.0
WIDTH = 15.0

#: El aro, visto desde el equipo en posesión: 1,575 m dentro de la línea de fondo.
BASKET = (LENGTH - 1.575, WIDTH / 2)

THREE_POINT_DISTANCE = 6.75
TWO_POINTS = 2
THREE_POINTS = 3

REGULATION_PERIODS = 4
#: El tercer cuarto abre la segunda parte, tras el descanso largo.
SECOND_HALF_START = 3
PERIOD_DURATION_S = 10 * 60
OVERTIME_DURATION_S = 5 * 60
SHOT_CLOCK_S = 24

#: Los cuatro cuartos y hasta seis prórrogas: más es antes un error que un récord.
MAX_PERIOD = REGULATION_PERIODS + 6
