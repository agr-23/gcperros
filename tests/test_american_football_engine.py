"""El motor de siempre con el tercer deporte (sección 22).

Deduplicación, marca de agua y posesión no cambian ni una línea: el fútbol
americano entra con su estado inyectado y se mide con la misma vara que los
otros dos, con el margen que sus datos eligieron.
"""

from __future__ import annotations

import pytest

from gcperros.core.american_football_stats import summarize_american_football
from gcperros.engine.american_football_state import (
    AMERICAN_FOOTBALL_ALLOWED_LATENESS_S,
    american_football_engine,
)
from gcperros.engine.harness import DEFAULT_SCENARIOS
from gcperros.engine.sport_harness import AMERICAN_FOOTBALL, SPORTS, run_sport_harness
from gcperros.governance.traceability import audit

SCENARIOS = {scenario.name: scenario for scenario in DEFAULT_SCENARIOS}


def test_the_third_sport_is_measured_with_the_same_yardstick() -> None:
    assert SPORTS["american_football"] is AMERICAN_FOOTBALL
    assert AMERICAN_FOOTBALL.allowed_lateness_s == AMERICAN_FOOTBALL_ALLOWED_LATENESS_S == 15.0


@pytest.mark.parametrize("seed", [0, 7, 39])
def test_every_committed_scenario_passes_with_its_margin(seed: int) -> None:
    results = run_sport_harness(AMERICAN_FOOTBALL, AMERICAN_FOOTBALL.simulate(seed), seed)

    assert all(result.passed for result in results), [
        r.scenario.name for r in results if not r.passed
    ]


def test_ten_seconds_lose_a_field_goal_and_the_harness_catches_it() -> None:
    """El margen no se eligió a ojo: con 10 s, un gol de campo llega tarde."""
    (result,) = run_sport_harness(
        AMERICAN_FOOTBALL,
        AMERICAN_FOOTBALL.simulate(39),
        39,
        scenarios=(SCENARIOS["hostil"],),
        allowed_lateness_s=10.0,
    )

    assert not result.passed and result.divergence.exact == 3


def test_the_live_state_projects_to_the_batch_summary() -> None:
    events = AMERICAN_FOOTBALL.simulate(7)

    live = american_football_engine().process_all(events).summary

    assert live == summarize_american_football(events)


def test_every_number_explains_where_it_comes_from() -> None:
    engine = american_football_engine()
    engine.process_all(AMERICAN_FOOTBALL.simulate(7))

    trail = audit(engine.state)
    kicks = [e for e in trail.explanations if e.indicator == "kick_expected_points"]

    assert kicks and all(e.model_versions == {"kick": "kick-1.0.0"} for e in kicks)
    assert all(e.lineage.event_count > 0 for e in trail.explanations if e.value)
