"""El campo y el reglamento del fútbol americano, el tercer deporte.

Reglas de la NFL: cuatro cuartos de quince minutos, un reloj de jugada de 40
segundos y una prórroga de diez minutos. El campo se mide en yardas, y la
posición del balón como yardas desde la propia línea de gol: 0 es la propia
zona de anotación y 100 la del rival. Se cambia sólo aquí.
"""

from __future__ import annotations

FIELD_YARDS = 100

TOUCHDOWN = 6
FIELD_GOAL = 3
SAFETY = 2
EXTRA_POINT = 1
TWO_POINT = 2

REGULATION_PERIODS = 4
#: El tercer cuarto abre la segunda parte, tras el descanso largo.
SECOND_HALF_START = 3
PERIOD_DURATION_S = 15 * 60
OVERTIME_DURATION_S = 10 * 60
#: Los cuatro cuartos y una prórroga.
MAX_PERIOD = REGULATION_PERIODS + 1

#: Lo que tiene el ataque para poner el balón en juego tras la jugada anterior.
PLAY_CLOCK_S = 40

#: Una jugada gana o pierde yardas dentro del campo: nunca más que su largo.
MAX_PLAY_YARDS = FIELD_YARDS - 1

#: Un gol de campo se patea desde la línea de golpeo más diecisiete yardas.
MIN_FIELD_GOAL_YARDS = 18
MAX_FIELD_GOAL_YARDS = 70

DOWNS = 4
