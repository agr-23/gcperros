"""El partido de baloncesto tal como lo ve el mercado (#90).

Es ``core/matchstate.py`` para el segundo deporte, y con la misma promesa: el
generador de cuotas y el detector de discrepancias leen el partido **con la misma
lectura**, para que una discrepancia no pueda venir de que uno va por detrás del
otro.

Dos diferencias con el fútbol. El salto inicial no dice quién es local, así que
los equipos se declaran al crear el lector, como los conocería un sistema real
por el calendario. Y lo que mueve el mercado no es un gol suelto sino una
**racha**: varios puntos seguidos de un equipo, que suelen acabar con un tiempo
muerto del otro.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gcperros.core import court
from gcperros.core.basketball_odds import BasketballState
from gcperros.core.contracts import BasketballOddsTrigger, MatchEvent
from gcperros.core.stats import as_float

#: Puntos seguidos de un equipo a partir de los cuales el mercado reacciona.
RUN_POINTS = 8


def points_scored(event: MatchEvent) -> int:
    """Cuántos puntos sube al marcador un evento: un tiro anotado o un libre."""
    if event.attrs.get("made") is not True:
        return 0
    if event.event_type == "free_throw":
        return 1
    if event.event_type == "shot":
        return int(as_float(event.attrs["points_value"]))
    return 0


@dataclass(slots=True)
class BasketballStateTracker:
    """Reconstruye periodo, reloj y marcador evento a evento."""

    home_team: str
    away_team: str
    period: int = 1
    clock_s: float = float(court.PERIOD_DURATION_S)
    points: dict[str, int] = field(default_factory=dict)
    _run_team: str = ""
    _run_points: int = 0

    def apply(self, event: MatchEvent) -> BasketballOddsTrigger | None:
        """Incorpora un evento y dice si es de los que mueven el mercado.

        Returns:
            ``"run"`` cuando un equipo alcanza una racha de ``RUN_POINTS``,
            ``"timeout"`` en un tiempo muerto, o nada.
        """
        period, clock = event.attrs.get("period"), event.attrs.get("clock_s")
        if isinstance(period, int):
            self.period = period
        if isinstance(clock, int | float) and not isinstance(clock, bool):
            self.clock_s = float(clock)

        if event.event_type == "timeout":
            return "timeout"

        scored = points_scored(event)
        if not scored:
            return None
        self.points[event.team] = self.points.get(event.team, 0) + scored
        before = self._run_points if event.team == self._run_team else 0
        self._run_team, self._run_points = event.team, before + scored
        # Sólo al cruzar el umbral: una racha de 12 no es tres señales.
        return "run" if before < RUN_POINTS <= self._run_points else None

    def state(self) -> BasketballState:
        """El partido en este instante, listo para el modelo de mercado."""
        return BasketballState(
            period=self.period,
            clock_s=self.clock_s,
            points_home=self.points.get(self.home_team, 0),
            points_away=self.points.get(self.away_team, 0),
        )
