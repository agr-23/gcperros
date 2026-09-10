"""Señal de discrepancia entre el modelo y el mercado (HU-19)."""

from __future__ import annotations

import datetime as dt
from datetime import UTC, datetime

import pytest

from gcperros.core.contracts import MatchEvent, OddsUpdate
from gcperros.core.odds import (
    MatchState,
    implied_probabilities,
    match_result_probabilities,
    probabilities_to_odds,
)
from gcperros.engine.signals import (
    DEFAULT_THRESHOLD,
    DiscrepancyDetector,
    detect_discrepancies,
    model_probabilities,
)
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.odds import simulate_odds

BASE = datetime(2026, 8, 26, 19, 0, 0, tzinfo=UTC)
CONFIG = MatchConfig(match_id="match-0019", home_team="RMA", away_team="BAR")
SEED = 20260826


def _quote(odds: dict[str, float], second: float = 0.0, operator: str = "OP-A") -> OddsUpdate:
    return OddsUpdate(
        event_id=f"o{second}-{operator}",
        event_time=BASE + dt.timedelta(seconds=second),
        match_id="match-0019",
        operator=operator,
        market="1x2",
        odds=odds,
        trigger="drift",
    )


###############################################################################
# El margen se descuenta: el corazón de la historia
###############################################################################


def test_a_fair_price_with_margin_raises_no_signal() -> None:
    """Si el operador cotiza justo lo que cree el modelo, no hay nada que señalar.

    Es la prueba central: el mercado publica exactamente las probabilidades del
    modelo, sólo que infladas por su margen. Un detector que no descontara el
    margen vería discrepancia en los tres resultados a la vez.
    """
    state = MatchState(minute=0.0, goals_home=0, goals_away=0)
    truth = match_result_probabilities(state)

    detector = DiscrepancyDetector()
    signals = detector.evaluate(_quote(probabilities_to_odds(truth, 1.06)))

    assert signals == []


def test_even_a_fat_margin_raises_no_signal() -> None:
    """Con un margen del 15 % el atajo ingenuo se equivocaría de largo."""
    truth = match_result_probabilities(MatchState(minute=0.0, goals_home=0, goals_away=0))

    detector = DiscrepancyDetector()
    assert detector.evaluate(_quote(probabilities_to_odds(truth, 1.15))) == []


def test_the_naive_shortcut_would_invent_discrepancies() -> None:
    """Deja constancia del error que la historia manda evitar.

    ``1 / cuota`` no es la probabilidad implícita: sobreestima cada resultado en
    proporción al margen. Sobre el mismo precio justo del caso anterior, el
    atajo se separa del modelo por encima del umbral y el detector correcto no.
    """
    truth = match_result_probabilities(MatchState(minute=0.0, goals_home=0, goals_away=0))
    odds = probabilities_to_odds(truth, 1.15)

    naive = {outcome: 1.0 / value for outcome, value in odds.items()}
    correct = implied_probabilities(odds)

    assert sum(naive.values()) > 1.0
    assert max(abs(truth[o] - naive[o]) for o in truth) > DEFAULT_THRESHOLD
    assert max(abs(truth[o] - correct[o]) for o in truth) < DEFAULT_THRESHOLD


###############################################################################
# El umbral
###############################################################################


def test_a_small_gap_stays_quiet() -> None:
    truth = match_result_probabilities(MatchState(minute=0.0, goals_home=0, goals_away=0))
    nudged = dict(truth)
    nudged["home"] += 0.02
    nudged["away"] -= 0.02

    assert DiscrepancyDetector().evaluate(_quote(probabilities_to_odds(nudged, 1.06))) == []


def test_a_big_gap_fires_with_both_numbers_and_the_time() -> None:
    truth = match_result_probabilities(MatchState(minute=0.0, goals_home=0, goals_away=0))
    skewed = dict(truth)
    skewed["home"] += 0.20
    skewed["away"] -= 0.20

    signals = DiscrepancyDetector().evaluate(
        _quote(probabilities_to_odds(skewed, 1.06), second=120)
    )

    assert signals
    signal = next(s for s in signals if s.outcome == "home")
    # La historia pide que la señal lleve ambas cifras y el instante.
    assert signal.model_probability == pytest.approx(truth["home"], abs=0.01)
    assert signal.market_probability == pytest.approx(skewed["home"], abs=0.01)
    assert signal.detected_at == BASE + dt.timedelta(seconds=120)
    assert signal.magnitude >= DEFAULT_THRESHOLD


