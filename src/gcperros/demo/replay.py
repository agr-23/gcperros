"""Un partido que pasa en el tiempo, para enseñarlo en vivo (#30).

Los generadores producen el partido entero de una vez; un cliente quiere verlo
ocurrir. Esta repetición recorre el partido con su propio reloj: cada vez que
avanza, entrega al motor lo que ya ocurrió y deja consultar el estado tal como
lo publicaría el sistema real.

El reloj es tiempo del partido, no de pared. Quién lo hace avanzar y a qué
velocidad es asunto del servidor; aquí, con la misma semilla, el mismo segundo
de partido da siempre el mismo estado.

``Replay`` es lo común a cualquier deporte: entregar al motor lo que ya ocurrió.
Cada deporte pone su reloj (#92): el fútbol cuenta minutos desde el inicio de
cada parte; el baloncesto, cuartos con su reloj de juego, que se para.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Generic, TypeVar

from gcperros.core import court, gridiron
from gcperros.core.american_football_stats import AmericanFootballSummary
from gcperros.core.basketball_stats import BasketballSummary
from gcperros.core.contracts import MatchEvent
from gcperros.core.stats import MatchSummary
from gcperros.engine.american_football_state import (
    AmericanFootballLiveState,
    american_football_engine,
)
from gcperros.engine.basketball_state import BasketballLiveState, basketball_engine
from gcperros.engine.pipeline import MatchEngine, StreamEngine
from gcperros.engine.sport import SportState
from gcperros.engine.state import LiveMatchState
from gcperros.engine.watermark import DEFAULT_ALLOWED_LATENESS_S
from gcperros.generators.match import HALF_DURATION_S

S_co = TypeVar("S_co", covariant=True)


@dataclass(frozen=True, slots=True)
class ReplayClock:
    """En qué punto del partido está la repetición."""

    elapsed_s: float
    period: int
    minute: int
    phase: str
    #: Lo que queda en el reloj de juego del periodo. Sólo en baloncesto, donde
    #: el reloj se para y el minuto no basta para leerlo.
    game_clock_s: float | None = None


class Replay(Generic[S_co]):
    """Recorre un partido ya simulado al ritmo que se le pida, de cualquier deporte."""

    __slots__ = ("_engine", "_events", "_finished", "_kickoff", "_next", "_now", "_period_starts")

    #: El deporte, tal como lo nombra la página.
    sport = ""

    #: Local y visitante, cuando el flujo no permite deducirlos (#92). Sin él,
    #: se respeta el orden en que los equipos aparecen.
    teams: tuple[str, str] | None = None

    def __init__(self, events: list[MatchEvent], engine: StreamEngine[S_co]) -> None:
        """Prepara la repetición en el inicio, sin nada entregado.

        Raises:
            ValueError: Si no hay eventos que repetir.
        """
        if not events:
            raise ValueError("no hay eventos que repetir")
        self._events = sorted(events, key=lambda event: event.event_time)
        self._engine = engine
        self._kickoff = self._events[0].event_time
        self._now = self._kickoff
        self._next = 0
        self._finished = False
        # Cada parte arranca con su primer evento: el minuto sale de los datos,
        # no de suponer cuánto duraron el descuento o el descanso.
        self._period_starts: dict[int, datetime] = {}
        for event in self._events:
            self._period_starts.setdefault(_period(event), event.event_time)

    @property
    def match_id(self) -> str:
        """Identificador del partido que se repite."""
        return self._events[0].match_id

    @property
    def engine(self) -> StreamEngine[S_co]:
        """El motor que recibe las entregas, para leer su estado sin tocarlo."""
        return self._engine

    def fresh_state(self) -> SportState[S_co]:
        """Un estado vacío del deporte, para reconstruir de qué sale un número."""
        raise NotImplementedError

    @property
    def duration_s(self) -> float:
        """Segundos del primer evento al último, descanso incluido."""
        return (self._events[-1].event_time - self._kickoff).total_seconds()

    @property
    def now(self) -> datetime:
        """Instante del partido en el que está el reloj."""
        return self._now

    @property
    def elapsed_s(self) -> float:
        """Segundos de partido ya recorridos."""
        return (self._now - self._kickoff).total_seconds()

    @property
    def finished(self) -> bool:
        """Verdadero cuando ya sonó el pitido final y el motor se vació."""
        return self._finished

    def advance_to(self, elapsed_s: float) -> int:
        """Lleva el reloj hasta ``elapsed_s`` y entrega lo que ocurrió hasta ahí.

        El reloj no retrocede: pedir un instante anterior no hace nada. Al
        llegar al final se vacía el motor, que es lo que haría el sistema real
        al cerrarse el flujo.

        Returns:
            Cuántos eventos se entregaron al motor en esta llamada.
        """
        # El reloj se detiene en el pitido final: más allá no ocurre nada.
        target = min(
            self._kickoff + timedelta(seconds=max(elapsed_s, 0.0)),
            self._events[-1].event_time,
        )
        if target <= self._now:
            return 0
        self._now = target

        delivered = 0
        while self._next < len(self._events) and self._events[self._next].event_time <= target:
            self._engine.process(self._events[self._next])
            self._next += 1
            delivered += 1

        if self._next == len(self._events) and not self._finished:
            self._engine.flush()
            self._finished = True
        return delivered

    def clock(self) -> ReplayClock:
        """Periodo, minuto y fase del partido en el instante actual."""
        raise NotImplementedError

    def minute_at(self, instant: datetime) -> int:
        """Minuto de partido de un instante."""
        raise NotImplementedError

    @property
    def delivered(self) -> tuple[MatchEvent, ...]:
        """Los eventos ya entregados al motor, en orden de tiempo."""
        return tuple(self._events[: self._next])

    def _phase(self, name: str) -> str:
        """La fase según lo entregado: antes de empezar, entre periodos, o el periodo."""
        if self._finished:
            return "final"
        if self._next == 0:
            return "previa"
        if _period(self._events[self._next]) > _period(self._events[self._next - 1]):
            return "descanso"
        return f"{name}-{_period(self._events[self._next - 1])}"


class MatchReplay(Replay[MatchSummary]):
    """Un partido de fútbol: dos partes con su descanso."""

    __slots__ = ("_match",)
    sport = "football"

    def __init__(
        self,
        events: list[MatchEvent],
        allowed_lateness_s: float = DEFAULT_ALLOWED_LATENESS_S,
    ) -> None:
        """Prepara la repetición en el pitido inicial, sin nada entregado.

        Raises:
            ValueError: Si no hay eventos que repetir.
        """
        engine = MatchEngine(allowed_lateness_s=allowed_lateness_s)
        super().__init__(events, engine)
        self._match = engine

    @property
    def engine(self) -> MatchEngine:
        """El motor del fútbol, con todo lo que sólo él sabe hacer."""
        return self._match

    def fresh_state(self) -> LiveMatchState:
        """Un estado de fútbol vacío."""
        return LiveMatchState()

    def clock(self) -> ReplayClock:
        """Parte, minuto y fase del partido en el instante actual."""
        phase = self._phase("parte")

        current = max(
            (p for p, start in self._period_starts.items() if start <= self._now), default=1
        )
        return ReplayClock(
            elapsed_s=round(self.elapsed_s, 1),
            period=current,
            minute=self.minute_at(self._now) if phase != "descanso" else 45,
            phase=phase,
        )

    def minute_at(self, instant: datetime) -> int:
        """Minuto de partido de un instante, contando cada parte desde su inicio."""
        current = max(
            (p for p, start in self._period_starts.items() if start <= instant), default=1
        )
        offset_s = (instant - self._period_starts.get(current, self._kickoff)).total_seconds()
        return int((current - 1) * HALF_DURATION_S / 60 + offset_s / 60)


class _QuarterReplay(Replay[S_co]):
    """Un deporte de cuartos con reloj de juego: el baloncesto y el fútbol americano.

    Cada subclase declara su reglamento —cuántos cuartos, cuánto dura cada uno y
    cuánto la prórroga— y su motor; el reloj y el minuto se leen igual.
    """

    __slots__ = ("_times", "teams")
    regulation_periods: int
    period_s: int
    overtime_s: int

    def __init__(
        self,
        events: list[MatchEvent],
        engine: StreamEngine[S_co],
        teams: tuple[str, str] | None = None,
    ) -> None:
        """Prepara la repetición. El primer evento no dice quién es local: ``teams`` sí."""
        super().__init__(events, engine)
        self.teams = teams
        self._times = [event.event_time for event in self._events]

    def _last_at(self, instant: datetime) -> MatchEvent | None:
        index = bisect_right(self._times, instant)
        return self._events[index - 1] if index else None

    def clock(self) -> ReplayClock:
        """Cuarto, reloj de juego y fase en el instante actual."""
        last = self._last_at(self._now)
        period = _period(last) if last is not None else 1
        game_clock = _clock(last) if last is not None else float(self.period_s)
        return ReplayClock(
            elapsed_s=round(self.elapsed_s, 1),
            period=period,
            minute=self.minute_at(self._now),
            phase=self._phase("cuarto"),
            game_clock_s=round(game_clock, 1),
        )

    def minute_at(self, instant: datetime) -> int:
        """Minutos de juego transcurridos hasta ese instante, prórrogas incluidas."""
        last = self._last_at(instant)
        if last is None:
            return 0
        period = _period(last)
        regulation = min(period - 1, self.regulation_periods) * self.period_s
        overtimes = max(period - 1 - self.regulation_periods, 0) * self.overtime_s
        length = self.period_s if period <= self.regulation_periods else self.overtime_s
        return int((regulation + overtimes + length - _clock(last)) / 60)


class BasketballReplay(_QuarterReplay[BasketballSummary]):
    """Un partido de baloncesto: cuartos, descansos y prórrogas, con reloj de juego."""

    __slots__ = ()
    sport = "basketball"
    regulation_periods = court.REGULATION_PERIODS
    period_s = court.PERIOD_DURATION_S
    overtime_s = court.OVERTIME_DURATION_S

    def __init__(self, events: list[MatchEvent], teams: tuple[str, str] | None = None) -> None:
        """Prepara la repetición en el salto inicial, con el motor del baloncesto."""
        super().__init__(events, basketball_engine(), teams)

    def fresh_state(self) -> BasketballLiveState:
        """Un estado de baloncesto vacío."""
        return BasketballLiveState()


class AmericanFootballReplay(_QuarterReplay[AmericanFootballSummary]):
    """Un partido de fútbol americano: cuatro cuartos de quince minutos y prórroga."""

    __slots__ = ()
    sport = "american_football"
    regulation_periods = gridiron.REGULATION_PERIODS
    period_s = gridiron.PERIOD_DURATION_S
    overtime_s = gridiron.OVERTIME_DURATION_S

    def __init__(self, events: list[MatchEvent], teams: tuple[str, str] | None = None) -> None:
        """Prepara la repetición en el saque inicial, con el motor del fútbol americano."""
        super().__init__(events, american_football_engine(), teams)

    def fresh_state(self) -> AmericanFootballLiveState:
        """Un estado de fútbol americano vacío."""
        return AmericanFootballLiveState()


def _clock(event: MatchEvent) -> float:
    clock = event.attrs.get("clock_s", 0.0)
    if isinstance(clock, bool) or not isinstance(clock, int | float):
        return 0.0
    return float(clock)


def _period(event: MatchEvent) -> int:
    period = event.attrs.get("period", 1)
    return period if isinstance(period, int) else 1
