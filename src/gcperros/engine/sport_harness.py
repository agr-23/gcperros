"""El harness de #17, para cualquier deporte (#91).

``engine/harness.py`` compara goles y xG porque nació con el fútbol, y sus
nombres son los de la puerta de CI y los informes, así que no se tocan. Este
módulo hace la misma comparación con lo que cada deporte declara en su perfil:
un indicador **exacto**, que no admite margen —goles, puntos—, uno **estimado**,
que es una suma de flotantes —xG, puntos esperados—, la posesión y la
contabilidad de eventos.

Con el perfil del fútbol da exactamente las mismas cifras que el harness de
siempre; ``tests/test_sport_harness.py`` lo comprueba. Es lo que permite poner
los dos deportes lado a lado sabiendo que se miden con la misma vara.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from gcperros.core.american_football_stats import summarize_american_football
from gcperros.core.basketball_stats import summarize_basketball
from gcperros.core.contracts import MatchEvent
from gcperros.core.divergence import Breach, Thresholds
from gcperros.core.possession import MAX_IN_PLAY_GAP_S, PossessionTracker
from gcperros.core.stats import summarize_events
from gcperros.engine.american_football_state import (
    AMERICAN_FOOTBALL_ALLOWED_LATENESS_S,
    AMERICAN_FOOTBALL_MAX_IN_PLAY_GAP_S,
    american_football_engine,
)
from gcperros.engine.basketball_state import (
    BASKETBALL_ALLOWED_LATENESS_S,
    BASKETBALL_MAX_IN_PLAY_GAP_S,
    basketball_engine,
)
from gcperros.engine.harness import DEFAULT_SCENARIOS, Scenario, degrade
from gcperros.engine.latency import LatencyStats
from gcperros.engine.pipeline import EngineResult, MatchEngine, StreamEngine
from gcperros.engine.watermark import DEFAULT_ALLOWED_LATENESS_S
from gcperros.generators.american_football import simulate_american_football
from gcperros.generators.basketball import simulate_basketball
from gcperros.generators.match import simulate_match


@dataclass(frozen=True, slots=True)
class SportPlane:
    """Lo que un plano dice de un partido, en los términos que comparten los deportes."""

    exact: int
    estimate: dict[str, float]
    possession_seconds: dict[str, float]
    event_count: int
    dropped_late: int = 0

    @property
    def possession_share(self) -> dict[str, float]:
        """Reparto de posesión, o vacío si no se atribuyó tiempo a nadie."""
        total = sum(self.possession_seconds.values())
        if total <= 0.0:
            return {}
        return {team: value / total for team, value in self.possession_seconds.items()}


@dataclass(frozen=True, slots=True)
class SportRun:
    """Una pasada del motor: lo que dijo y cómo le fue."""

    plane: SportPlane
    duplicates: int
    timeliness: float
    latency: LatencyStats


@dataclass(frozen=True, slots=True)
class SportProfile:
    """Lo que el harness necesita saber de un deporte."""

    name: str
    exact_label: str
    estimate_label: str
    simulate: Callable[[int], list[MatchEvent]]
    batch: Callable[[list[MatchEvent]], SportPlane]
    stream: Callable[[list[MatchEvent], float], SportRun]
    #: El margen de la marca de agua elegido para el deporte, con datos.
    allowed_lateness_s: float
    #: El motor del deporte, vacío, para el banco de carga (#91).
    engine: Callable[[], StreamEngine[object]] = MatchEngine


def _possession(events: list[MatchEvent], max_gap_s: float) -> dict[str, float]:
    tracker = PossessionTracker(max_in_play_gap_s=max_gap_s)
    for event in events:
        tracker.apply(event)
    return tracker.snapshot().running_seconds


def _football_batch(events: list[MatchEvent]) -> SportPlane:
    summary = summarize_events(events)
    return SportPlane(
        exact=sum(summary.goals.values()),
        estimate=summary.total_xg,
        possession_seconds=_possession(events, MAX_IN_PLAY_GAP_S),
        event_count=summary.event_count,
    )


def _run(
    result: EngineResult[object], exact: int, estimate: dict[str, float], event_count: int
) -> SportRun:
    """Lo que dijo el motor, en los términos que comparten los deportes."""
    return SportRun(
        plane=SportPlane(
            exact=exact,
            estimate=estimate,
            possession_seconds=result.possession.running_seconds,
            event_count=event_count,
            dropped_late=result.watermark.dropped_late,
        ),
        duplicates=result.dedup.duplicates,
        timeliness=result.watermark.timeliness,
        latency=result.latency,
    )


def _football_stream(events: list[MatchEvent], allowed_lateness_s: float) -> SportRun:
    result = MatchEngine(allowed_lateness_s=allowed_lateness_s).process_all(events)
    summary = result.summary
    return _run(result, sum(summary.goals.values()), summary.total_xg, summary.event_count)


def _basketball_batch(events: list[MatchEvent]) -> SportPlane:
    summary = summarize_basketball(events)
    return SportPlane(
        exact=sum(summary.points.values()),
        estimate=summary.expected_points,
        possession_seconds=_possession(events, BASKETBALL_MAX_IN_PLAY_GAP_S),
        event_count=summary.event_count,
    )


def _basketball_stream(events: list[MatchEvent], allowed_lateness_s: float) -> SportRun:
    result = basketball_engine(allowed_lateness_s).process_all(events)
    summary = result.summary
    return _run(result, sum(summary.points.values()), summary.expected_points, summary.event_count)


def _american_football_batch(events: list[MatchEvent]) -> SportPlane:
    summary = summarize_american_football(events)
    return SportPlane(
        exact=sum(summary.points.values()),
        estimate=summary.kick_expected_points,
        possession_seconds=_possession(events, AMERICAN_FOOTBALL_MAX_IN_PLAY_GAP_S),
        event_count=summary.event_count,
    )


def _american_football_stream(events: list[MatchEvent], allowed_lateness_s: float) -> SportRun:
    result = american_football_engine(allowed_lateness_s).process_all(events)
    summary = result.summary
    exact = sum(summary.points.values())
    return _run(result, exact, summary.kick_expected_points, summary.event_count)


FOOTBALL = SportProfile(
    "football",
    "goals",
    "total_xg",
    simulate_match,
    _football_batch,
    _football_stream,
    DEFAULT_ALLOWED_LATENESS_S,
)
BASKETBALL = SportProfile(
    "basketball",
    "points",
    "expected_points",
    simulate_basketball,
    _basketball_batch,
    _basketball_stream,
    BASKETBALL_ALLOWED_LATENESS_S,
    basketball_engine,
)
AMERICAN_FOOTBALL = SportProfile(
    "american_football",
    "points",
    "kick_expected_points",
    simulate_american_football,
    _american_football_batch,
    _american_football_stream,
    AMERICAN_FOOTBALL_ALLOWED_LATENESS_S,
    american_football_engine,
)
SPORTS: dict[str, SportProfile] = {
    sport.name: sport for sport in (FOOTBALL, BASKETBALL, AMERICAN_FOOTBALL)
}


@dataclass(frozen=True, slots=True)
class SportDivergence:
    """Cuánto se separan los dos planos, en los términos del deporte."""

    possession_share: float
    estimate: float
    exact: int
    events: int

    def breaches(self, thresholds: Thresholds | None = None) -> tuple[Breach, ...]:
        """Los umbrales del OE-2 que se superan: lo exacto y los eventos, sin margen."""
        limits = thresholds or Thresholds()
        found = []
        if self.possession_share >= limits.possession_share:
            found.append(Breach("possession_share", self.possession_share, limits.possession_share))
        if self.estimate >= limits.total_xg:
            found.append(Breach("estimate", self.estimate, limits.total_xg))
        if self.exact:
            found.append(Breach("exact", float(self.exact), 0.0))
        if self.events:
            found.append(Breach("events", float(self.events), 0.0))
        return tuple(found)

    def passes(self, thresholds: Thresholds | None = None) -> bool:
        """Indica si la separación cabe dentro de lo declarado."""
        return not self.breaches(thresholds)


def _widest_gap(reference: dict[str, float], observed: dict[str, float]) -> float:
    if not reference:
        return 0.0
    return max(abs(value - observed.get(team, 0.0)) for team, value in reference.items())


def measure(reference: SportPlane, observed: SportPlane) -> SportDivergence:
    """Compara el motor contra la referencia, como ``core.divergence.measure``."""
    return SportDivergence(
        possession_share=round(
            _widest_gap(reference.possession_share, observed.possession_share), 6
        ),
        estimate=round(_widest_gap(reference.estimate, observed.estimate), 6),
        exact=abs(reference.exact - observed.exact),
        events=reference.event_count - observed.event_count - observed.dropped_late,
    )


@dataclass(frozen=True, slots=True)
class SportScenarioResult:
    """Cómo le fue al motor con un escenario, en un deporte."""

    scenario: Scenario
    divergence: SportDivergence
    run: SportRun
    passed: bool


def run_sport_harness(
    sport: SportProfile,
    events: list[MatchEvent],
    seed: int,
    scenarios: tuple[Scenario, ...] = DEFAULT_SCENARIOS,
    allowed_lateness_s: float | None = None,
) -> tuple[SportScenarioResult, ...]:
    """Ejecuta cada escenario y mide la separación con el batch, con los umbrales del OE-2."""
    if not events:
        raise ValueError("no hay eventos que someter al harness")
    margin = sport.allowed_lateness_s if allowed_lateness_s is None else allowed_lateness_s
    reference = sport.batch(events)
    results = []
    for scenario in scenarios:
        run = sport.stream(degrade(events, scenario, seed), margin)
        divergence = measure(reference, run.plane)
        results.append(SportScenarioResult(scenario, divergence, run, divergence.passes()))
    return tuple(results)
