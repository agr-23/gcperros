"""Las interfaces de línea de comandos, que son la puerta de entrada del proyecto."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gcperros.generators import cli as generators_cli
from gcperros.loading import cli as loading_cli
from gcperros.publishing import cli as publishing_cli

SEED = ["--seed", "20260826"]


###############################################################################
# Generadores
###############################################################################


def test_match_generator_writes_one_json_object_per_line(tmp_path: Path) -> None:
    target = tmp_path / "partido.jsonl"
    assert generators_cli.main([*SEED, "--out", str(target)]) == 0

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) > 1000
    assert all(json.loads(line)["match_id"] == "match-0001" for line in lines)


def test_odds_generator_writes_its_own_stream(tmp_path: Path) -> None:
    target = tmp_path / "cuotas.jsonl"
    assert generators_cli.odds_main([*SEED, "--out", str(target)]) == 0

    payloads = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert payloads
    assert all("outcomes" in payload for payload in payloads)


def test_team_names_reach_the_stream(tmp_path: Path) -> None:
    target = tmp_path / "partido.jsonl"
    generators_cli.main([*SEED, "--home", "RMA", "--away", "BAR", "--out", str(target)])

    teams = {json.loads(line)["team"] for line in target.read_text(encoding="utf-8").splitlines()}
    assert teams == {"RMA", "BAR"}


def test_without_out_the_stream_goes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert generators_cli.main([*SEED]) == 0
    assert len(capsys.readouterr().out.splitlines()) > 1000


def test_summary_goes_to_stderr_so_it_never_pollutes_the_stream(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """El resumen no puede mezclarse con los datos: van por canales distintos."""
    generators_cli.main([*SEED, "--summary"])
    captured = capsys.readouterr()

    assert "eventos=" in captured.err
    assert "eventos=" not in captured.out


def test_the_seed_is_mandatory() -> None:
    with pytest.raises(SystemExit):
        generators_cli.main([])


###############################################################################
# Publicador
###############################################################################


def test_dry_run_needs_no_project() -> None:
    assert publishing_cli.main([*SEED, "--dry-run"]) == 0


def test_publishing_for_real_demands_a_project() -> None:
    with pytest.raises(SystemExit, match="--project"):
        publishing_cli.main([*SEED])


def test_only_lets_you_publish_one_stream(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO"):
        publishing_cli.main([*SEED, "--dry-run", "--only", "match"])

    published = [record for record in caplog.records if "publicados" in record.message]
    assert published
    assert "odds-updates" not in published[-1].getMessage()


def test_an_unknown_stream_is_rejected() -> None:
    with pytest.raises(SystemExit):
        publishing_cli.main([*SEED, "--dry-run", "--only", "corners"])


###############################################################################
# Cargador de la capa Raw (HU-14)
###############################################################################


def test_raw_loader_dry_run_persists_every_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    events = tmp_path / "partido.jsonl"
    generators_cli.main([*SEED, "--out", str(events)])
    line_count = len(events.read_text(encoding="utf-8").splitlines())

    with caplog.at_level("INFO"):
        exit_code = loading_cli.main(["--dry-run", "--stream", "match", "--in", str(events)])

    assert exit_code == 0
    summary = next(r for r in caplog.records if "extraídos" in r.message)
    assert f"{line_count} extraídos" in summary.getMessage()
    assert f"{line_count} persistidos" in summary.getMessage()
    assert "0 sin confirmar" in summary.getMessage()


def test_raw_loader_dry_run_needs_an_input_file() -> None:
    with pytest.raises(SystemExit, match="--in"):
        loading_cli.main(["--dry-run", "--stream", "match"])


def test_raw_loader_dry_run_rejects_both_streams_at_once(tmp_path: Path) -> None:
    events = tmp_path / "partido.jsonl"
    generators_cli.main([*SEED, "--out", str(events)])

    with pytest.raises(SystemExit, match="--stream match u odds"):
        loading_cli.main(["--dry-run", "--in", str(events)])


def test_raw_loader_loop_rejects_both_streams_at_once() -> None:
    with pytest.raises(SystemExit, match="--stream match u odds"):
        loading_cli.main(["--loop", "--project", "demo", "--stream", "both"])


def test_raw_loading_for_real_demands_a_project() -> None:
    with pytest.raises(SystemExit, match="--project"):
        loading_cli.main(["--stream", "match"])
