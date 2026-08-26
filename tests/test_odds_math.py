"""Verificación del modelo de probabilidad y de la conversión a cuotas."""

from __future__ import annotations

import pytest

from gcperros.core.odds import (
    MatchState,
    implied_probabilities,
    match_result_probabilities,
    overround,
    probabilities_to_odds,
    remaining_fraction,
    scoring_rates,
    total_goals_probabilities,
)

KICKOFF = MatchState(minute=0.0, goals_home=0, goals_away=0)


def test_pre_match_probabilities_match_the_domain() -> None:
    """Un 1X2 antes del saque reparte aproximadamente 45 / 26 / 29."""
    probabilities = match_result_probabilities(KICKOFF)

    assert 0.40 <= probabilities["home"] <= 0.50
    assert 0.22 <= probabilities["draw"] <= 0.30
    assert 0.25 <= probabilities["away"] <= 0.35


def test_probabilities_always_sum_to_one() -> None:
    for state in (KICKOFF, MatchState(30, 1, 0), MatchState(85, 2, 2), MatchState(45, 0, 3)):
        assert sum(match_result_probabilities(state).values()) == pytest.approx(1.0)
        assert sum(total_goals_probabilities(state).values()) == pytest.approx(1.0)


def test_home_advantage_is_present() -> None:
    probabilities = match_result_probabilities(KICKOFF)
    assert probabilities["home"] > probabilities["away"]


def test_scoring_a_goal_raises_your_win_probability() -> None:
    before = match_result_probabilities(MatchState(30, 0, 0))["home"]
    after = match_result_probabilities(MatchState(30, 1, 0))["home"]
    assert after > before


def test_a_lead_is_worth_more_as_time_runs_out() -> None:
    """El mismo 1-0 vale más en el 80 que en el 20: queda menos partido."""
    early = match_result_probabilities(MatchState(20, 1, 0))["home"]
    late = match_result_probabilities(MatchState(80, 1, 0))["home"]
    assert late > early


def test_a_red_card_shifts_the_market_towards_the_rival() -> None:
    even = match_result_probabilities(MatchState(30, 0, 0))
    away_sent_off = match_result_probabilities(MatchState(30, 0, 0, red_cards_away=1))

    assert away_sent_off["home"] > even["home"]
    assert away_sent_off["away"] < even["away"]


def test_red_cards_compound() -> None:
    one = match_result_probabilities(MatchState(30, 0, 0, red_cards_away=1))["home"]
    two = match_result_probabilities(MatchState(30, 0, 0, red_cards_away=2))["home"]
    assert two > one


def test_a_settled_match_leaves_no_doubt() -> None:
    probabilities = match_result_probabilities(MatchState(90, 2, 1))
    assert probabilities["home"] == pytest.approx(1.0)


def test_over_under_reacts_to_goals_already_scored() -> None:
    """Con tres goles marcados, superar 2,5 ya no es una incógnita."""
    assert total_goals_probabilities(MatchState(60, 2, 1))["over"] == pytest.approx(1.0)
    assert total_goals_probabilities(MatchState(89, 0, 0))["under"] > 0.99


def test_remaining_fraction_is_bounded() -> None:
    assert remaining_fraction(0.0) == 1.0
    assert remaining_fraction(45.0) == pytest.approx(0.5)
    assert remaining_fraction(90.0) == 0.0
    assert remaining_fraction(97.0) == 0.0  # tiempo añadido


def test_scoring_rates_fall_to_zero_at_the_final_whistle() -> None:
    assert scoring_rates(MatchState(90, 0, 0)) == (0.0, 0.0)


###############################################################################
# Margen del operador — el núcleo de lo que la HU-19 tendrá que deshacer
###############################################################################


def test_odds_carry_the_operator_margin() -> None:
    odds = probabilities_to_odds(match_result_probabilities(KICKOFF), 1.06)
    # El redondeo a dos decimales desplaza un poco el margen efectivo, igual que
    # ocurre con los precios reales.
    assert 1.05 <= overround(odds) <= 1.07


def test_implied_probabilities_recover_the_true_ones() -> None:
    """Descontar el margen debe devolver exactamente la probabilidad de partida."""
    truth = match_result_probabilities(MatchState(35, 1, 1))
    odds = probabilities_to_odds(truth, 1.06)
    recovered = implied_probabilities(odds)

    for outcome, value in truth.items():
        assert recovered[outcome] == pytest.approx(value, abs=0.005)


def test_the_naive_shortcut_is_biased() -> None:
    """`1 / cuota` no es la probabilidad implícita, y por eso no suma uno.

    Esta prueba existe para dejar constancia del error que la HU-19 debe evitar:
    el atajo sobreestima cada resultado en proporción al margen del operador.
    """
    odds = probabilities_to_odds(match_result_probabilities(KICKOFF), 1.06)
    naive = {outcome: 1.0 / value for outcome, value in odds.items()}

    assert sum(naive.values()) > 1.0
    for outcome, value in implied_probabilities(odds).items():
        assert naive[outcome] > value


def test_implied_probabilities_sum_to_one() -> None:
    odds = probabilities_to_odds(total_goals_probabilities(MatchState(20, 1, 0)), 1.04)
    assert sum(implied_probabilities(odds).values()) == pytest.approx(1.0)


def test_odds_stay_inside_publishable_limits() -> None:
    for state in (KICKOFF, MatchState(89, 4, 0), MatchState(89, 0, 4)):
        odds = probabilities_to_odds(match_result_probabilities(state), 1.06)
        for value in odds.values():
            assert 1.01 <= value <= 200.0


def test_a_bigger_margin_means_worse_prices() -> None:
    """A igual probabilidad, más margen es siempre menos cuota para el cliente."""
    probabilities = match_result_probabilities(KICKOFF)
    cheap = probabilities_to_odds(probabilities, 1.03)
    expensive = probabilities_to_odds(probabilities, 1.12)

    for outcome in probabilities:
        assert expensive[outcome] < cheap[outcome]
