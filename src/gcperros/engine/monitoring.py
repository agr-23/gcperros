"""Supervisión operativa y evaluación de SLA (#30).

Comprueba las cuatro métricas clave del pipeline frente a umbrales de SLA:
latencia p95, rendimiento (throughput), acumulación (backlog) y tasa de rechazo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["INFO", "WARNING", "CRITICAL"]


@dataclass(frozen=True, slots=True)
class SLALimits:
    """Límites declarados de acuerdo de nivel de servicio (SLA)."""

    max_p95_latency_ms: float = 2000.0  # SLA declarado de 2 segundos
    min_throughput_ev_per_s: float = 1000.0
    max_backlog: int = 50
    max_rejection_rate: float = 0.05  # máximo 5% de mensajes rechazados


@dataclass(frozen=True, slots=True)
class Alert:
    """Alerta operativa por incumplimiento de SLA."""

    metric: str
    observed: float
    threshold: float
    severity: Severity
    message: str


@dataclass(frozen=True, slots=True)
class OperationalReport:
    """Evaluación consolidada de salud operativa del pipeline."""

    p95_latency_ms: float
    throughput_ev_per_s: float
    max_backlog: int
    rejection_rate: float
    alerts: tuple[Alert, ...]

    @property
    def healthy(self) -> bool:
        """True si no hay alertas de severidad WARNING o CRITICAL."""
        return not any(a.severity in ("WARNING", "CRITICAL") for a in self.alerts)


def evaluate_operations(
    *,
    p95_latency_ms: float,
    throughput_ev_per_s: float,
    max_backlog: int,
    rejection_rate: float,
    limits: SLALimits | None = None,
) -> OperationalReport:
    """Evalúa métricas operativas observadas contra los límites de SLA."""
    lim = limits or SLALimits()
    alerts: list[Alert] = []

    if p95_latency_ms > lim.max_p95_latency_ms:
        alerts.append(
            Alert(
                metric="p95_latency",
                observed=p95_latency_ms,
                threshold=lim.max_p95_latency_ms,
                severity="CRITICAL",
                message=f"Latencia p95 {p95_latency_ms:.1f}ms excede SLA de {lim.max_p95_latency_ms:.1f}ms",
            )
        )

    if throughput_ev_per_s < lim.min_throughput_ev_per_s:
        alerts.append(
            Alert(
                metric="throughput",
                observed=throughput_ev_per_s,
                threshold=lim.min_throughput_ev_per_s,
                severity="WARNING",
                message=f"Rendimiento {throughput_ev_per_s:.1f} ev/s por debajo de {lim.min_throughput_ev_per_s:.1f} ev/s",
            )
        )

    if max_backlog > lim.max_backlog:
        alerts.append(
            Alert(
                metric="backlog",
                observed=float(max_backlog),
                threshold=float(lim.max_backlog),
                severity="CRITICAL",
                message=f"Backlog acumulado de {max_backlog} eventos excede tope de {lim.max_backlog}",
            )
        )

    if rejection_rate > lim.max_rejection_rate:
        alerts.append(
            Alert(
                metric="rejection_rate",
                observed=rejection_rate,
                threshold=lim.max_rejection_rate,
                severity="WARNING",
                message=f"Tasa de rechazo {rejection_rate:.1%} excede umbral de {lim.max_rejection_rate:.1%}",
            )
        )

    return OperationalReport(
        p95_latency_ms=p95_latency_ms,
        throughput_ev_per_s=throughput_ev_per_s,
        max_backlog=max_backlog,
        rejection_rate=rejection_rate,
        alerts=tuple(alerts),
    )
