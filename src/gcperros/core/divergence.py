"""Separación entre el plano streaming y el plano batch, contra umbrales (#17).

Es la aritmética del OE-2. Dado el resultado que produjo el motor y el que da
la referencia batch sobre los mismos eventos, mide cuánto se separan indicador
por indicador y lo contrasta con lo que el proyecto declaró tolerable.

Los umbrales vienen del informe (sección 3.3) y aquí se escriben una vez. Dos
admiten margen —posesión y xG son sumas de flotantes— y dos no: un gol o un
evento perdido no es «casi igual», es un dato que faltó.

Sobre «exacto» en los eventos: la marca de agua (HU-12) descarta tardíos y los
**cuenta**. Lo que no admite margen es la contabilidad: aplicados más tardíos
tiene que dar los únicos emitidos. Un evento que falte sin estar en esa cuenta
se perdió en silencio, y eso sí es una brecha.
"""

from __future__ import annotations

from dataclasses import dataclass

from gcperros.core.contracts import MatchEvent
from gcperros.core.possession import possession_totals
from gcperros.core.stats import MatchSummary, summarize_events


@dataclass(frozen=True, slots=True)
class PlaneResult:
    """Lo que un plano —streaming o batch— dice de un partido."""

    summary: MatchSummary
    possession_seconds: dict[str, float]
    dropped_late: int = 0

    @property
    def possession_share(self) -> dict[str, float]:
        """Reparto de posesión, o vacío si no se atribuyó tiempo a nadie."""
        total = sum(self.possession_seconds.values())
        if total <= 0.0:
            return {}
        return {team: value / total for team, value in self.possession_seconds.items()}


def batch_result(events: list[MatchEvent]) -> PlaneResult:
    """La referencia: el flujo entero, limpio, recorrido de una vez."""
    return PlaneResult(
        summary=summarize_events(events),
        possession_seconds=possession_totals(events),
    )


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Separación máxima tolerada, tal como la declara el proyecto."""

    possession_share: float = 0.01
    total_xg: float = 0.05


@dataclass(frozen=True, slots=True)
class Breach:
    """Un umbral superado, con la cifra que lo superó."""

    indicator: str
    observed: float
    limit: float


@dataclass(frozen=True, slots=True)
class Divergence:
    """Cuánto se separan los dos planos en cada indicador."""

    possession_share: float
    total_xg: float
    goals: int
    events: int

    def breaches(self, thresholds: Thresholds | None = None) -> tuple[Breach, ...]:
        """Los umbrales que esta separación supera. Vacío si cumple todos."""
        limits = thresholds or Thresholds()
        found = []
        if self.possession_share >= limits.possession_share:
            found.append(Breach("possession_share", self.possession_share, limits.possession_share))
        if self.total_xg >= limits.total_xg:
            found.append(Breach("total_xg", self.total_xg, limits.total_xg))
        # Goles y eventos no admiten margen: perder uno es perder un dato.
        if self.goals:
            found.append(Breach("goals", float(self.goals), 0.0))
        if self.events:
            found.append(Breach("events", float(self.events), 0.0))
        return tuple(found)

    def passes(self, thresholds: Thresholds | None = None) -> bool:
        """Indica si la separación cabe dentro de lo declarado."""
        return not self.breaches(thresholds)


def _widest_gap(reference: dict[str, float], observed: dict[str, float]) -> float:
    """Mayor diferencia por equipo. Un equipo ausente en lo observado vale cero."""
    if not reference:
        return 0.0
    return max(abs(value - observed.get(team, 0.0)) for team, value in reference.items())


def measure(reference: PlaneResult, observed: PlaneResult) -> Divergence:
    """Compara lo observado (motor) contra la referencia (batch), indicador a indicador.

    ``events`` son los únicos que faltan **sin justificar**: los tardíos ya
    están en la cuenta. Negativo significaría que el motor aplicó más de los
    que existen, que es peor todavía.
    """
    return Divergence(
        possession_share=round(
            _widest_gap(reference.possession_share, observed.possession_share), 6
        ),
        total_xg=round(_widest_gap(reference.summary.total_xg, observed.summary.total_xg), 6),
        goals=abs(sum(reference.summary.goals.values()) - sum(observed.summary.goals.values())),
        events=reference.summary.event_count - observed.summary.event_count - observed.dropped_late,
    )
