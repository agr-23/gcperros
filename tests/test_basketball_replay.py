"""La repetición del baloncesto: el mismo motor, con su reloj de cuartos (#92)."""

from __future__ import annotations

from gcperros.core import court
from gcperros.demo.replay import BasketballReplay
from gcperros.demo.trace import trace_indicator
from gcperros.generators.basketball import BasketballConfig, simulate_basketball

EVENTS = simulate_basketball(65, BasketballConfig("demo-bkb-65", "BOS", "LAL"))


def test_the_clock_reads_quarters_and_the_game_clock() -> None:
    replay = BasketballReplay(EVENTS)
    assert replay.clock().phase == "previa"

    replay.advance_to(5 * 60)
    clock = replay.clock()

    assert clock.phase == "cuarto-1"
    assert clock.game_clock_s is not None
    assert 0 < clock.game_clock_s < court.PERIOD_DURATION_S
    assert clock.minute == int((court.PERIOD_DURATION_S - clock.game_clock_s) / 60)


def test_the_clock_stops_between_quarters_and_ends_at_the_final_buzzer() -> None:
    replay = BasketballReplay(EVENTS)
    phases = set()
    for second in range(0, int(replay.duration_s) + 60, 20):
        replay.advance_to(second)
        phases.add(replay.clock().phase)

    assert {"cuarto-1", "cuarto-2", "cuarto-3", "cuarto-4", "descanso", "final"} <= phases
    assert replay.clock().minute >= court.REGULATION_PERIODS * court.PERIOD_DURATION_S // 60


def test_a_basketball_number_traces_back_with_a_verified_fingerprint() -> None:
    replay = BasketballReplay(EVENTS)
    replay.advance_to(replay.duration_s)

    trace = trace_indicator(replay, "points", "BOS")

    assert trace.verified
    assert trace.events
    assert {event.event_type for event in trace.events} <= {"shot", "free_throw"}
