"""Pruebas de la declaración de alertas y métricas en Terraform (HU-30)."""

from __future__ import annotations

from pathlib import Path

TERRAFORM_DIR = Path(__file__).parent.parent / "infra" / "terraform"


def test_monitoring_api_is_declared_in_apis_tf() -> None:
    apis_content = (TERRAFORM_DIR / "apis.tf").read_text(encoding="utf-8")
    assert "monitoring.googleapis.com" in apis_content


def test_monitoring_alert_policies_are_declared() -> None:
    monitoring_file = TERRAFORM_DIR / "monitoring.tf"
    assert monitoring_file.exists()
    content = monitoring_file.read_text(encoding="utf-8")
    assert 'resource "google_monitoring_alert_policy" "p95_latency_sla"' in content
    assert 'resource "google_monitoring_alert_policy" "backlog_threshold"' in content
    assert "2000" in content  # Umbral SLA 2s
    assert "50" in content  # Umbral Backlog 50
