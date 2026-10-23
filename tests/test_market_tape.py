"""La cinta del mercado de la demostración (#32)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from gcperros.core.contracts import MatchEvent, OddsUpdate
from gcperros.demo.market import MarketTape
from gcperros.engine.signals import detect_discrepancies
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.odds import simulate_odds

CONFIG = MatchConfig(match_id="match-0032", home_team="RMA", away_team="BAR")
SEED = 65


@pytest.fixture(scope="module")
def streams() -> tuple[list[MatchEvent], list[OddsUpdate]]:
    events = simulate_match(SEED, CONFIG)
    return events, simulate_odds(SEED, events)


def test_at_the_final_whistle_the_signals_are_the_batch_signals(
    streams: tuple[list[MatchEvent], list[OddsUpdate]],
) -> None:
    """La cinta no inventa señales: alimenta al mismo detector que el batch."""
    events, odds = streams
    tape = MarketTape(events, odds)
    end = max(events[-1].event_time, odds[-1].event_time)

    # A pasos de un minuto, como la llevaría el reloj de la repetición.
    instant = events[0].event_time
    while instant <= end:
        tape.advance_to(instant)
        instant += timedelta(minutes=1)
    tape.advance_to(end)

    assert tape.signals == tuple(detect_discrepancies(events, odds))
    assert tape.view().total_signals > 0


def test_before_kickoff_only_the_opening_prices_exist(
    streams: tuple[list[MatchEvent], list[OddsUpdate]],
) -> None:
    events, odds = streams
    tape = MarketTape(events, odds)
    tape.advance_to(events[0].event_time - timedelta(seconds=1))
    assert tape.view().operators == {}

    tape.advance_to(events[0].event_time)
    view = tape.view()
    assert sorted(view.operators) == ["OP-A", "OP-B", "OP-C"]
    assert (view.recent_signals, view.total_signals) == ((), 0)


def test_probabilities_are_complete_and_without_margin(
    streams: tuple[list[MatchEvent], list[OddsUpdate]],
) -> None:
    events, odds = streams
    tape = MarketTape(events, odds)
    tape.advance_to(events[0].event_time + timedelta(minutes=30))
    view = tape.view()

    for book in [view.model, *view.operators.values()]:
        assert set(book) == {"home", "draw", "away"}
        assert sum(book.values()) == pytest.approx(1.0, abs=1e-3)


def test_recent_signals_come_newest_first_and_are_capped(
    streams: tuple[list[MatchEvent], list[OddsUpdate]],
) -> None:
    events, odds = streams
    tape = MarketTape(events, odds)
    new = tape.advance_to(events[-1].event_time)
    view = tape.view(recent=5)

    assert new == view.total_signals == len(tape.signals)
    assert len(view.recent_signals) == 5
    assert view.recent_signals[0] == tape.signals[-1]
    assert tape.view(recent=0).recent_signals == ()


def test_going_back_in_time_changes_nothing(
    streams: tuple[list[MatchEvent], list[OddsUpdate]],
) -> None:
    events, odds = streams
    tape = MarketTape(events, odds)
    tape.advance_to(events[0].event_time + timedelta(minutes=60))
    before = tape.view()

    assert tape.advance_to(events[0].event_time) == 0
    assert tape.view() == before
