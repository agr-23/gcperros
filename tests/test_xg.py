"""Verificación del modelo de goles esperados contra referencias del dominio."""

from __future__ import annotations

import hashlib

import pytest

from gcperros.core import pitch
from gcperros.core.xg import MODEL_VERSION, expected_goals, goal_mouth_angle, shot_distance

CENTER = pitch.GOAL_CENTER_Y


def _central_shot_at(distance: float) -> float:
    return expected_goals(pitch.LENGTH - distance, CENTER)


@pytest.mark.parametrize(
    ("distance_m", "low", "high"),
    [
        (6.0, 0.40, 0.60),  # área chica
        (11.0, 0.15, 0.30),  # punto de penal, juego abierto
        (16.5, 0.06, 0.15),  # frontal del área grande
        (30.0, 0.005, 0.05),  # disparo lejano
    ],
)
def test_central_shots_match_domain_reference_ranges(
    distance_m: float, low: float, high: float
) -> None:
    assert low <= _central_shot_at(distance_m) <= high


def test_xg_decreases_with_distance() -> None:
    values = [_central_shot_at(d) for d in (6, 11, 16.5, 22, 30, 40)]
    assert values == sorted(values, reverse=True)


def test_xg_decreases_as_the_shot_gets_wider() -> None:
    """A igual distancia al fondo, ver menos portería vale menos."""
    values = [expected_goals(pitch.LENGTH - 16.5, CENTER + offset) for offset in (0, 5, 10, 20)]
    assert values == sorted(values, reverse=True)


def test_probability_is_bounded() -> None:
    for x in range(0, 106, 5):
        for y in range(0, 69, 4):
            assert 0.0 <= expected_goals(float(x), float(y)) <= 1.0


def test_goal_mouth_angle_is_widest_in_front_of_goal() -> None:
    in_front = goal_mouth_angle(pitch.LENGTH - 10, CENTER)
    from_the_wing = goal_mouth_angle(pitch.LENGTH - 10, 2.0)
    assert in_front > from_the_wing


def test_goal_mouth_angle_degenerates_on_the_post() -> None:
    """Sobre el propio poste el ángulo no está definido; se devuelve 0 sin excepción."""
    assert goal_mouth_angle(*pitch.LEFT_POST) == 0.0


def test_shot_distance_is_measured_to_the_goal_centre() -> None:
    assert shot_distance(pitch.LENGTH, CENTER) == 0.0
    assert shot_distance(pitch.LENGTH - 10, CENTER) == pytest.approx(10.0)


def test_model_is_a_pure_function() -> None:
    """Sin estado interno: el motor y el generador deben obtener el mismo valor."""
    assert expected_goals(90.0, 30.0) == expected_goals(90.0, 30.0)


###############################################################################
# Versión del modelo (HU-18)
###############################################################################

#: Huella de las salidas del modelo sobre una rejilla del campo. Congelada a
#: propósito, como las de `tests/test_pipeline.py`: si cambia, el modelo dejó de
#: calcular lo mismo y `MODEL_VERSION` tiene que subir en el mismo commit.
#:
#: Se muestrean salidas y no coeficientes porque lo que hay que detectar es un
#: cambio en lo que el modelo *responde*, venga de una constante o de la fórmula.
MODEL_FINGERPRINT = "888e093ac11d8b1ea15416c4dd67c732d45ac257c9797e4bf9dbc8d104bfd802"


def _model_fingerprint() -> str:
    valores = [
        f"{expected_goals(x, y):.4f}"
        for x in range(0, int(pitch.LENGTH) + 1, 5)
        for y in range(0, int(pitch.WIDTH) + 1, 4)
    ]
    return hashlib.sha256("|".join(valores).encode("utf-8")).hexdigest()


def test_the_model_has_not_drifted_without_saying_so() -> None:
    """Si falla: o se recalibró sin querer, o hay que subir MODEL_VERSION."""
    assert _model_fingerprint() == MODEL_FINGERPRINT, (
        "el modelo de xG cambió. Si es a propósito, sube MODEL_VERSION y "
        "actualiza esta huella en el mismo commit, explicando el motivo."
    )


def test_the_model_declares_a_version() -> None:
    """Viaja con cada indicador que lo usa, así que no puede faltar."""
    assert MODEL_VERSION.strip()
