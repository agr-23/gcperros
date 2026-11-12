"""El generador de fútbol americano: determinista, dentro de su contrato y calibrado.

La calibración se compara contra medias por equipo de la NFL, con rangos
anchos: el generador es un partido plausible, no una réplica de la liga. Si
alguien cambia una constante y el partido deja de parecer fútbol americano,
estas pruebas lo dicen.
"""

from __future__ import annotations

import itertools
import statistics
from pathlib import Path

import pytest

from gcperros.core import gridiron, kicking
from gcperros.core.american_football_stats import summarize_american_football
from gcperros.core.schema import AMERICAN_FOOTBALL_EVENT_SCHEMA
from gcperros.generators import cli
from gcperros.generators.american_football import simulate_american_football
from gcperros.governance.validation import validate_message

MATCHES = [simulate_american_football(seed) for seed in range(60)]
SUMMARIES = [summarize_american_football(events) for events in MATCHES]


def _per_team(field: str) -> float:
    values: list[float] = [v for s in SUMMARIES for v in getattr(s, field).values()]
    return statistics.mean(values)


def test_the_same_seed_gives_the_same_game_byte_for_byte() -> None:
    first = [e.to_json() for e in simulate_american_football(7)]

    assert first == [e.to_json() for e in simulate_american_football(7)]
    assert first != [e.to_json() for e in simulate_american_football(8)]


def test_every_event_it_produces_meets_its_own_contract() -> None:
    for event in MATCHES[0] + MATCHES[1]:
        assert validate_message(event.to_json(), AMERICAN_FOOTBALL_EVENT_SCHEMA).is_valid


@pytest.mark.parametrize(
    ("field", "low", "high"),
    [
        ("points", 17, 26),
        ("touchdowns", 1.9, 2.9),
        ("field_goals_made", 1.1, 2.0),
        ("plays", 55, 70),
        ("yards", 300, 400),
        ("turnovers", 0.9, 1.6),
        ("punts", 3.5, 5.5),
        ("possessions", 10, 13),
    ],
)
def test_a_game_looks_like_american_football(field: str, low: float, high: float) -> None:
    assert low <= _per_team(field) <= high


def test_the_points_are_what_the_events_say_they_are_worth() -> None:
    for events, summary in zip(MATCHES, SUMMARIES, strict=True):
        made = [e for e in events if e.attrs.get("made") is True]
        expected = (
            gridiron.TOUCHDOWN * sum(1 for e in events if e.event_type == "touchdown")
            + gridiron.FIELD_GOAL * sum(1 for e in made if e.event_type == "field_goal")
            + sum(
                kicking.conversion_value(str(e.attrs["kind"]))
                for e in made
                if e.event_type == "conversion"
            )
            + gridiron.SAFETY * sum(1 for e in events if e.event_type == "safety")
        )
        assert sum(summary.points.values()) == expected


def test_the_kick_model_follows_the_league() -> None:
    assert kicking.field_goal_probability(30) == pytest.approx(0.89)
    assert kicking.field_goal_probability(50) == pytest.approx(0.65)
    assert kicking.field_goal_probability(110) == kicking.FIELD_GOAL_FLOOR


def test_between_plays_the_clock_runs_and_after_a_score_it_stops() -> None:
    """Huecos vivos de hasta 40 s y parones de más de 55: la banda vacía del corte."""
    gaps = [
        (b.event_time - a.event_time).total_seconds()
        for events in MATCHES[:10]
        for a, b in itertools.pairwise(events)
    ]

    assert max(g for g in gaps if g < 50) <= gridiron.PLAY_CLOCK_S
    assert not [g for g in gaps if 41 < g < 55]


def test_the_command_writes_a_game(tmp_path: Path) -> None:
    out = tmp_path / "nfl.jsonl"

    assert cli.main(["--sport", "american_football", "--seed", "7", "--out", str(out)]) == 0
    assert len(out.read_text(encoding="utf-8").splitlines()) == len(simulate_american_football(7))
