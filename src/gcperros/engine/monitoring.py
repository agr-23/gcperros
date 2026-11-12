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
    max_backlog_age_s: float = 300.0  # máximo 5 minutos sin confirmar (#95)


def limits_for_sport(sport: str = "football") -> SLALimits:
    """Devuelve límites de SLA calibrados según la densidad del deporte (#95).

    En fútbol (11,1 ev/min), 50 eventos equivalen a 4,5 minutos de cola.
    En baloncesto (4,8 ev/min), 50 eventos tardarían más de 10 minutos en acumularse,
    por lo que un umbral de 24 eventos equivale a los mismos ~300 s (5 min) de antigüedad.
    """
    if sport == "basketball":
        return SLALimits(
            max_p95_latency_ms=2000.0,
            min_throughput_ev_per_s=1000.0,
            max_backlog=24,  # 300 s * (4.8 ev / 60 s) = 24 eventos
            max_rejection_rate=0.05,
            max_backlog_age_s=300.0,
        )
    return SLALimits(
        max_p95_latency_ms=2000.0,
        min_throughput_ev_per_s=1000.0,
        max_backlog=50,
        max_rejection_rate=0.05,
        max_backlog_age_s=300.0,
    )


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
    backlog_age_s: float | None = None

    @property
    def healthy(self) -> bool:
        """True si no hay alertas de severidad WARNING o CRITICAL."""
        return not any(a.severity in ("WARNING", "CRITICAL") for a in self.alerts)


def evaluate_operations(  # noqa: PLR0913
    *,
    p95_latency_ms: float,
    throughput_ev_per_s: float,
    max_backlog: int,
    rejection_rate: float,
    backlog_age_s: float | None = None,
    limits: SLALimits | None = None,
    sport: str | None = None,
) -> OperationalReport:
    """Evalúa métricas operativas observadas contra los límites de SLA."""
    lim = limits or (limits_for_sport(sport) if sport else SLALimits())
    alerts: list[Alert] = []

    if p95_latency_ms > lim.max_p95_latency_ms:
        msg = f"Latencia p95 {p95_latency_ms:.1f}ms excede SLA ({lim.max_p95_latency_ms:.1f}ms)"
        alerts.append(
            Alert(
                metric="p95_latency",
                observed=p95_latency_ms,
                threshold=lim.max_p95_latency_ms,
                severity="CRITICAL",
                message=msg,
            )
        )

    if throughput_ev_per_s < lim.min_throughput_ev_per_s:
        msg = f"Throughput {throughput_ev_per_s:.0f} ev/s bajo mínimo"
        alerts.append(
            Alert(
                metric="throughput",
                observed=throughput_ev_per_s,
                threshold=lim.min_throughput_ev_per_s,
                severity="WARNING",
                message=msg,
            )
        )

    if max_backlog > lim.max_backlog:
        msg = f"Backlog de {max_backlog} eventos excede tope ({lim.max_backlog})"
        alerts.append(
            Alert(
                metric="backlog",
                observed=float(max_backlog),
                threshold=float(lim.max_backlog),
                severity="CRITICAL",
                message=msg,
            )
        )

    if backlog_age_s is not None and backlog_age_s > lim.max_backlog_age_s:
        msg = (
            f"Mensaje más antiguo ({backlog_age_s:.1f}s) excede límite "
            f"({lim.max_backlog_age_s:.1f}s)"
        )
        alerts.append(
            Alert(
                metric="backlog_age",
                observed=backlog_age_s,
                threshold=lim.max_backlog_age_s,
                severity="CRITICAL",
                message=msg,
            )
        )

    if rejection_rate > lim.max_rejection_rate:
        msg = f"Tasa de rechazo {rejection_rate:.1%} excede umbral ({lim.max_rejection_rate:.1%})"
        alerts.append(
            Alert(
                metric="rejection_rate",
                observed=rejection_rate,
                threshold=lim.max_rejection_rate,
                severity="WARNING",
                message=msg,
            )
        )

    return OperationalReport(
        p95_latency_ms=p95_latency_ms,
        throughput_ev_per_s=throughput_ev_per_s,
        max_backlog=max_backlog,
        rejection_rate=rejection_rate,
        alerts=tuple(alerts),
        backlog_age_s=backlog_age_s,
    )
