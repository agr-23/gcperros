"""Los dos parámetros del fútbol que el baloncesto no podía heredar (#91).

El margen de la marca de agua y el corte de juego parado de la posesión se
eligieron midiendo partidos de fútbol. Medidos con baloncesto, los dos cambian.
"""

from __future__ import annotations

import pytest

from gcperros.core.basketball_stats import summarize_basketball
from gcperros.core.possession import MAX_IN_PLAY_GAP_S, PossessionTracker
from gcperros.engine.basketball_state import (
    BASKETBALL_ALLOWED_LATENESS_S,
    BASKETBALL_MAX_IN_PLAY_GAP_S,
    basketball_engine,
)
from gcperros.generators.basketball import simulate_basketball
from gcperros.generators.perturbation import inject_disorder, inject_duplicates

#: El desorden con el que se eligió el margen del fútbol, y el escenario hostil.
SCENARIOS = {"medio": 0.0, "hostil": 0.15}


def _points_lost(margin_s: float) -> int:
    """Cuántos partidos degradados acaban con un marcador distinto al real."""
    lost = 0
    for seed in range(12):
        events = simulate_basketball(seed)
        real = summarize_basketball(events).points
        for duplicate_rate in SCENARIOS.values():
            delivered = events
            if duplicate_rate:
                delivered, _ = inject_duplicates(delivered, seed, rate=duplicate_rate)
            delivered, _ = inject_disorder(delivered, seed + 1, mean_delay_s=2.0, max_delay_s=30.0)
            if basketball_engine(margin_s).process_all(delivered).summary.points != real:
                lost += 1
    return lost


def test_the_football_margin_loses_baskets_and_the_basketball_one_does_not() -> None:
    """Con un evento cada ~12 s, el que adelanta a otro ya le saca más de 10 s."""
    assert _points_lost(10.0) > 0
    assert _points_lost(BASKETBALL_ALLOWED_LATENESS_S) == 0


def test_the_basketball_engine_uses_its_own_parameters() -> None:
    assert BASKETBALL_ALLOWED_LATENESS_S == 15.0
    assert BASKETBALL_MAX_IN_PLAY_GAP_S == 24.0


@pytest.mark.parametrize("seed", [3, 8])
def test_the_shot_clock_cutoff_keeps_the_live_time_the_football_one_threw_away(seed: int) -> None:
    """Con el corte de 10 s del fútbol, el baloncesto perdía el 90 % de su tiempo vivo."""
    events = simulate_basketball(seed)
    football_cutoff = PossessionTracker(max_in_play_gap_s=MAX_IN_PLAY_GAP_S)
    for event in events:
        football_cutoff.apply(event)

    counted = basketball_engine().process_all(events).possession.running_seconds

    assert sum(counted.values()) > 5 * sum(football_cutoff.snapshot().running_seconds.values())
    assert sum(counted.values()) > 35 * 60, "los 40 minutos de juego, con algún parón corto"
