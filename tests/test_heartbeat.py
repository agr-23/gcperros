"""El latido de la marca de agua (sección 3): la espera baja, la corrección no cambia.

Sin latido, la marca de agua sólo avanza cuando llega algo, y en una pausa del
juego lo último que pasó espera hasta que el juego se reanuda: el p95 triplica
el margen y el máximo es el descanso entero. Con latido, cada evento sale en
cuanto pasa su margen.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import pytest

from gcperros.engine.basketball_state import BASKETBALL_ALLOWED_LATENESS_S, basketball_engine
from gcperros.engine.harness import DEFAULT_SCENARIOS, degrade
from gcperros.engine.pipeline import MatchEngine, StreamEngine
from gcperros.engine.sport_harness import BASKETBALL, FOOTBALL, SportProfile
from gcperros.engine.watermark import DEFAULT_ALLOWED_LATENESS_S, WatermarkReorderer
from gcperros.generators.match import simulate_match

SCENARIOS = {scenario.name: scenario for scenario in DEFAULT_SCENARIOS}
HEARTBEAT_S = 1.0


def _football() -> StreamEngine[object]:
    return MatchEngine()


def _basketball() -> StreamEngine[object]:
    return basketball_engine()


CASES = [
    (FOOTBALL, _football, DEFAULT_ALLOWED_LATENESS_S),
    (BASKETBALL, _basketball, BASKETBALL_ALLOWED_LATENESS_S),
]


@pytest.mark.parametrize(("sport", "engine", "margin"), CASES, ids=["football", "basketball"])
@pytest.mark.parametrize("scenario", ["limpio", "desorden-medio", "hostil"])
def test_the_heartbeat_changes_the_wait_and_nothing_else(
    sport: SportProfile, engine: Callable[[], StreamEngine[object]], margin: float, scenario: str
) -> None:
    delivered = degrade(sport.simulate(7), SCENARIOS[scenario], 7)

    without = engine().process_all(delivered)
    beating = engine().process_all(delivered, heartbeat_s=HEARTBEAT_S)

    assert beating.summary == without.summary
    assert beating.watermark.dropped_late == without.watermark.dropped_late
    assert beating.possession.running_seconds == without.possession.running_seconds
    # Cada evento sale en cuanto pasa su margen, más un latido como mucho.
    assert beating.latency.max_s <= margin + HEARTBEAT_S + 1e-6
    assert without.latency.max_s > 10 * margin  # el descanso entero, sin latido


def test_a_beat_releases_what_the_margin_already_passed() -> None:
    first, second, *_ = simulate_match(7)
    reorderer = WatermarkReorderer(allowed_lateness_s=10.0)
    reorderer.push(first)
    reorderer.push(second)

    assert reorderer.tick(first.event_time + timedelta(seconds=5)) == []
    released = reorderer.tick(second.event_time + timedelta(seconds=10))

    assert released == sorted([first, second], key=lambda e: (e.event_time, e.event_id))
    assert reorderer.buffered == 0


def test_the_watermark_never_goes_back_with_a_beat() -> None:
    first, *_ = simulate_match(7)
    reorderer = WatermarkReorderer(allowed_lateness_s=10.0)
    reorderer.push(first)
    reorderer.tick(first.event_time + timedelta(seconds=60))
    ahead = reorderer.watermark

    reorderer.tick(first.event_time)

    assert reorderer.watermark == ahead


def test_before_anything_arrives_a_beat_does_nothing() -> None:
    assert WatermarkReorderer().tick(simulate_match(7)[0].event_time) == []
    assert MatchEngine().tick(simulate_match(7)[0].event_time) == 0
