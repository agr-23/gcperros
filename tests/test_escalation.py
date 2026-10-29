"""El procedimiento de escalado de la calidad (historia #26)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gcperros.generators import cli as generators_cli
from gcperros.governance import cli as governance_cli
from gcperros.governance.catalog import OWNERS, Role
from gcperros.governance.escalation import ACTIONS, Severity, escalate, severity_of
from gcperros.governance.quality import (
    DEFAULT_RULES,
    PLANE_CONSISTENCY,
    REQUIRED_FIELDS,
    QualityDimension,
    QualityMeasurement,
    QualityReport,
)

MEASURED_AT = datetime(2026, 8, 26, 21, 0, tzinfo=UTC)


def _report(*measurements: QualityMeasurement) -> QualityReport:
    return QualityReport("match-events", MEASURED_AT, measurements)


def test_every_dimension_has_an_action() -> None:
    assert set(ACTIONS) == set(QualityDimension)
    assert {rule.dimension for rule in DEFAULT_RULES} <= set(ACTIONS)


@pytest.mark.parametrize(
    ("observed", "expected"),
    [(985, Severity.WARNING), (939, Severity.CRITICAL)],
)
def test_severity_grows_with_the_distance_to_the_threshold(
    observed: int, expected: Severity
) -> None:
    """Medio punto por debajo es un aviso; cinco puntos por debajo ya no se usa."""
    assert severity_of(QualityMeasurement(REQUIRED_FIELDS, observed, 1000)) is expected


def test_an_inconsistent_live_state_is_always_critical() -> None:
    """Un indicador que no cuadra es un número equivocado en pantalla, sin grados."""
    assert severity_of(QualityMeasurement(PLANE_CONSISTENCY, 3, 4)) is Severity.CRITICAL


def test_it_goes_to_the_owner_the_catalog_declares_and_governance_is_told() -> None:
    (escalation,) = escalate(_report(QualityMeasurement(REQUIRED_FIELDS, 90, 100)), "match-events")
    payload = json.loads(escalation.to_json())

    assert escalation.responsible == OWNERS[Role.PIPELINES]
    assert escalation.informed == OWNERS[Role.GOVERNANCE]
    assert payload["severity"] == "critical"
    assert payload["deadline"] == "inmediato, con el partido en curso"
    assert payload["measurement"]["rule"] == "required_fields"


def test_a_passing_report_escalates_nothing() -> None:
    assert escalate(_report(QualityMeasurement(REQUIRED_FIELDS, 100, 100)), "match-events") == ()


def test_an_uncatalogued_stream_has_nobody_to_escalate_to() -> None:
    with pytest.raises(KeyError):
        escalate(_report(QualityMeasurement(REQUIRED_FIELDS, 0, 100)), "user-clicks")


def test_the_cli_records_every_breach_and_keeps_the_series(tmp_path: Path) -> None:
    clean = tmp_path / "partido.jsonl"
    generators_cli.main(["--seed", "20260826", "--out", str(clean)])
    ruined = tmp_path / "arruinado.jsonl"
    lines = clean.read_text(encoding="utf-8").splitlines()
    ruined.write_text("\n".join([*lines[:5], "{basura", "[1]"]) + "\n", encoding="utf-8")
    log = tmp_path / "escalados.jsonl"

    for source in (clean, ruined, ruined):
        governance_cli.quality_main(
            ["--stream", "match", "--in", str(source), "--escalations", str(log)]
        )

    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert {r["measurement"]["dimension"] for r in records} == {"validity"}
    assert {r["responsible"]["person"] for r in records} == {OWNERS[Role.PIPELINES].person}
