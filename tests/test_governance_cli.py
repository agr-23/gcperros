"""La frontera desde la línea de comandos (HU-16).

Es la forma en que la historia se demuestra sin escribir código: se intercala
delante de cualquier consumidor y este solo ve lo que cumple el contrato.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from gcperros.generators import cli as generators_cli
from gcperros.governance import cli as governance_cli

SEED = "20260826"


@pytest.fixture
def match_file(tmp_path: Path) -> Path:
    target = tmp_path / "partido.jsonl"
    generators_cli.main(["--seed", SEED, "--out", str(target)])
    return target


@pytest.fixture
def odds_file(tmp_path: Path) -> Path:
    target = tmp_path / "cuotas.jsonl"
    generators_cli.odds_main(["--seed", SEED, "--out", str(target)])
    return target


def _corrupt(source: Path, target: Path) -> None:
    """Escribe el mismo flujo con tres mensajes averiados intercalados."""
    lines = source.read_text(encoding="utf-8").splitlines()
    shot = json.loads(next(line for line in lines if json.loads(line)["event_type"] == "shot"))
    shot["attrs"] = {key: value for key, value in shot["attrs"].items() if key != "xg"}

    broken = [lines[0], "{no cierra", json.dumps(shot), "[1, 2, 3]", lines[1]]
    target.write_text("\n".join(broken) + "\n", encoding="utf-8")


###############################################################################
# Un flujo limpio
###############################################################################


def test_a_clean_stream_crosses_byte_for_byte(match_file: Path, tmp_path: Path) -> None:
    """La frontera decide qué pasa, no cómo se ve."""
    out = tmp_path / "conformes.jsonl"

    code = governance_cli.main(
        ["--stream", "match", "--in", str(match_file), "--out", str(out), "--strict"]
    )

    assert code == 0
    assert out.read_bytes() == match_file.read_bytes()


def test_a_clean_stream_leaves_no_invalid_file_behind(match_file: Path, tmp_path: Path) -> None:
    invalid = tmp_path / "invalidos.jsonl"

    governance_cli.main(
        [
            "--stream",
            "match",
            "--in",
            str(match_file),
            "--out",
            str(tmp_path / "conformes.jsonl"),
            "--invalid",
            str(invalid),
        ]
    )

    assert not invalid.exists()


def test_the_odds_stream_has_its_own_contract(odds_file: Path, tmp_path: Path) -> None:
    out = tmp_path / "conformes.jsonl"

    code = governance_cli.main(
        ["--stream", "odds", "--in", str(odds_file), "--out", str(out), "--strict"]
    )

    assert code == 0
    assert out.read_bytes() == odds_file.read_bytes()


def test_a_match_stream_judged_as_odds_is_rejected_wholesale(
    match_file: Path, tmp_path: Path
) -> None:
    """Dos contratos distintos: confundir los topics no pasa desapercibido."""
    code = governance_cli.main(
        [
            "--stream",
            "odds",
            "--in",
            str(match_file),
            "--out",
            str(tmp_path / "conformes.jsonl"),
            "--strict",
        ]
    )

    assert code == 1


###############################################################################
# Un flujo averiado
###############################################################################


def test_only_the_conforming_messages_come_out(match_file: Path, tmp_path: Path) -> None:
    dirty = tmp_path / "sucio.jsonl"
    _corrupt(match_file, dirty)
    out = tmp_path / "conformes.jsonl"

    governance_cli.main(["--stream", "match", "--in", str(dirty), "--out", str(out)])

    assert len(out.read_text(encoding="utf-8").splitlines()) == 2


def test_every_rejection_is_archived_with_its_cause(match_file: Path, tmp_path: Path) -> None:
    dirty = tmp_path / "sucio.jsonl"
    _corrupt(match_file, dirty)
    invalid = tmp_path / "invalidos.jsonl"

    governance_cli.main(
        [
            "--stream",
            "match",
            "--in",
            str(dirty),
            "--out",
            str(tmp_path / "conformes.jsonl"),
            "--invalid",
            str(invalid),
        ]
    )

    records = [json.loads(line) for line in invalid.read_text(encoding="utf-8").splitlines()]

    assert len(records) == 3
    assert all(record["causes"] for record in records)
    assert {"malformed_json", "missing_field", "not_an_object"} == {
        rule for record in records for rule in record["rules"]
    }


def test_strict_turns_a_rejection_into_a_failing_exit_code(
    match_file: Path, tmp_path: Path
) -> None:
    """Es lo que permite usar la frontera como puerta en integración continua."""
    dirty = tmp_path / "sucio.jsonl"
    _corrupt(match_file, dirty)
    arguments = ["--stream", "match", "--in", str(dirty), "--out", str(tmp_path / "c.jsonl")]

    assert governance_cli.main(arguments) == 0
    assert governance_cli.main([*arguments, "--strict"]) == 1


def test_without_a_repository_the_rejections_are_counted_but_not_kept(
    match_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dirty = tmp_path / "sucio.jsonl"
    _corrupt(match_file, dirty)

    governance_cli.main(
        ["--stream", "match", "--in", str(dirty), "--out", str(tmp_path / "c.jsonl")]
    )

    assert "rechazados=3" in capsys.readouterr().err


###############################################################################
# Entradas y salidas
###############################################################################


def test_the_summary_goes_to_stderr_so_it_never_pollutes_the_stream(
    match_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    governance_cli.main(["--stream", "match", "--in", str(match_file)])

    captured = capsys.readouterr()

    assert "conformidad=1.0000" in captured.err
    assert captured.err not in captured.out


def test_the_stream_can_arrive_through_standard_input(
    match_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Así la frontera se intercala en una tubería, que es como se va a usar."""
    monkeypatch.setattr("sys.stdin", io.StringIO(match_file.read_text(encoding="utf-8")))
    out = tmp_path / "conformes.jsonl"

    assert governance_cli.main(["--stream", "match", "--out", str(out), "--strict"]) == 0
    assert out.read_bytes() == match_file.read_bytes()


