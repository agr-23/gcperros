"""Separación entre planos contra los umbrales declarados (#17)."""

from __future__ import annotations

import pytest

from gcperros.core.contracts import MatchEvent
from gcperros.core.divergence import (
    Divergence,
    PlaneResult,
    Thresholds,
    batch_result,
    measure,
)
from gcperros.core.stats import MatchSummary
from gcperros.engine.pipeline import MatchEngine
from gcperros.generators.match import MatchConfig, simulate_match

CONFIG = MatchConfig(match_id="match-0017", home_team="RMA", away_team="BAR")
SEED = 20260826


def _summary(
    event_count: int = 100,
    goals: dict[str, int] | None = None,
    total_xg: dict[str, float] | None = None,
) -> MatchSummary:
    return MatchSummary(
        event_count=event_count,
        goals=goals if goals is not None else {"RMA": 2, "BAR": 1},
        shots={"RMA": 8, "BAR": 5},
        total_xg=total_xg if total_xg is not None else {"RMA": 1.2, "BAR": 0.7},
        passes={"RMA": 40, "BAR": 30},
        completed_passes={"RMA": 34, "BAR": 25},
        fouls={"RMA": 3, "BAR": 4},
        red_cards={"RMA": 0, "BAR": 0},
        possessions={"RMA": 10, "BAR": 9},
    )


def _plane(summary: MatchSummary | None = None, **possession: float) -> PlaneResult:
    return PlaneResult(summary or _summary(), possession or {"RMA": 300.0, "BAR": 200.0})


###############################################################################
# Los umbrales declarados
###############################################################################


def test_identical_planes_do_not_diverge() -> None:
    divergence = measure(_plane(), _plane())

    assert divergence == Divergence(possession_share=0.0, total_xg=0.0, goals=0, events=0)
    assert divergence.passes()


def test_possession_within_one_percent_passes() -> None:
    divergence = measure(_plane(RMA=300.0, BAR=200.0), _plane(RMA=297.0, BAR=203.0))
    assert divergence.passes()


def test_possession_beyond_one_percent_is_a_breach() -> None:
    divergence = measure(_plane(RMA=300.0, BAR=200.0), _plane(RMA=280.0, BAR=220.0))

    breach = next(b for b in divergence.breaches() if b.indicator == "possession_share")
    assert breach.observed == pytest.approx(0.04)
    assert breach.limit == 0.01


def test_expected_goals_have_their_own_margin() -> None:
    observed = _plane(_summary(total_xg={"RMA": 1.24, "BAR": 0.7}))
    assert measure(_plane(), observed).passes()

    observed = _plane(_summary(total_xg={"RMA": 1.30, "BAR": 0.7}))
    assert [b.indicator for b in measure(_plane(), observed).breaches()] == ["total_xg"]


def test_a_lost_goal_admits_no_margin() -> None:
    """Un gol no es «casi igual»: es un dato que faltó."""
    observed = _plane(_summary(goals={"RMA": 1, "BAR": 1}))
    breaches = measure(_plane(), observed).breaches()

    assert [b.indicator for b in breaches] == ["goals"]
    assert breaches[0].limit == 0.0


def test_a_lost_event_admits_no_margin() -> None:
    observed = _plane(_summary(event_count=99))
    divergence = measure(_plane(), observed)

    assert divergence.events == 1
    assert [b.indicator for b in divergence.breaches()] == ["events"]


def test_a_late_event_that_was_counted_is_not_a_loss() -> None:
    """La HU-12 descarta tardíos y los cuenta: la contabilidad cierra."""
    observed = PlaneResult(_summary(event_count=99), {"RMA": 300.0, "BAR": 200.0}, dropped_late=1)

    assert measure(_plane(), observed).events == 0


def test_a_team_missing_entirely_counts_as_zero() -> None:
    """Si el motor perdió todos los eventos de un equipo, la brecha es total."""
    observed = _plane(_summary(total_xg={"RMA": 1.2}, goals={"RMA": 2}), RMA=300.0)
    divergence = measure(_plane(), observed)

    assert divergence.total_xg == pytest.approx(0.7)
    assert not divergence.passes()


def test_thresholds_can_be_tightened() -> None:
    observed = _plane(_summary(total_xg={"RMA": 1.21, "BAR": 0.7}))
    assert measure(_plane(), observed).passes()
    assert not measure(_plane(), observed).passes(Thresholds(total_xg=0.005))


###############################################################################
# Sobre el pipeline real
###############################################################################


def _engine_result(events: list[MatchEvent]) -> PlaneResult:
    result = MatchEngine(allowed_lateness_s=30.0).process_all(events)
    return PlaneResult(result.summary, result.possession.running_seconds)


def test_a_clean_stream_diverges_nowhere() -> None:
    events = simulate_match(SEED, CONFIG)
    divergence = measure(batch_result(events), _engine_result(events))

    assert divergence.passes()
    assert divergence.events == 0