def test_the_threshold_is_configurable() -> None:
    truth = match_result_probabilities(MatchState(minute=0.0, goals_home=0, goals_away=0))
    nudged = dict(truth)
    nudged["home"] += 0.03
    nudged["away"] -= 0.03
    odds = probabilities_to_odds(nudged, 1.06)

    assert DiscrepancyDetector(threshold=0.10).evaluate(_quote(odds)) == []
    assert DiscrepancyDetector(threshold=0.01).evaluate(_quote(odds))


def test_an_impossible_threshold_is_rejected() -> None:
    for value in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="entre 0 y 1"):
            DiscrepancyDetector(threshold=value)


def test_divergence_carries_its_direction() -> None:
    truth = match_result_probabilities(MatchState(minute=0.0, goals_home=0, goals_away=0))
    skewed = dict(truth)
    skewed["home"] -= 0.20
    skewed["away"] += 0.20

    signals = DiscrepancyDetector().evaluate(_quote(probabilities_to_odds(skewed, 1.06)))

    home = next(s for s in signals if s.outcome == "home")
    assert home.divergence > 0, "el modelo ve al local mejor que el mercado"
    assert "modelo por encima" in home.describe()


###############################################################################
# El precio rancio, que es lo que la historia quiere capturar
###############################################################################


def _goal(second: float, team: str) -> MatchEvent:
    return MatchEvent(
        event_id=f"g{second}",
        event_time=BASE + dt.timedelta(seconds=second),
        match_id="match-0019",
        team=team,
        event_type="goal",
        attrs={"period": 1},
    )


def _kickoff() -> MatchEvent:
    return MatchEvent(
        event_id="k0",
        event_time=BASE,
        match_id="match-0019",
        team="RMA",
        event_type="possession_change",
        attrs={"period": 1, "reason": "kickoff", "to_team": "RMA", "from_team": "BAR"},
    )


def test_a_goal_leaves_the_standing_price_stale_and_fires() -> None:
    """Entre el gol y el reprecio, el precio publicado ya no vale.

    Es el momento que la historia persigue, y sólo se ve si el detector revisa
    el precio vigente en vez de esperar a que llegue una cuota nueva.
    """
    detector = DiscrepancyDetector()
    detector.apply_match_event(_kickoff())

    truth = match_result_probabilities(MatchState(minute=0.0, goals_home=0, goals_away=0))
    assert detector.evaluate(_quote(probabilities_to_odds(truth, 1.06))) == []

    # El local marca; el operador todavía no ha repreciado.
    signals = detector.apply_match_event(_goal(600, "RMA"))

    assert signals, "el precio anterior al gol tiene que quedar señalado"
    home = next(s for s in signals if s.outcome == "home")
    assert home.divergence > 0
    assert home.detected_at == BASE + dt.timedelta(seconds=600)


def test_an_ordinary_event_does_not_re_evaluate() -> None:
    """Revisar en cada pase sería ruido: sólo un gol o una roja mueven el precio."""
    detector = DiscrepancyDetector()
    detector.apply_match_event(_kickoff())
    truth = match_result_probabilities(MatchState(minute=0.0, goals_home=0, goals_away=0))
    detector.evaluate(_quote(probabilities_to_odds(truth, 1.06)))

    a_pass = MatchEvent(
        event_id="p1",
        event_time=BASE + dt.timedelta(seconds=300),
        match_id="match-0019",
        team="RMA",
        event_type="pass",
        attrs={"period": 1, "completed": True},
    )
    assert detector.apply_match_event(a_pass) == []


def test_nothing_fires_before_any_price_exists() -> None:
    detector = DiscrepancyDetector()
    detector.apply_match_event(_kickoff())
    assert detector.apply_match_event(_goal(60, "RMA")) == []


###############################################################################
# Sobre un partido completo
###############################################################################


