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


def test_the_backlog_is_also_watched_in_time_for_any_sport() -> None:
    """50 mensajes son 4,5 min de fútbol y más de 10 de baloncesto: el tiempo no cambia (#95)."""
    content = (TERRAFORM_DIR / "monitoring.tf").read_text(encoding="utf-8")
    policy = content[content.index('"backlog_age"') :]

    assert "subscription/oldest_unacked_message_age" in policy
    assert "threshold_value = 300.0" in policy
    # Sin filtro por suscripción: vale para los flujos de los dos deportes.
    assert "subscription_id" not in policy
    football, basketball = 11.1, 4.8  # eventos por minuto, sección 21
    assert 50 / football * 60 <= 300.0 < 50 / basketball * 60
