"""Plausibilidad estadística del partido simulado (criterio de verificación del OE-1).

Estas pruebas son la red que impide que un ajuste de constantes desplace la
simulación fuera del dominio plausible sin que nadie se entere. Los rangos son
deliberadamente anchos: acotan lo que sería un partido irreal, no persiguen una
media exacta.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable

import pytest

from gcperros.core import pitch
from gcperros.core.contracts import JsonValue
from gcperros.generators.match import (
    MatchConfig,
    MatchSummary,
    pass_completion_probability,
    shot_probability,
    simulate_match,
    summarize_match,
)

SAMPLE_SIZE = 60


@pytest.fixture(scope="module")
def sample() -> list[MatchSummary]:
    return [
        summarize_match(simulate_match(seed, MatchConfig(match_id=f"match-{seed:04d}")))
        for seed in range(SAMPLE_SIZE)
    ]


def _mean(sample: list[MatchSummary], extract: Callable[[MatchSummary], float]) -> float:
    return statistics.mean(extract(summary) for summary in sample)


def _touches_a_boundary(attrs: dict[str, JsonValue]) -> bool:
    for key, value in attrs.items():
        if key in {"x", "start_x", "end_x"} and value in {0.0, pitch.LENGTH}:
            return True
        if key in {"y", "start_y", "end_y"} and value in {0.0, pitch.WIDTH}:
            return True
    return False


@pytest.mark.statistical
def test_event_volume_matches_the_documented_range(sample: list[MatchSummary]) -> None:
    """La documentación declara 1.200-1.500 eventos por partido."""
    assert 1200 <= _mean(sample, lambda s: s.event_count) <= 1500


@pytest.mark.statistical
def test_pass_volume_and_completion_are_plausible(sample: list[MatchSummary]) -> None:
    assert 850 <= _mean(sample, lambda s: sum(s.passes.values())) <= 1150

    completion = _mean(sample, lambda s: sum(s.completed_passes.values())) / _mean(
        sample, lambda s: sum(s.passes.values())
    )
    assert 0.78 <= completion <= 0.88


@pytest.mark.statistical
def test_shots_goals_and_fouls_are_plausible(sample: list[MatchSummary]) -> None:
    assert 18 <= _mean(sample, lambda s: sum(s.shots.values())) <= 32
    assert 1.8 <= _mean(sample, lambda s: sum(s.goals.values())) <= 3.6
    assert 14 <= _mean(sample, lambda s: sum(s.fouls.values())) <= 30


@pytest.mark.statistical
def test_possession_count_is_plausible(sample: list[MatchSummary]) -> None:
    assert 180 <= _mean(sample, lambda s: sum(s.possessions.values())) <= 280


@pytest.mark.statistical
def test_simulated_goals_converge_to_accumulated_xg(sample: list[MatchSummary]) -> None:
    """Coherencia interna del modelo: los goles se muestrean de Bernoulli(xG).

    Sobre una muestra grande, el total de goles debe acercarse a la suma de xG.
    La tolerancia es el margen de un muestreo binomial de este tamaño, no un
    número elegido para que la prueba pase.
    """
    goals = sum(sum(s.goals.values()) for s in sample)
    total_xg = sum(sum(s.total_xg.values()) for s in sample)

    assert total_xg > 0
    assert abs(goals - total_xg) <= 3 * (total_xg**0.5)


@pytest.mark.statistical
def test_neither_team_is_systematically_favoured(sample: list[MatchSummary]) -> None:
    """El generador es simétrico: no hay ventaja de local codificada."""
    home = _mean(sample, lambda s: s.possessions["HOME"])
    away = _mean(sample, lambda s: s.possessions["AWAY"])
    assert abs(home - away) / (home + away) < 0.08


@pytest.mark.statistical
def test_events_do_not_pile_up_on_the_pitch_boundaries() -> None:
    """Regresión: el balón sale del campo, no se pega a la línea.

    Una versión anterior recortaba al rectángulo del campo la coordenada de
    todo pase desviado. El resultado era una acumulación artificial del 25 % de
    los eventos sobre las líneas, que habría contaminado el indicador de
    distribución espacial del juego.
    """
    events = [
        event
        for seed in range(10)
        for event in simulate_match(seed, MatchConfig(match_id=f"match-{seed:04d}"))
    ]

    on_boundary = sum(1 for event in events if _touches_a_boundary(event.attrs))
    assert on_boundary / len(events) < 0.06


@pytest.mark.statistical
def test_shots_are_not_taken_from_the_goal_line() -> None:
    """Regresión: rematar desde ``x = 105`` es físicamente imposible."""
    shots = [
        event
        for seed in range(10)
        for event in simulate_match(seed, MatchConfig(match_id=f"match-{seed:04d}"))
        if event.event_type == "shot"
    ]

    from_the_goal_line = sum(1 for shot in shots if shot.attrs["x"] == pitch.LENGTH)
    assert from_the_goal_line / len(shots) < 0.03


@pytest.mark.statistical
def test_shot_quality_matches_the_domain() -> None:
    """El xG medio por remate en fútbol profesional ronda 0,10-0,12."""
    shots = [
        event
        for seed in range(20)
        for event in simulate_match(seed, MatchConfig(match_id=f"match-{seed:04d}"))
        if event.event_type == "shot"
    ]

    mean_xg = statistics.mean(float(str(shot.attrs["xg"])) for shot in shots)
    assert 0.08 <= mean_xg <= 0.16


def test_pass_completion_falls_towards_the_opponent_box() -> None:
    """Propiedad exigida explícitamente por la HU-8."""
    probabilities = [pass_completion_probability(x) for x in (0, 20, 40, 60, 80, 105)]
    assert probabilities == sorted(probabilities, reverse=True)
    assert probabilities[0] > probabilities[-1]


def test_no_shots_are_taken_from_outside_the_shooting_zone() -> None:
    assert shot_probability(0.0) == 0.0
    assert shot_probability(50.0) == 0.0
    assert shot_probability(104.0) > 0.0


def test_shot_propensity_grows_towards_goal() -> None:
    values = [shot_probability(x) for x in (76, 85, 95, 105)]
    assert values == sorted(values)
