"""El modelo de mercado del baloncesto: ganador y total de puntos (#90)."""

from __future__ import annotations

import pytest

from gcperros.core import court
from gcperros.core.basketball_odds import (
    BasketballState,
    moneyline_probabilities,
    opening_line,
    seconds_left,
    total_points_probabilities,
)
from gcperros.core.odds import implied_probabilities, probabilities_to_odds
from gcperros.generators.basketball import simulate_basketball

TIPOFF = BasketballState(period=1, clock_s=court.PERIOD_DURATION_S, points_home=0, points_away=0)


def _state(period: int, clock_s: float, home: int, away: int) -> BasketballState:
    return BasketballState(period=period, clock_s=clock_s, points_home=home, points_away=away)


def test_every_market_sums_to_one() -> None:
    for state in (TIPOFF, _state(3, 312.0, 51, 44), _state(4, 4.0, 88, 90)):
        assert sum(moneyline_probabilities(state).values()) == pytest.approx(1.0)
        assert sum(total_points_probabilities(state, 161.5).values()) == pytest.approx(1.0)


def test_an_even_match_starts_even_and_the_operator_bias_tilts_it() -> None:
    assert moneyline_probabilities(TIPOFF)["home"] == pytest.approx(0.5)
    assert moneyline_probabilities(TIPOFF, home_strength=1.04)["home"] > 0.55


def test_the_same_lead_is_worth_more_the_less_time_is_left() -> None:
    early = moneyline_probabilities(_state(1, 300.0, 8, 3))["home"]
    late = moneyline_probabilities(_state(4, 60.0, 80, 75))["home"]

    assert 0.5 < early < late < 1.0


def test_with_no_time_left_the_scoreboard_decides_and_a_tie_goes_to_overtime() -> None:
    assert moneyline_probabilities(_state(4, 0.0, 80, 79))["home"] == 1.0
    assert moneyline_probabilities(_state(4, 0.0, 79, 80))["home"] == 0.0
    assert moneyline_probabilities(_state(4, 0.0, 80, 80))["home"] == 0.5


def test_overtime_counts_only_its_own_clock() -> None:
    assert seconds_left(_state(5, 120.0, 90, 90)) == 120.0
    assert seconds_left(_state(2, 100.0, 30, 30)) == 100.0 + 2 * court.PERIOD_DURATION_S


def test_the_total_opens_on_a_half_point_near_the_expected_total() -> None:
    line = opening_line()

    assert line == 161.5
    assert total_points_probabilities(TIPOFF, line)["over"] == pytest.approx(0.5, abs=0.02)
    assert total_points_probabilities(_state(4, 30.0, 85, 80), line)["over"] > 0.99


def test_the_margin_comes_off_exactly_the_same_way_as_in_football() -> None:
    """La conversión y el descuento del margen no dependen del deporte."""
    real = moneyline_probabilities(_state(2, 200.0, 40, 33), home_strength=0.97)

    implied = implied_probabilities(probabilities_to_odds(real, overround_target=1.06))

    for outcome, probability in real.items():
        assert implied[outcome] == pytest.approx(probability, abs=0.01)


def test_the_model_is_calibrated_against_the_generator() -> None:
    """Predicho al descanso contra lo que pasó: mejor que tirar una moneda, y bastante."""
    squared_errors: list[float] = []
    for seed in range(400, 560):
        score = {"HOME": 0, "AWAY": 0}
        halftime: BasketballState | None = None
        for event in simulate_basketball(seed):
            if halftime is None and event.attrs["period"] == court.SECOND_HALF_START:
                halftime = _state(3, court.PERIOD_DURATION_S, score["HOME"], score["AWAY"])
            if event.attrs.get("made") is True:
                value = event.attrs.get("points_value", 1)
                score[event.team] += value if isinstance(value, int) else 1
        assert halftime is not None
        won = 1.0 if score["HOME"] > score["AWAY"] else 0.0
        squared_errors.append((moneyline_probabilities(halftime)["home"] - won) ** 2)

    brier = sum(squared_errors) / len(squared_errors)
    assert brier < 0.20, f"Brier {brier:.3f}: una moneda daría 0,25"
