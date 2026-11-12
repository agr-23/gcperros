"""La calidad y la frontera del baloncesto, con su escalado (#98).

Las cinco dimensiones de la historia 26 se miden igual en los dos deportes: lo
que cambia es el contrato que juzga la frontera y los indicadores con los que el
estado en vivo se contrasta con el recálculo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gcperros.engine.sport_harness import SportDivergence
from gcperros.generators import cli as generators_cli
from gcperros.governance import cli as governance_cli
from gcperros.governance.catalog import OWNERS, Role
from gcperros.governance.escalation import Severity, escalate
from gcperros.governance.quality import IngestionEvidence, QualityDimension, assess

SEED = "20260826"


@pytest.fixture
def game(tmp_path: Path) -> Path:
    target = tmp_path / "baloncesto.jsonl"
    generators_cli.main(["--seed", SEED, "--sport", "basketball", "--out", str(target)])
    return target


def _report(path: Path, stream: str, *extra: str) -> dict[str, object]:
    out = path.with_suffix(".informe.json")
    governance_cli.quality_main(
        ["--stream", stream, "--in", str(path), "--report", str(out), *extra]
    )
    report: dict[str, object] = json.loads(out.read_text(encoding="utf-8"))
    return report


def _values(report: dict[str, object]) -> dict[str, float]:
    measurements = report["measurements"]
    assert isinstance(measurements, list)
    return {m["dimension"]: m["value"] for m in measurements}


def test_a_clean_game_passes_the_five_dimensions(game: Path) -> None:
    report = _report(game, "basketball")

    assert report["passed"] is True
    assert report["scope"] == "basketball-events/match-0001"
    assert _values(report) == dict.fromkeys(QualityDimension, 1.0)


def test_a_shot_worth_four_is_a_validity_failure_escalated_to_its_owner(
    game: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un tiro vale 2 o 3: el cuatro lo rechaza la frontera y alguien se entera."""
    lines = game.read_text(encoding="utf-8").splitlines()
    shots = [i for i, line in enumerate(lines) if json.loads(line)["event_type"] == "shot"]
    for index in shots[:10]:
        shot = json.loads(lines[index])
        shot["attrs"]["points_value"] = 4
        lines[index] = json.dumps(shot)
    ruined = tmp_path / "cuatro.jsonl"
    ruined.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log = tmp_path / "escalados.jsonl"

    report = _report(ruined, "basketball", "--escalations", str(log))

    assert _values(report)["validity"] < 0.99
    assert _values(report)["completeness"] == 1.0
    (escalation,) = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert escalation["measurement"]["dimension"] == "validity"
    assert escalation["responsible"]["person"] == OWNERS[Role.PIPELINES].person
    assert "escalado" in capsys.readouterr().err


def test_points_lost_between_planes_are_a_critical_consistency_breach() -> None:
    """Un punto perdido no admite margen, como un gol en fútbol."""
    evidence = IngestionEvidence(divergence=SportDivergence(0.0, 0.0, exact=2, events=0))
    report = assess("basketball-events/match-0001", evidence)

    (consistency,) = report.measurements
    assert (consistency.observed, consistency.total) == (3, 4)
    (escalation,) = escalate(report, "basketball-events")
    assert escalation.severity is Severity.CRITICAL


def test_the_basketball_odds_are_only_measured_at_the_gate(tmp_path: Path) -> None:
    odds = tmp_path / "cuotas.jsonl"
    generators_cli.odds_main(["--seed", SEED, "--sport", "basketball", "--out", str(odds)])

    report = _report(odds, "basketball-odds")

    assert report["passed"] is True
    assert set(_values(report)) == {"completeness", "validity"}
    assert str(report["scope"]).startswith("basketball-odds/")


def test_the_gate_judges_basketball_by_its_own_contract(game: Path, tmp_path: Path) -> None:
    """Un partido de baloncesto juzgado como fútbol no pasa: su vocabulario es otro."""
    as_basketball = governance_cli.main(["--stream", "basketball", "--in", str(game), "--strict"])
    as_football = governance_cli.main(
        ["--stream", "match", "--in", str(game), "--out", str(tmp_path / "x.jsonl"), "--strict"]
    )

    assert (as_basketball, as_football) == (0, 1)
