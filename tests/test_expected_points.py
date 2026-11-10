"""El modelo de puntos esperados, el xG del baloncesto (#88)."""

from __future__ import annotations

import pytest

from gcperros.core import court
from gcperros.core.expected_points import (
    FREE_THROW_PROBABILITY,
    MODEL_VERSION,
    expected_points,
    make_probability,
)


@pytest.mark.parametrize(
    ("points_value", "distance", "reference"),
    [(2, 0.5, 0.65), (2, 4.0, 0.49), (3, court.THREE_POINT_DISTANCE, 0.40)],
)
def test_reference_values(points_value: int, distance: float, reference: float) -> None:
    assert make_probability(points_value, distance) == pytest.approx(reference, abs=0.01)


def test_the_farther_the_shot_the_less_it_goes_in() -> None:
    twos = [make_probability(2, d / 2) for d in range(1, 14)]
    threes = [make_probability(3, court.THREE_POINT_DISTANCE + d / 4) for d in range(8)]

    assert twos == sorted(twos, reverse=True)
    assert threes == sorted(threes, reverse=True)


def test_a_three_is_worth_more_than_a_long_two() -> None:
    """Es la razón por la que el baloncesto moderno tira tanto de tres."""
    long_two = expected_points(2, court.THREE_POINT_DISTANCE - 0.1)
    three = expected_points(3, court.THREE_POINT_DISTANCE)

    assert three > long_two


def test_probabilities_never_go_negative() -> None:
    assert make_probability(2, 20.0) == 0.0
    assert make_probability(3, 20.0) == 0.0


@pytest.mark.parametrize(("points_value", "distance"), [(4, 7.0), (1, 4.6), (3, 5.0)])
def test_impossible_shots_are_refused(points_value: int, distance: float) -> None:
    with pytest.raises(ValueError, match=r"tiro|triple"):
        make_probability(points_value, distance)


def test_the_model_is_versioned() -> None:
    assert MODEL_VERSION == "ep-1.0.0"
    assert 0.7 < FREE_THROW_PROBABILITY < 0.8
