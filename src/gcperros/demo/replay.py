"""Un partido que pasa en el tiempo, para enseñarlo en vivo (#30).

Los generadores producen el partido entero de una vez; un cliente quiere verlo
ocurrir. Esta repetición recorre el partido con su propio reloj: cada vez que
avanza, entrega al motor lo que ya ocurrió y deja consultar el estado tal como
lo publicaría el sistema real.

El reloj es tiempo del partido, no de pared. Quién lo hace avanzar y a qué
velocidad es asunto del servidor; aquí, con la misma semilla, el mismo segundo
de partido da siempre el mismo estado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from gcperros.core.contracts import MatchEvent
from gcperros.engine.pipeline import MatchEngine
from gcperros.engine.watermark import DEFAULT_ALLOWED_LATENESS_S
from gcperros.generators.match import HALF_DURATION_S


@dataclass(frozen=True, slots=True)
class ReplayClock:
    """En qué punto del partido está la repetición."""

    elapsed_s: float
    period: int
    minute: int
    phase: str


class MatchReplay:
    """Recorre un partido ya simulado al ritmo que se le pida."""

    __slots__ = ("_engine", "_events", "_finished", "_kickoff", "_next", "_now", "_period_starts")

    def __init__(
        self,
        events: list[MatchEvent],
        allowed_lateness_s: float = DEFAULT_ALLOWED_LATENESS_S,
    ) -> None:
        """Prepara la repetición en el pitido inicial, sin nada entregado.

        Raises:
            ValueError: Si no hay eventos que repetir.
        """
        if not events:
            raise ValueError("no hay eventos que repetir")
        self._events = sorted(events, key=lambda event: event.event_time)
        self._engine = MatchEngine(allowed_lateness_s=allowed_lateness_s)
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
    def engine(self) -> MatchEngine:
        """El motor que recibe las entregas, para leer su estado sin tocarlo."""
        return self._engine

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
        """Parte, minuto y fase del partido en el instante actual."""
        if self._finished:
            phase = "final"
        elif self._next == 0:
            phase = "previa"
        else:
            phase = f"parte-{_period(self._events[self._next - 1])}"
            upcoming = self._events[self._next]
            if _period(upcoming) > _period(self._events[self._next - 1]):
                phase = "descanso"

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

    @property
    def delivered(self) -> tuple[MatchEvent, ...]:
        """Los eventos ya entregados al motor, en orden de tiempo."""
        return tuple(self._events[: self._next])


def _period(event: MatchEvent) -> int:
    period = event.attrs.get("period", 1)
    return period if isinstance(period, int) else 1
