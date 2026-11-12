"""Estado vivo de un partido de fútbol americano (sección 22).

La contraparte en streaming de ``core.american_football_stats``, con la misma
regla que el baloncesto: el motor de siempre, con otro estado inyectado. Aplica
cada evento con las mismas funciones que el resumen batch —``scoring`` y
``kick_value``—, así que proyectarse a la misma estructura no depende de que
dos implementaciones coincidan. Cada número lleva su linaje.
"""

from __future__ import annotations

from collections.abc import Mapping

from gcperros.core import kicking
from gcperros.core.american_football_stats import (
    COUNTERS,
    AmericanFootballSummary,
    kick_value,
    scoring,
)
from gcperros.core.contracts import AMERICAN_FOOTBALL_CONTRACT_VERSION, MatchEvent
from gcperros.core.lineage import LineageAccumulator, LineageRecord
from gcperros.engine.pipeline import StreamEngine
from gcperros.engine.state import WHOLE_MATCH


class AmericanFootballLiveState:
    """Acumula los indicadores del fútbol americano a medida que llegan los eventos."""

    contract_version = AMERICAN_FOOTBALL_CONTRACT_VERSION
    team_indicators: tuple[str, ...] = ("points", "kick_expected_points", *COUNTERS[1:])
    models_by_indicator: Mapping[str, Mapping[str, str]] = {
        "kick_expected_points": {"kick": kicking.MODEL_VERSION}
    }

    __slots__ = ("_counters", "_event_count", "_expected", "_lineage", "_teams")

    def __init__(self) -> None:
        """Crea un estado vacío: los equipos se aprenden del propio flujo."""
        self._teams: dict[str, None] = {}
        self._event_count = 0
        self._counters: dict[str, dict[str, int]] = {name: {} for name in COUNTERS}
        self._expected: dict[str, float] = {}
        self._lineage: dict[tuple[str, str], LineageAccumulator] = {}

    def apply(self, event: MatchEvent) -> None:
        """Incorpora un evento al estado. Duplicados y orden los resolvió el motor."""
        team = event.team
        if team not in self._teams:
            self._teams[team] = None
            for counter in self._counters.values():
                counter[team] = 0
            self._expected[team] = 0.0
        self._event_count += 1
        self._trace("event_count", WHOLE_MATCH, event.event_id)
        for name, amount in scoring(event).items():
            self._counters[name][team] += amount
            self._trace(name, team, event.event_id)
        value = kick_value(event)
        if event.event_type in ("field_goal", "conversion"):
            self._expected[team] += value
            self._trace("kick_expected_points", team, event.event_id)

    def _trace(self, indicator: str, scope: str, event_id: str) -> None:
        self._lineage.setdefault((indicator, scope), LineageAccumulator()).add(event_id)

    def lineage(self, indicator: str, scope: str) -> LineageRecord:
        """Explica de dónde sale un indicador. Uno a cero tiene linaje vacío."""
        accumulator = self._lineage.get((indicator, scope), LineageAccumulator())
        return accumulator.record(indicator, scope)

    def lineage_records(self) -> tuple[LineageRecord, ...]:
        """Linaje de todos los indicadores con al menos un evento detrás."""
        return tuple(acc.record(name, scope) for (name, scope), acc in self._lineage.items())

    def summary(self) -> AmericanFootballSummary:
        """Proyecta el estado a la misma estructura del plano batch."""
        return AmericanFootballSummary(
            event_count=self._event_count,
            kick_expected_points={team: round(v, 4) for team, v in self._expected.items()},
            **{name: dict(values) for name, values in self._counters.items()},
        )

    @property
    def event_count(self) -> int:
        """Cuántos eventos se han aplicado."""
        return self._event_count

    @property
    def teams(self) -> tuple[str, ...]:
        """Equipos conocidos, en el orden en que aparecieron en el flujo."""
        return tuple(self._teams)


#: Hueco máximo entre eventos que sigue contando como juego. Los huecos vivos no
#: pasan del reloj de jugada (40 s) y los parones empiezan pasados los 55: el
#: corte va en medio de esa banda vacía, como el del fútbol (sección 22).
AMERICAN_FOOTBALL_MAX_IN_PLAY_GAP_S = 50.0

#: Margen de la marca de agua, medido como el de los otros dos: el mínimo con el
#: que los seis escenarios comprometidos cumplen el OE-2. Sobre 60 partidos, con
#: 10 s un gol de campo llega tarde en el escenario hostil; con 15 s, ninguno.
AMERICAN_FOOTBALL_ALLOWED_LATENESS_S = 15.0


def american_football_engine(
    allowed_lateness_s: float = AMERICAN_FOOTBALL_ALLOWED_LATENESS_S,
    max_in_play_gap_s: float = AMERICAN_FOOTBALL_MAX_IN_PLAY_GAP_S,
) -> StreamEngine[AmericanFootballSummary]:
    """El mismo motor, con el estado y el corte de posesión del fútbol americano."""
    return StreamEngine(
        AmericanFootballLiveState(),
        allowed_lateness_s=allowed_lateness_s,
        max_in_play_gap_s=max_in_play_gap_s,
    )
