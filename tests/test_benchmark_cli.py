"""La línea de comandos del banco de carga (#18)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gcperros.engine import benchmark_cli
from gcperros.generators import cli as generators_cli

SEED = ["--seed", "20260826"]
#: Una tasa que cualquier máquina sostiene y otra que ninguna: la tabla enseña
#: ambos veredictos sin depender de lo rápido que sea el ordenador que prueba.
RATES = ["--rates", "1e9,1", "--repeats", "1"]


def test_benchmark_prints_one_row_per_rate_in_increasing_order(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert benchmark_cli.main([*SEED, *RATES]) == 0

    out, err = capsys.readouterr()
    rows = out.strip().splitlines()
    assert rows[0].startswith("tasa ev/s")
    assert rows[1].split()[0] == "1" and rows[1].endswith("sostiene")
    assert rows[2].split()[0] == "1000000000" and rows[2].endswith("satura")
    assert "saturacion=1000000000" in err
    assert out.isascii()


def test_benchmark_writes_the_full_report(tmp_path: Path) -> None:
    target = tmp_path / "carga.json"

    assert benchmark_cli.main([*SEED, *RATES, "--report", str(target)]) == 0

    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["saturation_rate"] == 1e9
    assert report["capacity_events_per_s"] == pytest.approx(1.0 / report["mean_cost_s"])
    assert [r["saturated"] for r in report["rates"]] == [False, True]


def test_benchmark_reads_a_match_from_disk(tmp_path: Path) -> None:
    match = tmp_path / "partido.jsonl"
    assert generators_cli.main([*SEED, "--out", str(match)]) == 0

    assert benchmark_cli.main(["--match", str(match), *RATES]) == 0


def test_benchmark_rejects_bad_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    for argv in (
        [*SEED, "--rates", "0,10"],
        [*SEED, "--rates", "diez"],
        [*SEED, "--repeats", "0"],
        ["--rates", "1"],
    ):
        with pytest.raises(SystemExit) as exit_info:
            benchmark_cli.main(argv)
        assert exit_info.value.code == 2
    capsys.readouterr()
