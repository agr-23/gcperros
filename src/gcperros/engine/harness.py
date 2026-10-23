"""Harness que somete el motor a perturbaciones y mide si sigue siendo correcto (#17).

Convierte «confiamos en que el motor funciona» en «medimos que el motor
funciona»: toma un partido, lo degrada como lo haría el broker —duplicados,
desorden, retardo— a intensidades crecientes, lo pasa por el motor y contrasta
cada resultado contra la referencia batch con ``core.divergence``.

Dos familias de escenarios, a propósito. ``DEFAULT_SCENARIOS`` es la
adversidad que el diseño se compromete a resistir con su margen por defecto, y
es lo que puede bloquear una integración. ``STRESS_SCENARIOS`` va más allá de
ese compromiso para localizar dónde se rompe: se informa, no se exige.
"""

from __future__ import annotations

from dataclasses import dataclass

from gcperros.core.contracts import MatchEvent
from gcperros.core.divergence import (
    Divergence,
    PlaneResult,
    Thresholds,
    batch_result,
    measure,
)
from gcperros.engine.pipeline import MatchEngine
from gcperros.engine.watermark import DEFAULT_ALLOWED_LATENESS_S
from gcperros.generators.perturbation import inject_disorder, inject_duplicates


@dataclass(frozen=True, slots=True)
class Scenario:
    """Una forma concreta de maltratar el flujo antes de dárselo al motor."""

    name: str
    duplicate_rate: float = 0.0
    mean_delay_s: float = 0.0
    max_delay_s: float = 0.0


#: Lo que el motor se compromete a resistir. La perturbación «desorden medio» es
#: la misma con la que se eligió el margen de la marca de agua.
DEFAULT_SCENARIOS: tuple[Scenario, ...] = (
    Scenario("limpio"),
    Scenario("duplicados-5", duplicate_rate=0.05),
    Scenario("duplicados-20", duplicate_rate=0.20),
    Scenario("desorden-leve", mean_delay_s=1.0, max_delay_s=10.0),
    Scenario("desorden-medio", mean_delay_s=2.0, max_delay_s=30.0),
    Scenario("hostil", duplicate_rate=0.15, mean_delay_s=2.0, max_delay_s=30.0),
)

#: Más allá del compromiso: sirve para ver dónde se rompe, no para exigir.
STRESS_SCENARIOS: tuple[Scenario, ...] = (
    Scenario("retardo-fuerte", mean_delay_s=5.0, max_delay_s=60.0),
    Scenario("retardo-extremo", mean_delay_s=10.0, max_delay_s=120.0),
)


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """Cómo le fue al motor con un escenario."""

    scenario: Scenario
    divergence: Divergence
    delivered: int
    duplicates_removed: int
    dropped_late: int
    timeliness: float
    passed: bool


@dataclass(frozen=True, slots=True)
class HarnessReport:
    """El informe completo de una ejecución del harness."""

    match_id: str
    allowed_lateness_s: float
    results: tuple[ScenarioResult, ...]

    @property
    def passed(self) -> bool:
        """Verdadero sólo si todos los escenarios cumplen los umbrales."""
        return all(result.passed for result in self.results)

    @property
    def failures(self) -> tuple[ScenarioResult, ...]:
        """Los escenarios que no cumplieron, para el informe y la salida."""
        return tuple(result for result in self.results if not result.passed)


def _degrade(events: list[MatchEvent], scenario: Scenario, seed: int) -> list[MatchEvent]:
    """Degrada el flujo como dice el escenario, con semilla derivada de su nombre."""
    salt = sum(ord(char) for char in scenario.name)
    delivered = events
    if scenario.duplicate_rate > 0.0:
        delivered, _ = inject_duplicates(delivered, seed=seed + salt, rate=scenario.duplicate_rate)
    if scenario.mean_delay_s > 0.0:
        delivered, _ = inject_disorder(
            delivered,
            seed=seed + salt + 1,
            mean_delay_s=scenario.mean_delay_s,
            max_delay_s=scenario.max_delay_s,
        )
    return delivered


def run_harness(
    events: list[MatchEvent],
    seed: int,
    scenarios: tuple[Scenario, ...] = DEFAULT_SCENARIOS,
    allowed_lateness_s: float = DEFAULT_ALLOWED_LATENESS_S,
    thresholds: Thresholds | None = None,
) -> HarnessReport:
    """Ejecuta cada escenario contra el motor y mide la separación con el batch.

    La semilla de las perturbaciones es independiente de la del partido, para
    poder variar la adversidad sin cambiar el encuentro.
    """
    if not events:
        raise ValueError("no hay eventos que someter al harness")

    reference = batch_result(events)
    results = []

    for scenario in scenarios:
        delivered = _degrade(events, scenario, seed)
        outcome = MatchEngine(allowed_lateness_s=allowed_lateness_s).process_all(delivered)
        observed = PlaneResult(
            summary=outcome.summary,
            possession_seconds=outcome.possession.running_seconds,
            dropped_late=outcome.watermark.dropped_late,
        )
        divergence = measure(reference, observed)
        results.append(
            ScenarioResult(
                scenario=scenario,
                divergence=divergence,
                delivered=len(delivered),
                duplicates_removed=outcome.dedup.duplicates,
                dropped_late=outcome.watermark.dropped_late,
                timeliness=round(outcome.watermark.timeliness, 4),
                passed=divergence.passes(thresholds),
            )
        )

    return HarnessReport(
        match_id=events[0].match_id,
        allowed_lateness_s=allowed_lateness_s,
        results=tuple(results),
    )