def test_blank_lines_are_not_messages(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "huecos.jsonl"
    source.write_text("\n\n   \n", encoding="utf-8")

    governance_cli.main(["--stream", "match", "--in", str(source)])

    assert "vistos=0" in capsys.readouterr().err


def test_the_stream_is_mandatory() -> None:
    with pytest.raises(SystemExit):
        governance_cli.main(["--in", "nada.jsonl"])


def test_an_unknown_stream_is_rejected() -> None:
    with pytest.raises(SystemExit):
        governance_cli.main(["--stream", "quiniela"])


###############################################################################
# gcperros-quality (HU-17)
###############################################################################


def test_a_clean_match_passes_every_rule(match_file: Path, tmp_path: Path) -> None:
    report_file = tmp_path / "calidad.json"

    code = governance_cli.quality_main(
        ["--stream", "match", "--in", str(match_file), "--report", str(report_file), "--strict"]
    )

    report = json.loads(report_file.read_text(encoding="utf-8"))

    assert code == 0
    assert report["passed"] is True
    assert {m["dimension"] for m in report["measurements"]} == {
        "completeness",
        "uniqueness",
        "timeliness",
    }


def test_the_odds_stream_can_only_be_measured_on_completeness(
    odds_file: Path, tmp_path: Path
) -> None:
    """No pasa por el motor, y lo que no se midió se dice en vez de aprobarse."""
    report_file = tmp_path / "calidad.json"

    governance_cli.quality_main(
        ["--stream", "odds", "--in", str(odds_file), "--report", str(report_file)]
    )

    report = json.loads(report_file.read_text(encoding="utf-8"))

    assert [m["dimension"] for m in report["measurements"]] == ["completeness"]
    assert report["unmeasured"] == ["uniqueness", "timeliness"]


def test_the_report_says_which_causes_ate_the_completeness(
    match_file: Path, tmp_path: Path
) -> None:
    dirty = tmp_path / "sucio.jsonl"
    _corrupt(match_file, dirty)
    report_file = tmp_path / "calidad.json"

    governance_cli.quality_main(
        ["--stream", "match", "--in", str(dirty), "--report", str(report_file)]
    )

    report = json.loads(report_file.read_text(encoding="utf-8"))

    assert set(report["rejections_by_rule"]) == {
        "malformed_json",
        "missing_field",
        "not_an_object",
    }


def test_a_stream_below_the_threshold_fails_under_strict(match_file: Path, tmp_path: Path) -> None:
    """Es lo que permite usar el informe como puerta y no solo como lectura."""
    lines = match_file.read_text(encoding="utf-8").splitlines()
    ruined = tmp_path / "arruinado.jsonl"
    ruined.write_text("\n".join([*lines[:5], "{basura", "[1]", "null"]) + "\n", encoding="utf-8")

    arguments = ["--stream", "match", "--in", str(ruined), "--report", str(tmp_path / "c.json")]

    assert governance_cli.quality_main(arguments) == 0
    assert governance_cli.quality_main([*arguments, "--strict"]) == 1


def test_the_scope_can_be_named(match_file: Path, tmp_path: Path) -> None:
    report_file = tmp_path / "calidad.json"

    governance_cli.quality_main(
        [
            "--stream",
            "match",
            "--in",
            str(match_file),
            "--report",
            str(report_file),
            "--scope",
            "jornada-3",
        ]
    )

    assert json.loads(report_file.read_text(encoding="utf-8"))["scope"] == "jornada-3"


def test_the_report_goes_to_stdout_and_the_summary_to_stderr(
    match_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    governance_cli.quality_main(["--stream", "match", "--in", str(match_file)])

    captured = capsys.readouterr()

    assert json.loads(captured.out)["passed"] is True
    assert "calidad=PASA" in captured.err


def test_rejected_messages_are_archived_during_the_quality_run(
    match_file: Path, tmp_path: Path
) -> None:
    """El informe mide; el repositorio conserva la evidencia de cada rechazo."""
    dirty = tmp_path / "sucio.jsonl"
    _corrupt(match_file, dirty)
    invalid = tmp_path / "invalidos.jsonl"

    governance_cli.quality_main(
        [
            "--stream",
            "match",
            "--in",
            str(dirty),
            "--invalid",
            str(invalid),
            "--report",
            str(tmp_path / "c.json"),
        ]
    )

    assert len(invalid.read_text(encoding="utf-8").splitlines()) == 3
