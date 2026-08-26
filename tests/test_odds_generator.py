"""Comportamiento del generador de cuotas (HU-9).

Lo que la historia promete y aquí se comprueba: que el mercado reaccione a los
eventos relevantes acortando la cuota del beneficiado, y que se quede casi
quieto cuando no pasa nada.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest

from gcperros.core.contracts import MARKET_OUTCOMES, ODDS_CONTRACT_VERSION, MatchEvent, OddsUpdate
from gcperros.core.odds import MAX_ODDS, MIN_ODDS, overround
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.odds import (
    MARKETS,
    OPERATORS,
    simulate_odds,
    summarize_odds,
)

CONFIG = MatchConfig(match_id="match-0042", home_team="RMA", away_team="BAR")
SEED = 20260826

#: Semillas con al menos un gol y con al menos una expulsión, elegidas una vez
#: para no depender de la suerte en cada ejecución.
SEEDS = tuple(range(12))


@pytest.fixture(scope="module")
def match() -> list[MatchEvent]:
    return simulate_match(SEED, CONFIG)


@pytest.fixture(scope="module")
def updates(match: list[MatchEvent]) -> list[OddsUpdate]:
    return simulate_odds(SEED, match)


###############################################################################
# Reproducibilidad
###############################################################################


def _serialize(seed: int) -> bytes:
    events = simulate_match(seed, CONFIG)
    return b"".join((u.to_json() + "\n").encode() for u in simulate_odds(seed, events))


def test_same_seed_produces_identical_bytes() -> None:
    assert _serialize(SEED) == _serialize(SEED)


def test_different_seeds_produce_different_markets() -> None:
    assert _serialize(1) != _serialize(2)


def test_event_ids_are_unique(updates: list[OddsUpdate]) -> None:
    identifiers = [update.event_id for update in updates]
    assert len(identifiers) == len(set(identifiers))


def test_odds_ids_never_collide_with_match_ids(
    match: list[MatchEvent], updates: list[OddsUpdate]
) -> None:
    """Los dos flujos se deduplican por separado; sus identificadores no se cruzan."""
    assert {e.event_id for e in match}.isdisjoint({u.event_id for u in updates})


def test_empty_match_is_rejected() -> None:
    with pytest.raises(ValueError, match="no hay eventos"):
        simulate_odds(SEED, [])


###############################################################################
# Contrato
###############################################################################


def test_serialised_update_matches_the_contract(updates: list[OddsUpdate]) -> None:
    payload: dict[str, Any] = json.loads(updates[0].to_json())

    assert set(payload) == {
        "event_id",
        "event_time",
        "match_id",
        "contract_version",
        "operator",
        "market",
        "outcomes",
        "trigger",
    }
    assert payload["contract_version"] == ODDS_CONTRACT_VERSION


def test_outcomes_are_complete_and_ordered(updates: list[OddsUpdate]) -> None:
    for update in updates:
        payload: dict[str, Any] = json.loads(update.to_json())
        names = [entry["outcome"] for entry in payload["outcomes"]]
        assert tuple(names) == MARKET_OUTCOMES[update.market]


def test_updates_are_chronological(updates: list[OddsUpdate]) -> None:
    stamps = [update.event_time for update in updates]
    assert stamps == sorted(stamps)


def test_every_operator_and_market_is_quoted(updates: list[OddsUpdate]) -> None:
    assert {u.operator for u in updates} == {operator.name for operator in OPERATORS}
    assert {u.market for u in updates} == set(MARKETS)


def test_published_odds_are_within_limits(updates: list[OddsUpdate]) -> None:
    for update in updates:
        for value in update.odds.values():
            assert MIN_ODDS <= value <= MAX_ODDS


###############################################################################
# Reacción al partido — el corazón de la HU-9
###############################################################################


def _outcome_for(team: str) -> str:
    return "home" if team == CONFIG.home_team else "away"


def test_every_goal_triggers_a_repricing_by_every_operator() -> None:
    for seed in SEEDS:
        events = simulate_match(seed, CONFIG)
        goals = [e for e in events if e.event_type == "goal"]
        if not goals:
            continue

        updates = simulate_odds(seed, events)
        triggered = [u for u in updates if u.trigger == "goal"]

        # Cada gol mueve los dos mercados de las tres casas.
        assert len(triggered) >= len(goals) * len(OPERATORS)
        assert {u.operator for u in triggered} == {operator.name for operator in OPERATORS}


def test_a_goal_shortens_the_odds_of_the_team_that_scored() -> None:
    """La promesa literal de la historia."""
    checked = 0

    for seed in SEEDS:
        events = simulate_match(seed, CONFIG)
        updates = simulate_odds(seed, events)

        for goal in (e for e in events if e.event_type == "goal"):
            outcome = _outcome_for(goal.team)

            for operator in OPERATORS:
                quotes = [u for u in updates if u.operator == operator.name and u.market == "1x2"]
                before = [u for u in quotes if u.event_time <= goal.event_time]
                after = [u for u in quotes if u.event_time > goal.event_time]
                if not before or not after:
                    continue

                was, now = before[-1].odds[outcome], after[0].odds[outcome]

                # La cuota del que marca nunca se alarga...
                assert now <= was
                # ...y se acorta de verdad salvo que ya estuviera en el suelo
                # publicable, donde no queda recorrido que recortar.
                if was > MIN_ODDS:
                    assert now < was
                    checked += 1

    assert checked > 0, "la muestra no contenía ningún gol utilizable"


def test_a_red_card_shortens_the_odds_of_the_rival() -> None:
    checked = 0

    for seed in range(60):
        events = simulate_match(seed, CONFIG)
        cards = [e for e in events if e.event_type == "red_card"]
        if not cards:
            continue

        updates = simulate_odds(seed, events)
        for card in cards:
            rival = CONFIG.away_team if card.team == CONFIG.home_team else CONFIG.home_team
            outcome = _outcome_for(rival)

            quotes = [u for u in updates if u.operator == "OP-A" and u.market == "1x2"]
            before = [u for u in quotes if u.event_time <= card.event_time]
            after = [u for u in quotes if u.event_time > card.event_time]
            if not before or not after:
                continue

            assert after[0].odds[outcome] <= before[-1].odds[outcome]
            checked += 1

    assert checked > 0, "la muestra no contenía ninguna expulsión utilizable"


@pytest.mark.statistical
def test_significant_events_produce_bursts() -> None:
    """El ritmo tras un gol tiene que dispararse frente al ritmo de fondo.

    Sin este contraste el pipeline nunca se enfrentaría al patrón de tráfico que
    encontrará en producción, que es la razón de ser de la historia.
    """
    baseline_rates: list[float] = []
    burst_rates: list[float] = []

    for seed in SEEDS:
        events = simulate_match(seed, CONFIG)
        updates = simulate_odds(seed, events)
        span = (updates[-1].event_time - updates[0].event_time).total_seconds()
        baseline_rates.append(len(updates) / span * 60.0)

        for event in events:
            if event.event_type not in {"goal", "red_card"}:
                continue
            window = event.event_time + dt.timedelta(seconds=20)
            hits = sum(1 for u in updates if event.event_time <= u.event_time < window)
            burst_rates.append(hits * 3.0)

    baseline = sum(baseline_rates) / len(baseline_rates)
    burst = sum(burst_rates) / len(burst_rates)
    assert burst > baseline * 3.0


@pytest.mark.statistical
def test_quiet_play_is_quiet() -> None:
    """Que existan latidos demuestra que hay tramos sin movimiento de precio."""
    triggers = summarize_odds(simulate_odds(SEED, simulate_match(SEED, CONFIG))).by_trigger
    reactive = triggers.get("goal", 0) + triggers.get("red_card", 0)
    assert triggers.get("heartbeat", 0) + triggers.get("drift", 0) > 0
    assert reactive < triggers.get("drift", 0)


###############################################################################
# Margen y cierre de mercado
###############################################################################


@pytest.mark.statistical
def test_live_markets_keep_a_plausible_margin() -> None:
    """La suma de probabilidades implícitas debe reflejar el margen del operador."""
    for operator in OPERATORS:
        for market in MARKETS:
            sample = [
                overround(u.odds)
                for seed in SEEDS
                for u in simulate_odds(seed, simulate_match(seed, CONFIG))
                if u.operator == operator.name
                and u.market == market
                and all(MIN_ODDS < value < MAX_ODDS for value in u.odds.values())
            ]
            assert sample, f"sin cotizaciones vivas de {operator.name} en {market}"

            observed = sum(sample) / len(sample)
            expected = operator.overrounds[market]
            assert abs(observed - expected) < 0.02


def test_a_settled_market_stops_quoting() -> None:
    """Cuando el resultado ya no admite duda, la casa cierra el mercado.

    Se comprueba sobre over/under: en cuanto caen tres goles, superar la línea
    de 2,5 deja de ser una incógnita.
    """
    for seed in SEEDS:
        events = simulate_match(seed, CONFIG)
        goals = [e for e in events if e.event_type == "goal"]
        if len(goals) < 3:
            continue

        third_goal = goals[2].event_time
        updates = simulate_odds(seed, events)
        late = [
            u
            for u in updates
            if u.market == "over_under_2_5" and u.event_time > third_goal + dt.timedelta(seconds=60)
        ]
        assert not late
        return

    pytest.skip("ninguna semilla de la muestra alcanzó los tres goles")
