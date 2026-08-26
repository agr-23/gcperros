"""Generador determinista de actualizaciones de cuotas (HU-9).

Las cuotas no se inventan en el vacío: se derivan del estado del partido que
produce el generador de eventos (HU-8). Ese acoplamiento es el punto de la
historia — un feed de cuotas que no reaccionara al marcador no serviría para
probar nada, porque el pipeline nunca vería el patrón de tráfico que enfrentará
en producción.

El patrón de tráfico
--------------------
Durante el juego sin novedad las cuotas se mueven poco y despacio: solo el reloj
corre, y el mercado se limita a acompañarlo. Cuando cae un gol o una expulsión,
las probabilidades saltan de golpe y **todos** los operadores republican **todos**
sus mercados en cuestión de segundos. De ahí nacen las ráfagas.

Se modelan varios operadores porque la arquitectura habla de un *feed de casas*,
en plural, y porque es lo que convierte la ráfaga en ráfaga de verdad: un gol no
produce dos mensajes, produce tantos como operadores por mercados. Además cada
casa valora al local algo distinto y aplica su propio margen, así que sus precios
difieren — que es exactamente la materia prima de la señal de discrepancia
(HU-19).

Los nombres de los operadores son ficticios a propósito. Usar marcas reales
sugeriría que el proyecto consume datos de casas de apuestas reales, y todo el
dato aquí es sintético.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from gcperros.core.contracts import (
    Market,
    MatchEvent,
    OddsTrigger,
    OddsUpdate,
    new_odds_event_id,
)
from gcperros.core.odds import (
    MatchState,
    match_result_probabilities,
    overround,
    probabilities_to_odds,
    total_goals_probabilities,
)

#: Orden fijo de recorrido de los mercados. Es parte de lo que hace reproducible
#: la serialización: recorrer un conjunto no ordenado cambiaría el orden de
#: emisión entre ejecuciones.
MARKETS: tuple[Market, ...] = ("1x2", "over_under_2_5")

#: Cada cuánto reevalúa el mercado un operador cuando no pasa nada.
ODDS_TICK_S = 45.0

#: Movimiento relativo mínimo para republicar por iniciativa propia. Por debajo
#: de este umbral el precio se considera el mismo y no se gasta un mensaje.
ODDS_MOVE_THRESHOLD = 0.05

#: Silencio máximo tolerado. Un mercado que lleva mucho sin publicar parece
#: caído, así que se refresca aunque el precio no se haya movido.
ODDS_HEARTBEAT_S = 300.0

#: Dispersión de la reacción de cada operador, en segundos. Sin ella todas las
#: casas publicarían en el mismo instante exacto, que es justo lo que no pasa.
REACTION_JITTER_S = (0.5, 4.0)

#: Eventos del partido que mueven el mercado. El resto —pases, faltas sin
#: tarjeta, cambios de posesión— no altera la probabilidad de resultado lo
#: suficiente como para justificar un reprecio.
SIGNIFICANT_EVENTS = frozenset({"goal", "red_card"})

#: Probabilidad a partir de la cual un mercado se da por resuelto y el operador
#: deja de cotizarlo. Sin este corte el generador seguiría publicando precios
#: pegados a los topes (1,01 contra 200), que ninguna casa ofrece: en un mercado
#: decidido no hay margen que cobrar, así que se cierra.
SETTLED_PROBABILITY = 0.995

#: Identificador del segundo tiempo dentro de ``attrs``, tal como lo emite el
#: generador de partidos. Se replica aquí en vez de importarlo del otro módulo
#: para no acoplar el consumidor del flujo a la implementación del productor:
#: es un valor del contrato, no de la simulación.
SECOND_HALF_PERIOD = 2


@dataclass(frozen=True, slots=True)
class Operator:
    """Una casa de apuestas sintética.

    Attributes:
        name: Identificador ficticio del operador.
        overrounds: Margen aplicado por mercado. Las casas no cobran lo mismo.
        reaction_delay_s: Cuánto tarda en reprecio tras un evento relevante.
        home_strength: Cómo valora al local frente al modelo base. Es la fuente
            de la discrepancia entre operadores.
    """

    name: str
    overrounds: dict[Market, float]
    reaction_delay_s: float
    home_strength: float


OPERATORS: tuple[Operator, ...] = (
    Operator("OP-A", {"1x2": 1.055, "over_under_2_5": 1.040}, 3.0, 1.00),
    Operator("OP-B", {"1x2": 1.072, "over_under_2_5": 1.055}, 6.5, 1.04),
    Operator("OP-C", {"1x2": 1.061, "over_under_2_5": 1.047}, 11.0, 0.97),
)


@dataclass(frozen=True, slots=True)
class OddsSummary:
    """Agregados del flujo de cuotas, calculados sobre lo ya emitido."""

    update_count: int
    by_trigger: dict[str, int]
    by_operator: dict[str, int]
    mean_overround: dict[str, float]


@dataclass(slots=True)
class _Moment:
    """Un instante en el que un operador va a revisar sus mercados."""

    at: datetime
    operator_index: int
    trigger: OddsTrigger


@dataclass(slots=True)
class _Clock:
    """Traduce tiempo de pared a minuto de partido.

    El reloj de pared incluye el descanso, así que no se puede dividir entre
    sesenta y quedarse tranquilo: entre el minuto 45 y el 46 pasan quince
    minutos en los que el partido no avanza.
    """

    first_half_start: datetime
    second_half_start: datetime | None

    def minute(self, moment: datetime) -> float:
        """Minuto de partido correspondiente a un instante de reloj de pared."""
        if self.second_half_start is not None and moment >= self.second_half_start:
            return 45.0 + (moment - self.second_half_start).total_seconds() / 60.0
        return (moment - self.first_half_start).total_seconds() / 60.0


@dataclass(slots=True)
class _ScoreLine:
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
class _Book:
    """Último precio publicado por un operador en un mercado."""

    odds: dict[str, float] = field(default_factory=dict)
    published_at: datetime | None = None
    settled: bool = False


def _kickoff_teams(events: list[MatchEvent]) -> tuple[str, str]:
    """Identifica local y visitante leyendo el saque inicial del primer tiempo.

    Se derivan del propio flujo y no de la configuración del partido porque el
    generador de cuotas es, conceptualmente, un consumidor del topic: en
    producción recibirá eventos por el broker sin acceso a la configuración con
    la que se simuló el encuentro.
    """
    for event in events:
        if event.event_type == "possession_change" and event.attrs.get("reason") == "kickoff":
            home = event.attrs.get("to_team")
            away = event.attrs.get("from_team")
            if isinstance(home, str) and isinstance(away, str):
                return home, away
    raise ValueError("el flujo no contiene un saque inicial del que deducir los equipos")


def _build_clock(events: list[MatchEvent]) -> _Clock:
    second_half = next(
        (event.event_time for event in events if event.attrs.get("period") == SECOND_HALF_PERIOD),
        None,
    )
    return _Clock(first_half_start=events[0].event_time, second_half_start=second_half)


def _relative_move(previous: dict[str, float], current: dict[str, float]) -> float:
    """Mayor variación relativa entre dos cotizaciones del mismo mercado."""
    return max(abs(current[outcome] - previous[outcome]) / previous[outcome] for outcome in current)


class _OddsSimulator:
    """Máquina de estados del mercado. La API pública es `simulate_odds`."""

    def __init__(
        self, seed: int, events: list[MatchEvent], operators: tuple[Operator, ...]
    ) -> None:
        self._rng = random.Random(seed)
        self._events = events
        self._operators = operators
        self._match_id = events[0].match_id
        self._clock = _build_clock(events)
        self._sequence = 0
        self._updates: list[OddsUpdate] = []
        self._books: dict[tuple[str, Market], _Book] = {
            (operator.name, market): _Book() for operator in operators for market in MARKETS
        }

    # -- planificación --------------------------------------------------------

    def _significant(self) -> list[MatchEvent]:
        return [event for event in self._events if event.event_type in SIGNIFICANT_EVENTS]

    def _moments(self) -> list[_Moment]:
        """Instantes en los que algún operador revisará sus mercados."""
        kickoff = self._events[0].event_time
        final_whistle = self._events[-1].event_time
        moments: list[_Moment] = []

        for index, operator in enumerate(self._operators):
            moments.append(_Moment(kickoff, index, "open"))

            for event in self._significant():
                jitter = self._rng.uniform(*REACTION_JITTER_S)
                delay = timedelta(seconds=operator.reaction_delay_s + jitter)
                trigger: OddsTrigger = "goal" if event.event_type == "goal" else "red_card"
                moments.append(_Moment(event.event_time + delay, index, trigger))

            elapsed = ODDS_TICK_S
            while kickoff + timedelta(seconds=elapsed) <= final_whistle:
                moments.append(_Moment(kickoff + timedelta(seconds=elapsed), index, "drift"))
                elapsed += ODDS_TICK_S

        # El desempate por índice de operador mantiene el orden estable cuando
        # dos casas coinciden en el mismo instante.
        moments.sort(key=lambda moment: (moment.at, moment.operator_index))
        return moments

    # -- emisión --------------------------------------------------------------

    def _publish(
        self,
        operator: Operator,
        market: Market,
        moment: datetime,
        odds: dict[str, float],
        trigger: OddsTrigger,
    ) -> None:
        self._sequence += 1
        self._updates.append(
            OddsUpdate(
                event_id=new_odds_event_id(self._match_id, self._sequence),
                event_time=moment,
                match_id=self._match_id,
                operator=operator.name,
                market=market,
                odds=odds,
                trigger=trigger,
            )
        )
        book = self._books[(operator.name, market)]
        book.odds = odds
        book.published_at = moment

    def _quote(
        self, operator: Operator, market: Market, state: MatchState
    ) -> tuple[dict[str, float], dict[str, float]]:
        probabilities = (
            match_result_probabilities(state, operator.home_strength)
            if market == "1x2"
            else total_goals_probabilities(state, operator.home_strength)
        )
        return probabilities, probabilities_to_odds(probabilities, operator.overrounds[market])

    def run(self) -> list[OddsUpdate]:
        """Recorre el partido y devuelve el flujo de cuotas."""
        significant = self._significant()
        home_team, away_team = _kickoff_teams(self._events)
        score = _ScoreLine(home_team=home_team, away_team=away_team)
        applied = 0

        for moment in self._moments():
            # El operador cotiza con lo que ya ocurrió en el campo, no con lo
            # que ocurrirá: se incorporan solo los eventos anteriores al momento.
            while applied < len(significant) and significant[applied].event_time <= moment.at:
                score.apply(significant[applied])
                applied += 1

            operator = self._operators[moment.operator_index]
            state = score.state(self._clock.minute(moment.at))

            for market in MARKETS:
                self._evaluate(operator, market, moment, state)

        return self._updates

    def _evaluate(
        self, operator: Operator, market: Market, moment: _Moment, state: MatchState
    ) -> None:
        book = self._books[(operator.name, market)]
        if book.settled:
            return

        probabilities, odds = self._quote(operator, market, state)

        if max(probabilities.values()) >= SETTLED_PROBABILITY:
            book.settled = True
            return

        # Apertura y reacción a un evento relevante se publican siempre: es la
        # ráfaga que la historia pide reproducir.
        if moment.trigger != "drift" or book.published_at is None:
            self._publish(operator, market, moment.at, odds, moment.trigger)
            return

        if _relative_move(book.odds, odds) >= ODDS_MOVE_THRESHOLD:
            self._publish(operator, market, moment.at, odds, "drift")
            return

        silent_for = (moment.at - book.published_at).total_seconds()
        if silent_for >= ODDS_HEARTBEAT_S:
            self._publish(operator, market, moment.at, odds, "heartbeat")


def simulate_odds(
    seed: int,
    match_events: list[MatchEvent],
    operators: tuple[Operator, ...] = OPERATORS,
) -> list[OddsUpdate]:
    """Deriva el flujo de cuotas a partir de un partido ya simulado.

    Args:
        seed: Semilla del generador. Con el mismo partido y la misma semilla, el
            flujo de cuotas es idéntico evento por evento.
        match_events: Eventos del partido, en orden cronológico.
        operators: Casas que cotizan el encuentro.

    Returns:
        Las actualizaciones de cuotas en orden cronológico no decreciente.

    Raises:
        ValueError: Si el partido no trae eventos de los que derivar el mercado.
    """
    if not match_events:
        raise ValueError("no hay eventos de partido de los que derivar cuotas")
    return _OddsSimulator(seed, match_events, operators).run()


def summarize_odds(updates: list[OddsUpdate]) -> OddsSummary:
    """Agrega un flujo de cuotas ya emitido."""
    by_trigger: dict[str, int] = {}
    by_operator: dict[str, int] = {}
    books: dict[str, list[float]] = {market: [] for market in MARKETS}

    for update in updates:
        by_trigger[update.trigger] = by_trigger.get(update.trigger, 0) + 1
        by_operator[update.operator] = by_operator.get(update.operator, 0) + 1
        books[update.market].append(overround(update.odds))

    return OddsSummary(
        update_count=len(updates),
        by_trigger=by_trigger,
        by_operator=by_operator,
        mean_overround={
            market: round(sum(values) / len(values), 4) if values else 0.0
            for market, values in books.items()
        },
    )
