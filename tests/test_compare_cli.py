"""Fútbol frente a baloncesto, con la misma vara: la tabla y la puerta (#91)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gcperros.engine.compare_cli import compare, main, markdown
from gcperros.engine.sport_harness import BASKETBALL, FOOTBALL

SEEDS = range(3)


def test_each_sport_holds_its_committed_scenarios_with_its_declared_margin() -> None:
    football = compare(FOOTBALL, SEEDS, (), capacity=False)
    basketball = compare(BASKETBALL, SEEDS, (), capacity=False)

    assert football.passed and basketball.passed
    assert (football.declared_margin_s, basketball.declared_margin_s) == (10.0, 15.0)


def test_the_measurements_say_what_the_documentation_says() -> None:
    """Menos eventos por minuto en baloncesto, así que la marca de agua hace esperar más."""
    football = compare(FOOTBALL, SEEDS, (), capacity=False)
    basketball = compare(BASKETBALL, SEEDS, (), capacity=False)

    assert basketball.events_per_minute < football.events_per_minute / 2
    assert basketball.latency_p95_s > football.latency_p95_s


def test_the_sweep_finds_a_margin_no_longer_than_the_declared_one() -> None:
    row = compare(BASKETBALL, SEEDS, (2.0, 15.0, 30.0), capacity=False)

    assert row.minimum_margin_s is not None
    assert row.minimum_margin_s <= row.declared_margin_s


def test_the_table_puts_the_two_sports_side_by_side() -> None:
    rows = [compare(sport, range(1), (), capacity=False) for sport in (FOOTBALL, BASKETBALL)]

    table = markdown(rows)

    assert table.startswith("| | football | basketball |")
    assert "| Eventos por minuto |" in table and "| Latencia p50 / p95 |" in table


def test_the_cli_writes_its_report_and_is_a_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "comparacion.json"

    code = main(
        ["--matches", "2", "--margins", "", "--no-capacity", "--strict", "--report", str(report)]
    )

    assert code == 0
    assert "| | football | basketball |" in capsys.readouterr().out
    assert [row["sport"] for row in json.loads(report.read_text(encoding="utf-8"))] == [
        "football",
        "basketball",
    ]
