"""Pruebas de supervisión operativa y alertas SLA (#30)."""

from __future__ import annotations

from gcperros.engine.monitoring import SLALimits, evaluate_operations


def test_healthy_pipeline_triggers_no_alerts() -> None:
    report = evaluate_operations(
        p95_latency_ms=120.0,
        throughput_ev_per_s=5000.0,
        max_backlog=5,
        rejection_rate=0.01,
    )
    assert report.healthy
    assert len(report.alerts) == 0


def test_latency_breach_triggers_critical_alert() -> None:
    report = evaluate_operations(
        p95_latency_ms=3100.0,  # 3.1s > 2.0s SLA
        throughput_ev_per_s=5000.0,
        max_backlog=5,
        rejection_rate=0.01,
    )
    assert not report.healthy
    alert = next(a for a in report.alerts if a.metric == "p95_latency")
    assert alert.severity == "CRITICAL"
    assert alert.threshold == 2000.0


def test_throughput_drop_triggers_warning() -> None:
    report = evaluate_operations(
        p95_latency_ms=500.0,
        throughput_ev_per_s=400.0,  # < 1000 ev/s
        max_backlog=10,
        rejection_rate=0.02,
    )
    assert not report.healthy
    alert = next(a for a in report.alerts if a.metric == "throughput")
    assert alert.severity == "WARNING"


def test_backlog_and_rejection_breaches_are_reported() -> None:
    report = evaluate_operations(
        p95_latency_ms=150.0,
        throughput_ev_per_s=2000.0,
        max_backlog=120,  # > 50
        rejection_rate=0.12,  # > 5%
    )
    metrics = {a.metric for a in report.alerts}
    assert metrics == {"backlog", "rejection_rate"}
