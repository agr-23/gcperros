"""La vista provisional (sección 3): lo exacto, en cuanto llega, sin corregirse nunca.

Con un margen de 10 s no se puede cumplir el SLA de 2 s con la vista definitiva:
el margen es lo que compra la corrección. La provisional enseña lo aplicado más
lo que espera a la marca de agua, así que un gol aparece al llegar. Contar no
depende del orden, y por eso lo exacto que enseña es siempre el de todo lo
aceptado hasta ese momento.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from gcperros.core.basketball_stats import summarize_basketball
from gcperros.core.contracts import MatchEvent
from gcperros.core.stats import summarize_events
from gcperros.engine.basketball_state import basketball_engine
from gcperros.engine.harness import DEFAULT_SCENARIOS, degrade
from gcperros.engine.pipeline import MatchEngine, Outcome, StreamEngine
from gcperros.engine.sport_harness import BASKETBALL, FOOTBALL, SportProfile

SCENARIOS = {scenario.name: scenario for scenario in DEFAULT_SCENARIOS}


def _goals(events: list[MatchEvent]) -> int:
    return sum(summarize_events(events).goals.values())


def _points(events: list[MatchEvent]) -> int:
    return sum(summarize_basketball(events).points.values())


def _football() -> StreamEngine[object]:
    return MatchEngine()


def _basketball() -> StreamEngine[object]:
    return basketball_engine()


CASES = [
    (FOOTBALL, _football, _goals, "goals"),
    (BASKETBALL, _basketball, _points, "points"),
]
IDS = ["football", "basketball"]


@pytest.mark.parametrize(("sport", "engine", "exact", "field"), CASES, ids=IDS)
@pytest.mark.parametrize("scenario", ["limpio", "hostil"])
def test_the_provisional_score_is_everything_accepted_so_far(
    sport: SportProfile,
    engine: Callable[[], StreamEngine[object]],
    exact: Callable[[list[MatchEvent]], int],
    field: str,
    scenario: str,
) -> None:
    live = engine()
    accepted: dict[str, MatchEvent] = {}

    for event in degrade(sport.simulate(3), SCENARIOS[scenario], 3):
        if live.process(event) is Outcome.ACCEPTED:
            accepted[event.event_id] = event
        shown = sum(getattr(live.provisional(), field).values())
        assert shown == exact(sorted(accepted.values(), key=lambda e: (e.event_time, e.event_id)))


@pytest.mark.parametrize(("sport", "engine"), [case[:2] for case in CASES], ids=IDS)
def test_when_the_window_closes_the_provisional_and_final_views_agree(
    sport: SportProfile, engine: Callable[[], StreamEngine[object]]
) -> None:
    live = engine()
    for event in sport.simulate(3):
        live.process(event)
    live.flush()

    assert live.provisional() == live.result().summary


def test_a_goal_shows_up_provisionally_before_its_margin_passes() -> None:
    events = FOOTBALL.simulate(3)
    goal = next(e for e in events if e.event_type == "goal")
    live = MatchEngine()
    for event in events[: events.index(goal) + 1]:
        live.process(event)

    assert sum(live.result().summary.goals.values()) == 0  # la definitiva aún espera
    assert sum(live.provisional().goals.values()) == 1


def test_the_provisional_view_does_not_touch_the_live_state() -> None:
    live = MatchEngine()
    for event in FOOTBALL.simulate(3)[:50]:
        live.process(event)
    before = live.result().summary

    live.provisional()

    assert live.result().summary == before
