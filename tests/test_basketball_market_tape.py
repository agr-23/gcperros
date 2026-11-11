"""La cinta del mercado con baloncesto: su ganador y sus señales, verificables (#92)."""

from __future__ import annotations

from gcperros.demo.market import MarketTape
from gcperros.demo.signal_trace import trace_signal
from gcperros.engine.basketball_market import BASKETBALL_THRESHOLD, BasketballMarketReader
from gcperros.generators.basketball import BasketballConfig, simulate_basketball
from gcperros.generators.basketball_odds import simulate_basketball_odds

TEAMS = ("BOS", "LAL")
EVENTS = simulate_basketball(65, BasketballConfig("demo-bkb-65", *TEAMS))


def _tape_at_the_end() -> MarketTape:
    odds = simulate_basketball_odds(65, EVENTS, TEAMS)
    tape = MarketTape(EVENTS, odds, BASKETBALL_THRESHOLD, BasketballMarketReader(*TEAMS))
    tape.advance_to(EVENTS[-1].event_time)
    return tape


def test_the_tape_shows_the_winner_market_without_a_draw() -> None:
    view = _tape_at_the_end().view()

    assert set(view.model) == {"home", "away"}
    assert set(view.operators) == {"OP-A", "OP-B", "OP-C"}
    assert all(set(book) == {"home", "away"} for book in view.operators.values())


def test_every_basketball_signal_traces_back_with_a_verified_fingerprint() -> None:
    """Un tiro y su rebote comparten instante: el tiempo no basta para saber qué vio el detector."""
    tape = _tape_at_the_end()

    assert tape.signals
    assert all(trace_signal(tape, i, lambda _t: 0).verified for i in range(len(tape.signals)))


def test_the_tape_remembers_what_the_detector_had_seen() -> None:
    tape = _tape_at_the_end()

    seen = [len(tape.events_behind(i)) for i in range(len(tape.signals))]
    assert seen == sorted(seen)
    assert seen[-1] <= len(tape.consumed_events)
