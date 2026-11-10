"""Generador determinista de cuotas del baloncesto (#90).

Es la HU-9 para el segundo deporte: las cuotas se derivan del partido que
produce el generador de baloncesto (#88), con las tres casas sintéticas de
siempre —los mismos retrasos y los mismos sesgos sobre el local— y sus márgenes
para los mercados nuevos.

Lo que cambia es qué provoca la ráfaga. En fútbol, un gol o una roja; en
baloncesto una canasta suelta no mueve casi nada, pero una **racha** de ocho
puntos seguidos sí, y el **tiempo muerto** que suele cortarla también. Entre
ráfagas, cada casa revisa sus precios con el mismo ritmo del fútbol y republica
sólo si se movieron lo bastante o si llevan demasiado en silencio.

La línea del total de puntos se fija al abrir y no se mueve durante el partido:
lo que cambia es el precio de cada lado. Es una simplificación declarada; un
operador real también corre la línea.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from gcperros.core.basketball_matchstate import BasketballStateTracker
from gcperros.core.basketball_odds import (
    BasketballState,
    moneyline_probabilities,
    opening_line,
    total_points_probabilities,
)
from gcperros.core.contracts import (
    BasketballMarket,
    BasketballOddsTrigger,
    MatchEvent,
    OddsUpdate,
    new_odds_event_id,
)
from gcperros.core.odds import probabilities_to_odds
from gcperros.generators.odds import (
    ODDS_HEARTBEAT_S,
    ODDS_MOVE_THRESHOLD,
    ODDS_TICK_S,
    OPERATORS,
    REACTION_JITTER_S,
    SETTLED_PROBABILITY,
    Operator,
)

BASKETBALL_MARKETS: tuple[BasketballMarket, ...] = ("moneyline", "total_points")

#: Las mismas casas, con sus márgenes para los mercados del baloncesto. Un
#: ganador de dos resultados admite menos margen que un 1X2 de tres.
_MARGINS: dict[str, dict[str, float]] = {
    "OP-A": {"moneyline": 1.045, "total_points": 1.040},
    "OP-B": {"moneyline": 1.060, "total_points": 1.055},
    "OP-C": {"moneyline": 1.052, "total_points": 1.047},
}
BASKETBALL_OPERATORS: tuple[Operator, ...] = tuple(
    Operator(op.name, _MARGINS[op.name], op.reaction_delay_s, op.home_strength) for op in OPERATORS
)


@dataclass(slots=True)
class _Moment:
    at: datetime
    operator_index: int
    trigger: BasketballOddsTrigger


@dataclass(slots=True)
class _Book:
    odds: dict[str, float]
    published_at: datetime
    settled: bool = False


def _relative_move(previous: dict[str, float], current: dict[str, float]) -> float:
    return max(abs(current[o] - previous[o]) / previous[o] for o in current)


class _BasketballOddsSimulator:
    """Máquina de estados del mercado. La API pública es ``simulate_basketball_odds``."""

    def __init__(
        self,
        seed: int,
        events: list[MatchEvent],
        teams: tuple[str, str],
        operators: tuple[Operator, ...],
    ) -> None:
        self._rng = random.Random(seed)
        self._events = events
        self._teams = teams
        self._operators = operators
        self._match_id = events[0].match_id
        self._line = opening_line()
        self._sequence = 0
        self._updates: list[OddsUpdate] = []
        self._books: dict[tuple[str, str], _Book] = {}

    def _triggers(self) -> list[tuple[datetime, BasketballOddsTrigger]]:
        """Las rachas y los tiempos muertos del partido, en su instante."""
        tracker = BasketballStateTracker(*self._teams)
        found: list[tuple[datetime, BasketballOddsTrigger]] = []
        for event in self._events:
            trigger = tracker.apply(event)
            if trigger is not None:
                found.append((event.event_time, trigger))
        return found

    def _moments(self) -> list[_Moment]:
        tipoff, final = self._events[0].event_time, self._events[-1].event_time
        triggers = self._triggers()
        moments: list[_Moment] = []
        for index, operator in enumerate(self._operators):
            moments.append(_Moment(tipoff, index, "open"))
            for at, trigger in triggers:
                delay = operator.reaction_delay_s + self._rng.uniform(*REACTION_JITTER_S)
                moments.append(_Moment(at + timedelta(seconds=delay), index, trigger))
            elapsed = ODDS_TICK_S
            while tipoff + timedelta(seconds=elapsed) <= final:
                moments.append(_Moment(tipoff + timedelta(seconds=elapsed), index, "drift"))
                elapsed += ODDS_TICK_S
        # El desempate por operador mantiene estable el orden de emisión.
        moments.sort(key=lambda moment: (moment.at, moment.operator_index))
        return moments

    def run(self) -> list[OddsUpdate]:
        """Recorre el partido y devuelve el flujo de cuotas."""
        tracker = BasketballStateTracker(*self._teams)
        applied = 0
        for moment in self._moments():
            # Cada casa cotiza con lo que ya pasó en la cancha, no con lo que pasará.
            while applied < len(self._events) and self._events[applied].event_time <= moment.at:
                tracker.apply(self._events[applied])
                applied += 1
            operator = self._operators[moment.operator_index]
            for market in BASKETBALL_MARKETS:
                self._evaluate(operator, market, moment, tracker.state())
        return self._updates

    def _probabilities(
        self, operator: Operator, market: BasketballMarket, state: BasketballState
    ) -> dict[str, float]:
        if market == "moneyline":
            return moneyline_probabilities(state, operator.home_strength)
        return total_points_probabilities(state, self._line, operator.home_strength)

    def _evaluate(
        self,
        operator: Operator,
        market: BasketballMarket,
        moment: _Moment,
        state: BasketballState,
    ) -> None:
        book = self._books.get((operator.name, market))
        if book is not None and book.settled:
            return
        probabilities = self._probabilities(operator, market, state)
        if max(probabilities.values()) >= SETTLED_PROBABILITY:
            # Un mercado decidido se cierra: nadie cotiza 1,01 contra 200.
            if book is not None:
                book.settled = True
            return
        odds = probabilities_to_odds(probabilities, operator.overrounds[market])

        if book is None or moment.trigger != "drift":
            self._publish(operator, market, moment, odds, moment.trigger)
        elif _relative_move(book.odds, odds) >= ODDS_MOVE_THRESHOLD:
            self._publish(operator, market, moment, odds, "drift")
        elif (moment.at - book.published_at).total_seconds() >= ODDS_HEARTBEAT_S:
            self._publish(operator, market, moment, odds, "heartbeat")

    def _publish(
        self,
        operator: Operator,
        market: BasketballMarket,
        moment: _Moment,
        odds: dict[str, float],
        trigger: BasketballOddsTrigger,
    ) -> None:
        self._sequence += 1
        self._updates.append(
            OddsUpdate(
                event_id=new_odds_event_id(self._match_id, self._sequence),
                event_time=moment.at,
                match_id=self._match_id,
                operator=operator.name,
                market=market,
                odds=odds,
                trigger=trigger,
                line=self._line if market == "total_points" else None,
            )
        )
        self._books[(operator.name, market)] = _Book(odds, moment.at)


def simulate_basketball_odds(
    seed: int,
    match_events: list[MatchEvent],
    teams: tuple[str, str],
    operators: tuple[Operator, ...] = BASKETBALL_OPERATORS,
) -> list[OddsUpdate]:
    """Deriva el flujo de cuotas de un partido de baloncesto ya simulado.

    Args:
        seed: Semilla. Con el mismo partido y la misma semilla, el mismo flujo.
        match_events: Eventos del partido, en orden cronológico.
        teams: ``(local, visitante)``. El salto inicial no permite deducirlos.
        operators: Casas que cotizan el partido.

    Raises:
        ValueError: Si el partido no trae eventos.
    """
    if not match_events:
        raise ValueError("no hay eventos de partido de los que derivar cuotas")
    return _BasketballOddsSimulator(seed, match_events, teams, operators).run()