def test_the_model_and_the_market_use_the_same_match_state() -> None:
    """Si partieran de estados distintos, la señal mediría el desajuste."""
    events = simulate_match(SEED, CONFIG)
    detector = DiscrepancyDetector()
    for event in events[:400]:
        detector.apply_match_event(event)

    state = detector.state
    goals = sum(1 for e in events[:400] if e.event_type == "goal")

    assert state.goals_home + state.goals_away == goals
    assert state.minute > 0


def test_detection_is_deterministic() -> None:
    events = simulate_match(SEED, CONFIG)
    updates = simulate_odds(SEED, events)

    first = detect_discrepancies(events, updates)
    second = detect_discrepancies(events, updates)

    assert first == second


def test_signals_come_out_in_order() -> None:
    events = simulate_match(SEED, CONFIG)
    signals = detect_discrepancies(events, simulate_odds(SEED, events))

    stamps = [signal.detected_at for signal in signals]
    assert stamps == sorted(stamps)


def test_a_higher_threshold_never_yields_more_signals() -> None:
    events = simulate_match(SEED, CONFIG)
    updates = simulate_odds(SEED, events)

    counts = [len(detect_discrepancies(events, updates, threshold=t)) for t in (0.02, 0.05, 0.15)]
    assert counts == sorted(counts, reverse=True)


@pytest.mark.statistical
def test_signals_cluster_around_the_events_that_move_the_market() -> None:
    """Si aparecieran en cualquier momento, no estarían midiendo nada."""
    near, total = 0, 0

    for seed in range(6):
        config = MatchConfig(match_id=f"m{seed}", home_team="RMA", away_team="BAR")
        events = simulate_match(seed, config)
        signals = detect_discrepancies(events, simulate_odds(seed, events))
        moments = [e.event_time for e in events if e.event_type in {"goal", "red_card"}]

        total += len(signals)
        near += sum(
            1
            for s in signals
            if any(0 <= (s.detected_at - m).total_seconds() <= 45 for m in moments)
        )

    assert total > 0
    assert near / total > 0.3, "las señales tienen que concentrarse tras gol o expulsión"


@pytest.mark.statistical
def test_operator_bias_shows_in_the_average_gap() -> None:
    """El sesgo del operador se mide, aunque no cruce el umbral por sí solo.

    OP-A valora al local igual que el modelo; OP-B y OP-C no. Esa diferencia
    aparece en la discrepancia media, no en el número de señales: al umbral
    declarado las señales las dominan los precios rancios, y un gol deja rancios
    los libros de las tres casas por igual.
    """
    totals: dict[str, list[float]] = {}

    for seed in range(8):
        config = MatchConfig(match_id=f"m{seed}", home_team="RMA", away_team="BAR")
        events = simulate_match(seed, config)
        # Umbral mínimo para ver todas las comparaciones, no sólo las notables.
        for signal in detect_discrepancies(events, simulate_odds(seed, events), threshold=0.0001):
            totals.setdefault(signal.operator, []).append(signal.magnitude)

    average = {op: sum(gaps) / len(gaps) for op, gaps in totals.items()}
    assert average["OP-A"] < average["OP-B"]
    assert average["OP-A"] < average["OP-C"]


@pytest.mark.statistical
def test_a_goal_leaves_every_book_stale_alike() -> None:
    """El retardo de cada casa no cambia a cuántas pilla el gol, sólo cuándo se corrigen."""
    stale: dict[str, int] = {}

    for seed in range(8):
        config = MatchConfig(match_id=f"m{seed}", home_team="RMA", away_team="BAR")
        events = simulate_match(seed, config)
        moments = [e.event_time for e in events if e.event_type in {"goal", "red_card"}]
        for signal in detect_discrepancies(events, simulate_odds(seed, events)):
            if any(0 <= (signal.detected_at - m).total_seconds() <= 45 for m in moments):
                stale[signal.operator] = stale.get(signal.operator, 0) + 1

    counts = list(stale.values())
    assert len(counts) == 3
    assert max(counts) == min(counts)


def test_model_probabilities_cover_both_markets() -> None:
    state = MatchState(minute=30.0, goals_home=1, goals_away=0)

    assert set(model_probabilities("1x2", state)) == {"home", "draw", "away"}
    assert set(model_probabilities("over_under_2_5", state)) == {"over", "under"}
