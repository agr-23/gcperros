"""Calibración del generador de baloncesto contra los rangos de referencia (#88).

Si un cambio de constantes saca la simulación del baloncesto plausible, esta
prueba rompe la construcción en vez de dejarlo pasar. Los rangos y su fuente
están en ``docs/decisiones-de-diseno.md``, sección 18.
"""

from __future__ import annotations

import statistics
from functools import cache
from pathlib import Path

import pytest

from gcperros.core.basketball_stats import BasketballSummary, summarize_basketball
from gcperros.generators.basketball import simulate_basketball
from gcperros.generators.cli import main

SAMPLE = 100


@cache
def _summaries() -> tuple[BasketballSummary, ...]:
    return tuple(summarize_basketball(simulate_basketball(seed)) for seed in range(SAMPLE))


def _per_team(metric: str) -> float:
    """Media por equipo de una métrica derivada del resumen."""
    values: list[float] = []
    for s in _summaries():
        home, away = list(s.points)
        for team, rival in ((home, away), (away, home)):
            attempts = s.two_attempted[team] + s.three_attempted[team]
            rebounds = s.offensive_rebounds[team] + s.defensive_rebounds[rival]
            values.append(
                {
                    "possessions": s.possessions[team],
                    "points": s.points[team],
                    "points_per_possession": s.points[team] / s.possessions[team],
                    "three_point_rate": s.three_attempted[team] / attempts,
                    "two_point_pct": s.two_made[team] / s.two_attempted[team],
                    "three_point_pct": s.three_made[team] / s.three_attempted[team],
                    "free_throw_rate": s.free_throws_attempted[team] / attempts,
                    "free_throw_pct": s.free_throws_made[team] / s.free_throws_attempted[team],
                    "offensive_rebound_pct": s.offensive_rebounds[team] / rebounds,
                    "turnovers": s.turnovers[team],
                    "fouls": s.fouls[team],
                    "timeouts": s.timeouts[team],
                }[metric]
            )
    return statistics.fmean(values)


@pytest.mark.parametrize(
    ("metric", "low", "high"),
    [
        ("possessions", 68, 76),
        ("points", 75, 88),
        ("points_per_possession", 1.05, 1.18),
        ("three_point_rate", 0.35, 0.45),
        ("two_point_pct", 0.50, 0.57),
        ("three_point_pct", 0.32, 0.38),
        ("free_throw_rate", 0.25, 0.40),
        ("free_throw_pct", 0.72, 0.80),
        ("offensive_rebound_pct", 0.24, 0.32),
        ("turnovers", 10, 15),
        ("fouls", 17, 23),
        ("timeouts", 2, 5),
    ],
)
def test_the_simulation_stays_in_the_reference_range(metric: str, low: float, high: float) -> None:
    assert low <= _per_team(metric) <= high


def test_expected_points_track_the_real_points() -> None:
    """Los puntos esperados son un buen estimador: en media no se desvían."""
    real = statistics.fmean(sum(s.points.values()) for s in _summaries())
    expected = statistics.fmean(sum(s.expected_points.values()) for s in _summaries())

    assert expected == pytest.approx(real, rel=0.03)


def test_the_cli_generates_basketball_byte_for_byte(tmp_path: Path) -> None:
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"

    for target in (first, second):
        assert main(["--sport", "basketball", "--seed", "42", "--out", str(target)]) == 0

    assert first.read_bytes() == second.read_bytes()
    assert b'"event_type":"free_throw"' in first.read_bytes()


def test_the_cli_summary_reports_the_score(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = str(tmp_path / "match.jsonl")
    assert main(["--sport", "basketball", "--seed", "7", "--summary", "--out", out]) == 0

    assert "puntos=" in capsys.readouterr().err
