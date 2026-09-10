"""Estado del partido tal como lo ve el mercado: minuto, marcador y expulsiones.

Es la lectura del partido que necesita cualquiera que quiera poner precio a un
resultado. El generador de cuotas (HU-9) la usa para fabricar precios; el
detector de discrepancias (HU-19) la usa para calcular lo que el modelo propio
cree. **Tiene que ser la misma lectura en ambos lados**: si el mercado y el
modelo partieran de estados distintos, una discrepancia podría venir de que uno
va un minuto por detrás del otro y no de un precio mal puesto, y la señal
dejaría de significar lo que promete.

Todo se deriva del propio flujo de eventos, no de la configuración con la que se
simuló el partido: en producción esto consume de un topic y no tiene acceso a
otra cosa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from gcperros.core.contracts import MatchEvent
from gcperros.core.odds import MatchState

#: Identificador del segundo tiempo dentro de ``attrs``, tal como lo emite el
#: generador de partidos. Es un valor del contrato, no de la simulación.
SECOND_HALF_PERIOD = 2

#: Minuto en el que arranca el segundo tiempo, con independencia de cuánto haya
#: durado el añadido del primero.
SECOND_HALF_START_MINUTE = 45.0


def kickoff_teams(events: list[MatchEvent]) -> tuple[str, str]:
    """Identifica local y visitante leyendo el saque inicial del primer tiempo.

    Args:
        events: Eventos del partido, en orden cronológico.

    Returns:
        Par ``(local, visitante)``.

    Raises:
        ValueError: Si el flujo no trae un saque inicial del que deducirlos.
    """
    for event in events:
        if event.event_type == "possession_change" and event.attrs.get("reason") == "kickoff":
            home = event.attrs.get("to_team")
            away = event.attrs.get("from_team")
            if isinstance(home, str) and isinstance(away, str):
                return home, away
    raise ValueError("el flujo no contiene un saque inicial del que deducir los equipos")


@dataclass(slots=True)
class MatchClock:
    """Traduce tiempo de pared a minuto de partido.

    El reloj de pared incluye el descanso, así que no se puede dividir entre
    sesenta y quedarse tranquilo: entre el minuto 45 y el 46 pasan quince
    minutos en los que el partido no avanza.
    """

    first_half_start: datetime
    second_half_start: datetime | None = None

    def minute(self, moment: datetime) -> float:
        """Minuto de partido correspondiente a un instante de reloj de pared."""
        if self.second_half_start is not None and moment >= self.second_half_start:
            elapsed = (moment - self.second_half_start).total_seconds()
            return SECOND_HALF_START_MINUTE + elapsed / 60.0
        return (moment - self.first_half_start).total_seconds() / 60.0


def build_clock(events: list[MatchEvent]) -> MatchClock:
    """Construye el reloj a partir de un flujo completo."""
    second_half = next(
        (event.event_time for event in events if event.attrs.get("period") == SECOND_HALF_PERIOD),
        None,
    )
    return MatchClock(first_half_start=events[0].event_time, second_half_start=second_half)


@dataclass(slots=True)
class ScoreLine:
    """Marcador y expulsiones acumuladas hasta un instante."""

    home_team: str
    away_team: str
    goals_home: int = 0
    goals_away: int = 0
    reds_home: int = 0
    reds_away: int = 0

    def apply(self, event: MatchEvent) -> None:
        """Incorpora un evento relevante al marcador."""
        is_home = event.team == self.home_team
        if event.event_type == "goal":
            if is_home:
                self.goals_home += 1
            else:
                self.goals_away += 1
        elif event.event_type == "red_card":
            if is_home:
                self.reds_home += 1
            else:
                self.reds_away += 1

    def state(self, minute: float) -> MatchState:
        """Proyecta el marcador al estado que consume el modelo de cuotas."""
        return MatchState(
            minute=minute,
            goals_home=self.goals_home,
            goals_away=self.goals_away,
            red_cards_home=self.reds_home,
            red_cards_away=self.reds_away,
        )


@dataclass(slots=True)
class MatchStateTracker:
    """Sigue el estado del partido evento a evento.

    A diferencia de ``build_clock``, que necesita el flujo entero por delante,
    este va aprendiendo sobre la marcha: reconoce el saque inicial de cada tiempo
    según llega. Es lo que necesita un consumidor en vivo, que no puede mirar el
    futuro para saber cuándo empezó el segundo tiempo.
    """

    home_team: str | None = None
    away_team: str | None = None
    _clock: MatchClock | None = field(default=None, init=False)
    _score: ScoreLine | None = field(default=None, init=False)
    _last_minute: float = field(default=0.0, init=False)

    def apply(self, event: MatchEvent) -> None:
        """Incorpora un evento al estado."""
        if event.event_type == "possession_change" and event.attrs.get("reason") == "kickoff":
            self._start_period(event)

        if self._clock is None:
            self._clock = MatchClock(first_half_start=event.event_time)

        self._last_minute = self._clock.minute(event.event_time)

        if self._score is not None:
            self._score.apply(event)

    def _start_period(self, event: MatchEvent) -> None:
        """Aprende los equipos en el saque inicial y abre el segundo tiempo."""
        home = event.attrs.get("to_team")
        away = event.attrs.get("from_team")

        if self._score is None and isinstance(home, str) and isinstance(away, str):
            # El saque del primer tiempo lo hace el local, así que `to_team` es
            # el local. En el del segundo saca el visitante, y por eso los
            # equipos sólo se aprenden una vez.
            self.home_team, self.away_team = home, away
            self._score = ScoreLine(home_team=home, away_team=away)
            self._clock = MatchClock(first_half_start=event.event_time)
            return

        if event.attrs.get("period") == SECOND_HALF_PERIOD and self._clock is not None:
            self._clock.second_half_start = event.event_time

    @property
    def minute(self) -> float:
        """Minuto de partido del último evento aplicado."""
        return self._last_minute

    def state(self) -> MatchState:
        """Estado actual, listo para el modelo de probabilidad.

        Antes del saque inicial devuelve un partido sin empezar, que es la
        respuesta correcta: 0-0 en el minuto 0.
        """
        if self._score is None:
            return MatchState(minute=0.0, goals_home=0, goals_away=0)
        return self._score.state(self._last_minute)
