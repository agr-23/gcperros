"""Verificación del modelo de goles esperados contra referencias del dominio."""

from __future__ import annotations

import pytest

from gcperros.core import pitch
from gcperros.core.xg import expected_goals, goal_mouth_angle, shot_distance

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
