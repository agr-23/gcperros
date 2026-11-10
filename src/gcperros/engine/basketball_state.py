"""Estado vivo de un partido de baloncesto (#89).

La contraparte en streaming de ``core.basketball_stats.summarize_basketball``,
como ``engine/state.py`` lo es del fútbol. Recibe los eventos ya deduplicados y
en orden, y en todo momento puede proyectarse a la misma estructura que el plano
batch: esa igualdad es la que el harness comprueba.

Cada número lleva su linaje: qué eventos lo formaron, plegados en una huella
(HU-18). Los puntos esperados llevan además la versión del modelo que los
calcula.
"""

from __future__ import annotations

from collections.abc import Mapping

from gcperros.core import court, expected_points
from gcperros.core.basketball_stats import BasketballSummary
from gcperros.core.contracts import BASKETBALL_CONTRACT_VERSION, MatchEvent
from gcperros.core.lineage import LineageAccumulator, LineageRecord
from gcperros.core.stats import as_float
from gcperros.engine.pipeline import StreamEngine
from gcperros.engine.state import WHOLE_MATCH

#: Los contadores enteros del resumen, por equipo.
_COUNTERS: tuple[str, ...] = (
    "points",
    "two_attempted",
    "two_made",
    "three_attempted",
    "three_made",
    "free_throws_attempted",
    "free_throws_made",
    "offensive_rebounds",
    "defensive_rebounds",
    "turnovers",
    "fouls",
    "timeouts",
    "possessions",
)


class BasketballLiveState:
    """Acumula los indicadores del baloncesto a medida que llegan los eventos."""

    contract_version = BASKETBALL_CONTRACT_VERSION
    team_indicators: tuple[str, ...] = ("points", "expected_points", *_COUNTERS[1:])
    models_by_indicator: Mapping[str, Mapping[str, str]] = {
        "expected_points": {"expected_points": expected_points.MODEL_VERSION}
    }

    __slots__ = ("_counters", "_event_count", "_expected", "_lineage", "_teams")

    def __init__(self) -> None:
        """Crea un estado vacío: los equipos se aprenden del propio flujo."""
        self._teams: dict[str, None] = {}
        self._event_count = 0
        self._counters: dict[str, dict[str, int]] = {name: {} for name in _COUNTERS}
        self._expected: dict[str, float] = {}
        self._lineage: dict[tuple[str, str], LineageAccumulator] = {}

    def _register(self, team: str) -> None:
        if team in self._teams:
            return
        self._teams[team] = None
        for counter in self._counters.values():
            counter[team] = 0
        self._expected[team] = 0.0

    def _count(self, indicator: str, event: MatchEvent, amount: int = 1) -> None:
        self._counters[indicator][event.team] += amount
        self._trace(indicator, event.team, event.event_id)

    def _expect(self, event: MatchEvent, value: float) -> None:
        self._expected[event.team] += value
        self._trace("expected_points", event.team, event.event_id)

    def apply(self, event: MatchEvent) -> None:
        """Incorpora un evento al estado. Duplicados y orden los resolvió el motor."""
        self._register(event.team)
        self._event_count += 1
        self._trace("event_count", WHOLE_MATCH, event.event_id)
        attrs = event.attrs

        match event.event_type:
            case "shot":
                value = int(as_float(attrs["points_value"]))
                three = value == court.THREE_POINTS
                self._count("three_attempted" if three else "two_attempted", event)
                self._expect(event, value * as_float(attrs["make_probability"]))
                if attrs["made"] is True:
                    self._count("three_made" if three else "two_made", event)
                    self._count("points", event, value)
            case "free_throw":
                self._count("free_throws_attempted", event)
                self._expect(event, as_float(attrs["make_probability"]))
                if attrs["made"] is True:
                    self._count("free_throws_made", event)
                    self._count("points", event)
            case "rebound":
                offensive = attrs["kind"] == "offensive"
                self._count("offensive_rebounds" if offensive else "defensive_rebounds", event)
            case "turnover":
                self._count("turnovers", event)
            case "foul":
                self._count("fouls", event)
            case "timeout":
                self._count("timeouts", event)
            case "possession_change":
                self._count("possessions", event)

    def _trace(self, indicator: str, scope: str, event_id: str) -> None:
        self._lineage.setdefault((indicator, scope), LineageAccumulator()).add(event_id)

    def lineage(self, indicator: str, scope: str) -> LineageRecord:
        """Explica de dónde sale un indicador. Uno a cero tiene linaje vacío."""
        accumulator = self._lineage.get((indicator, scope), LineageAccumulator())
        return accumulator.record(indicator, scope)

    def lineage_records(self) -> tuple[LineageRecord, ...]:
        """Linaje de todos los indicadores con al menos un evento detrás."""
        return tuple(
            accumulator.record(indicator, scope)
            for (indicator, scope), accumulator in self._lineage.items()
        )

    def summary(self) -> BasketballSummary:
        """Proyecta el estado a la misma estructura del plano batch."""
        c = {name: dict(values) for name, values in self._counters.items()}
        return BasketballSummary(
            event_count=self._event_count,
            points=c["points"],
            expected_points={team: round(value, 4) for team, value in self._expected.items()},
            two_attempted=c["two_attempted"],
            two_made=c["two_made"],
            three_attempted=c["three_attempted"],
            three_made=c["three_made"],
            free_throws_attempted=c["free_throws_attempted"],
            free_throws_made=c["free_throws_made"],
            offensive_rebounds=c["offensive_rebounds"],
            defensive_rebounds=c["defensive_rebounds"],
            turnovers=c["turnovers"],
            fouls=c["fouls"],
            timeouts=c["timeouts"],
            possessions=c["possessions"],
        )

    @property
    def event_count(self) -> int:
        """Cuántos eventos se han aplicado."""
        return self._event_count

    @property
    def teams(self) -> tuple[str, ...]:
        """Equipos conocidos, en el orden en que aparecieron en el flujo."""
        return tuple(self._teams)


#: Hueco máximo entre eventos que sigue contando como juego (#91). El del
#: fútbol, 10 s, descarta el 90 % del tiempo vivo del baloncesto, donde dos
#: eventos con el balón vivo pueden separarse hasta 24 s. No hay banda vacía que
#: separe juego y parón —hay parones de 6 s—, así que el corte lo pone el
#: reglamento: ningún hueco vivo supera el reloj de posesión.
BASKETBALL_MAX_IN_PLAY_GAP_S = float(court.SHOT_CLOCK_S)

#: Margen de la marca de agua del baloncesto (#91). Medido como el del fútbol:
#: el mínimo con el que los seis escenarios comprometidos cumplen el OE-2 en 12
#: partidos. En fútbol sale 10 s; en baloncesto, con 10 s falla 1 de 72 y con
#: 15 s ninguno. Con un evento cada ~12 s, el que adelanta a otro ya le saca más
#: de 10 s, así que el margen tiene que superar el hueco típico entre eventos.
BASKETBALL_ALLOWED_LATENESS_S = 15.0


def basketball_engine(
    allowed_lateness_s: float = BASKETBALL_ALLOWED_LATENESS_S,
    max_in_play_gap_s: float = BASKETBALL_MAX_IN_PLAY_GAP_S,
) -> StreamEngine[BasketballSummary]:
    """El mismo motor del fútbol, con el estado y el corte de posesión del baloncesto."""
    return StreamEngine(
        BasketballLiveState(),
        allowed_lateness_s=allowed_lateness_s,
        max_in_play_gap_s=max_in_play_gap_s,
    )
