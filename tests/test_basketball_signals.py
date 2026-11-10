"""La señal de discrepancia, el mismo detector con el baloncesto inyectado (#90)."""

from __future__ import annotations

from datetime import timedelta
from functools import cache

import pytest

from gcperros.core.basketball_matchstate import points_scored
from gcperros.core.contracts import MatchEvent, OddsUpdate
from gcperros.engine.basketball_market import (
    BASKETBALL_THRESHOLD,
    BasketballMarketReader,
    detect_basketball_discrepancies,
)
from gcperros.engine.signals import DEFAULT_THRESHOLD, DiscrepancyDetector
from gcperros.generators.basketball import BasketballConfig, simulate_basketball
from gcperros.generators.basketball_odds import BASKETBALL_OPERATORS, simulate_basketball_odds
from gcperros.generators.odds import REACTION_JITTER_S

TEAMS = ("BOS", "LAL")


@cache
def _flows(seed: int) -> tuple[tuple[MatchEvent, ...], tuple[OddsUpdate, ...]]:
    events = simulate_basketball(seed, BasketballConfig(home_team="BOS", away_team="LAL"))
    return tuple(events), tuple(simulate_basketball_odds(seed, events, TEAMS))


def test_the_same_detector_finds_basketball_signals() -> None:
    events, odds = _flows(1)

    signals = detect_basketball_discrepancies(list(events), list(odds), TEAMS)

    assert signals
    assert {s.market for s in signals} <= {"moneyline", "total_points"}
    assert all(s.magnitude >= BASKETBALL_THRESHOLD for s in signals)
    assert all(s.model_version == "basketball-odds-1.0.0" for s in signals)


def test_every_signal_is_a_price_left_stale_by_a_basket() -> None:
    """Como en fútbol: lo que detecta es la ventana en que una casa aún no repreció."""
    events, odds = _flows(2)
    baskets = [e.event_time for e in events if points_scored(e)]
    slowest = max(op.reaction_delay_s for op in BASKETBALL_OPERATORS) + REACTION_JITTER_S[1]

    for signal in detect_basketball_discrepancies(list(events), list(odds), TEAMS):
        assert any(
            timedelta(0) <= signal.detected_at - b <= timedelta(seconds=slowest) for b in baskets
        )


def test_a_signal_traces_back_to_its_quote_and_the_score_behind_it() -> None:
    events, odds = _flows(3)

    signal = detect_basketball_discrepancies(list(events), list(odds), TEAMS)[0]

    assert signal.lineage.indicator == "discrepancy_signal"
    assert signal.lineage.scope == f"{signal.operator}/{signal.market}"
    assert signal.lineage.event_count >= 2


def test_the_basketball_threshold_fires_less_than_the_football_one() -> None:
    events, odds = _flows(4)

    strict = detect_basketball_discrepancies(list(events), list(odds), TEAMS)
    loose = detect_basketball_discrepancies(list(events), list(odds), TEAMS, DEFAULT_THRESHOLD)

    assert BASKETBALL_THRESHOLD == 0.10
    assert len(strict) < len(loose) / 2


def test_each_reader_ignores_the_other_sports_markets() -> None:
    _, odds = _flows(5)
    football = DiscrepancyDetector(threshold=0.01)

    assert all(football.evaluate(update) == [] for update in odds)
    with pytest.raises(TypeError, match="fútbol"):
        _ = DiscrepancyDetector(reader=BasketballMarketReader(*TEAMS)).state


def test_the_game_minute_counts_quarters_and_overtime() -> None:
    reader = BasketballMarketReader(*TEAMS)
    events, _ = _flows(6)
    for event in events:
        reader.apply(event)
        if event.attrs["period"] == 3 and event.attrs["clock_s"] == 600.0:
            assert reader.minute == pytest.approx(20.0)
    assert reader.minute >= 40.0
