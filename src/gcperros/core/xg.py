"""Modelo de goles esperados (xG).

Función paramétrica cerrada, calibrada analíticamente sobre puntos de referencia
del dominio. **No es un modelo entrenado**: su propósito es habilitar la
validación del sistema de datos, no competir con modelos comerciales de
predicción deportiva (ver alcance del proyecto, "Que NO incluye").

Este módulo es la pieza que comparten el generador y el motor. El generador
decide cada gol muestreando ``Bernoulli(xG)`` sobre esta función (HU-8); el
motor recalcula el mismo xG a partir de las coordenadas que le llegan por el
broker (HU-11/12). Que ambos planos usen exactamente esta implementación es lo
que hace informativa la comparación "goles observados contra xG acumulado": la
convergencia no valida el acierto del modelo —eso sería tautológico, porque el
gol se muestrea del propio xG— sino que las coordenadas del tiro atravesaron el
pipeline sin corromperse. Si el motor reconstruye un xG distinto del que usó el
generador, el dato se degradó en el transporte.
"""

from __future__ import annotations

import math

from gcperros.core import pitch

# Coeficientes del modelo logístico. Calibrados para reproducir los siguientes
# valores de referencia en tiro central de juego abierto, que son los que
# verifica `tests/test_xg.py`:
#
#     6 m  -> ~0.49      dentro del área chica
#    11 m  -> ~0.22      punto de penal, en juego abierto
#    16.5 m -> ~0.10     frontal del área grande
#    30 m  -> ~0.02      disparo lejano
#
# El término de ángulo penaliza los tiros escorados: dos disparos a la misma
# distancia valen distinto según cuánta portería vea el rematador.
BETA_INTERCEPT = -1.20
BETA_DISTANCE = -0.10
BETA_ANGLE = 1.60

# Los valores de xG se redondean antes de salir del módulo. Es lo que garantiza
# que el generador y el motor comparen números idénticos y que la serialización
# sea estable byte a byte entre ejecuciones.
XG_DECIMALS = 4


def shot_distance(x: float, y: float) -> float:
    """Distancia euclídea desde el punto de remate al centro de la portería."""
    return math.hypot(pitch.LENGTH - x, pitch.GOAL_CENTER_Y - y)


def goal_mouth_angle(x: float, y: float) -> float:
    """Ángulo en radianes que subtiende la portería desde el punto de remate.

    Es la porción de arco que el rematador tiene realmente a la vista: máxima
    frente al centro y decreciente hacia las bandas, incluso sin alejarse.
    """
    to_left = math.hypot(pitch.LEFT_POST[0] - x, pitch.LEFT_POST[1] - y)
    to_right = math.hypot(pitch.RIGHT_POST[0] - x, pitch.RIGHT_POST[1] - y)

    # Remate exactamente sobre un poste: el ángulo degenera y se toma como nulo.
    denominator = to_left * to_right
    if denominator == 0.0:
        return 0.0

    cosine = (to_left**2 + to_right**2 - pitch.GOAL_WIDTH**2) / (2 * denominator)
    # El coseno puede salirse de [-1, 1] por error de redondeo en flotante.
    return math.acos(min(max(cosine, -1.0), 1.0))


def expected_goals(x: float, y: float) -> float:
    """Probabilidad de que un remate desde ``(x, y)`` termine en gol.

    Args:
        x: Distancia al fondo propio, en metros, atacando hacia ``pitch.LENGTH``.
        y: Distancia a la banda, en metros.

    Returns:
        Probabilidad en ``[0, 1]``, redondeada a ``XG_DECIMALS`` decimales.
    """
    logit = (
        BETA_INTERCEPT + BETA_DISTANCE * shot_distance(x, y) + BETA_ANGLE * goal_mouth_angle(x, y)
    )
    return round(1.0 / (1.0 + math.exp(-logit)), XG_DECIMALS)
