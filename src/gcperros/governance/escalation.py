"""Procedimiento de escalado cuando la calidad incumple un umbral (historia #26).

Un umbral incumplido que sólo cambia un código de salida no es accionable. Cada
fallo se convierte en un escalado: **qué tan grave es, quién responde, a quién
se informa y qué hacer**. Quién responde lo declara el catálogo para el flujo
medido (historia #24); Gobernanza se informa siempre, porque lleva la serie.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from gcperros.core.contracts import JsonValue, format_event_time
from gcperros.governance.catalog import OWNERS, Owner, Role, asset
from gcperros.governance.quality import QualityDimension, QualityMeasurement, QualityReport

#: Distancia al umbral a partir de la cual un fallo deja de ser un aviso. Cinco
#: puntos es la misma escala que la señal de discrepancia: por debajo, el dato
#: está degradado; por encima, ya no se puede usar.
SEVERE_GAP = 0.05


class Severity(StrEnum):
    """Qué tan grave es un incumplimiento."""

    #: El dato sigue siendo usable, degradado. Se corrige sin parar nada.
    WARNING = "warning"

    #: El dato no se puede usar tal cual. Se para lo que dependa de él.
    CRITICAL = "critical"


#: Qué hacer ante cada dimensión incumplida.
ACTIONS: dict[QualityDimension, str] = {
    QualityDimension.COMPLETENESS: (
        "Revisar el productor: qué campos faltan, en el repositorio de inválidos "
        "(missing_field, market_incomplete)."
    ),
    QualityDimension.VALIDITY: (
        "Revisar el productor: qué valores salen de su dominio, en el repositorio de inválidos."
    ),
    QualityDimension.UNIQUENESS: (
        "Revisar la entrega del broker: reintentos, plazos de ack y la memoria del deduplicador."
    ),
    QualityDimension.TIMELINESS: (
        "Medir el retraso de entrega frente al margen de la marca de agua antes de tocar el margen."
    ),
    QualityDimension.CONSISTENCY: (
        "Tratar el estado en vivo como no fiable: no publicar señales del partido hasta "
        "que cuadre con el recálculo batch."
    ),
}

#: Plazo de respuesta según la severidad.
DEADLINES: dict[Severity, str] = {
    Severity.WARNING: "antes del siguiente partido",
    Severity.CRITICAL: "inmediato, con el partido en curso",
}


@dataclass(frozen=True, slots=True)
class Escalation:
    """Un incumplimiento, con a quién le toca y qué hacer."""

    scope: str
    measurement: QualityMeasurement
    severity: Severity
    responsible: Owner
    informed: Owner
    action: str
    raised_at: datetime

    def to_dict(self) -> dict[str, JsonValue]:
        """Proyecta el escalado a la estructura que se registra."""
        return {
            "scope": self.scope,
            "raised_at": format_event_time(self.raised_at),
            "severity": self.severity.value,
            "measurement": self.measurement.to_dict(),
            "responsible": {"role": self.responsible.role.value, "person": self.responsible.person},
            "informed": {"role": self.informed.role.value, "person": self.informed.person},
            "action": self.action,
            "deadline": DEADLINES[self.severity],
        }

    def to_json(self) -> str:
        """Serializa el escalado como una línea JSON estable."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def severity_of(measurement: QualityMeasurement) -> Severity:
    """Clasifica un incumplimiento.

    La consistencia es crítica siempre: un indicador que no cuadra es un número
    en pantalla que no es el del partido, sin grados. El resto, según lo lejos
    que quede del umbral.
    """
    if measurement.rule.dimension is QualityDimension.CONSISTENCY:
        return Severity.CRITICAL
    gap = measurement.rule.minimum - measurement.value
    return Severity.CRITICAL if gap > SEVERE_GAP else Severity.WARNING


def escalate(report: QualityReport, stream: str) -> tuple[Escalation, ...]:
    """Escala cada regla incumplida de un informe al responsable del flujo.

    Args:
        report: Informe de calidad de una ingestión.
        stream: Flujo medido, tal como lo nombra el catálogo.

    Raises:
        KeyError: Si el flujo no está catalogado: sin responsable no hay a
            quién escalar, y eso es un fallo del catálogo, no del dato.
    """
    responsible = OWNERS[asset(stream).owner]
    return tuple(
        Escalation(
            scope=report.scope,
            measurement=failure,
            severity=severity_of(failure),
            responsible=responsible,
            informed=OWNERS[Role.GOVERNANCE],
            action=ACTIONS[failure.rule.dimension],
            raised_at=report.measured_at,
        )
        for failure in report.failures
    )
