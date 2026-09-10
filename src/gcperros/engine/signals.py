"""Señal de discrepancia entre el modelo y el mercado (HU-19).

Compara lo que el modelo propio cree, alimentado por el estado completo del
partido, con lo que la cuota vigente da por probable. Cuando se separan más de
un umbral declarado, se emite una señal con **ambas cifras y el instante**, para
que quien la reciba pueda juzgarla en lugar de creérsela.

Descontar el margen no es opcional
----------------------------------
La probabilidad implícita en una cuota **no** es uno partido por la cuota. Ese
atajo devuelve la probabilidad inflada por el margen del operador: con un
overround de 1,06 sobreestima cada resultado un 6 %, y como el sesgo va siempre
en el mismo sentido, el detector encontraría discrepancias en todas partes y
ninguna sería real. ``core.odds.implied_probabilities`` normaliza para quitarlo,
y es la única puerta por la que este módulo mira el precio.

El mismo estado en los dos lados
--------------------------------
El modelo y el mercado se comparan sobre el estado que da ``core.matchstate``.
Si cada uno partiera de su propia lectura del partido, una discrepancia podría
venir de que uno va un minuto por detrás del otro, y la señal dejaría de
significar lo que promete.

Se evalúa el precio vigente, no sólo el recién publicado
------------------------------------------------------
Un operador tarda unos segundos en repreciar tras un gol. Durante esos segundos
su precio **sigue publicado y ya no vale**, y ése es justamente el momento que
la historia quiere capturar. Por eso el detector guarda el último precio de cada
operador y lo vuelve a contrastar cuando el partido se mueve, en lugar de
esperar a que llegue una cuota nueva: cuando llega, el operador ya se enteró y
no hay nada que señalar.

Qué mide esta señal, y qué no
-----------------------------
El modelo de referencia es deliberadamente parsimonioso y comparte su forma con
el que usan los operadores sintéticos, así que esta señal **no** dice «el
mercado se equivoca». Dice algo más modesto y medible.

Midiendo sobre ocho partidos, al umbral declarado la señal está dominada por el
**precio rancio**: el 57 % de las señales cae en los 45 s siguientes a un gol o
una expulsión. El sesgo del operador existe y se mide —la discrepancia media es
de 0,0061 para el operador que valora al local como el modelo, y de 0,0093 y
0,0095 para los que no— pero se queda por debajo del umbral y casi nunca cruza
por sí solo.

Conviene decirlo así de claro: al umbral de 0,05 esto detecta precios que se
quedaron viejos, no casas que valoran distinto. Con un modelo propio de verdad
la maquinaria sería la misma; cambia lo que se le pone dentro.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from gcperros.core.contracts import Market, MatchEvent, OddsUpdate
from gcperros.core.matchstate import MatchStateTracker
from gcperros.core.odds import (
    MatchState,
    implied_probabilities,
    match_result_probabilities,
    total_goals_probabilities,
)

#: Eventos que mueven la probabilidad lo bastante como para dejar rancio un
#: precio publicado. Un pase no cambia el pronóstico; un gol sí.
MARKET_MOVING_EVENTS = frozenset({"goal", "red_card"})

#: Separación mínima, en puntos de probabilidad, para que la señal se emita.
#: Elegido a partir del reparto de discrepancias observado; ver
#: ``docs/decisiones-de-diseno.md``.
DEFAULT_THRESHOLD = 0.05


@dataclass(frozen=True, slots=True)
class DiscrepancySignal:
    """Un momento en el que el modelo y el mercado no se ponen de acuerdo."""

    detected_at: datetime
    match_id: str
    operator: str
    market: Market
    outcome: str
    model_probability: float
    market_probability: float
    minute: float

    @property
    def divergence(self) -> float:
        """Cuánto se separan, con signo.

        Positivo significa que el modelo ve el resultado **más** probable que el
        mercado; negativo, al revés.
        """
        return round(self.model_probability - self.market_probability, 4)

    @property
    def magnitude(self) -> float:
        """Separación en valor absoluto."""
        return abs(self.divergence)

    def describe(self) -> str:
        """Una línea legible, para el registro y la línea de comandos."""
        sentido = "modelo por encima" if self.divergence > 0 else "mercado por encima"
        return (
            f"min {self.minute:5.1f}  {self.operator}  {self.market}/{self.outcome}  "
            f"modelo {self.model_probability:.3f} vs mercado {self.market_probability:.3f}  "
            f"({self.divergence:+.3f}, {sentido})"
        )


def model_probabilities(market: Market, state: MatchState) -> dict[str, float]:
    """Lo que el modelo propio cree para cada resultado de un mercado."""
    if market == "1x2":
        return match_result_probabilities(state)
    return total_goals_probabilities(state)


class DiscrepancyDetector:
    """Contrasta cada actualización de cuotas contra el modelo propio.

    Consume los dos flujos: los eventos del partido mantienen el estado, y cada
    actualización de cuotas se evalúa contra él en el momento en que llega.
    """

    __slots__ = ("_books", "_threshold", "_tracker")

    def __init__(self, threshold: float = DEFAULT_THRESHOLD) -> None:
        """Crea un detector con el umbral indicado.

        Args:
            threshold: Separación mínima, en puntos de probabilidad, para emitir.

        Raises:
            ValueError: Si el umbral no cae en ``(0, 1)``. Un umbral de cero
                emitiría en cada redondeo, y uno de uno no emitiría nunca.
        """
        if not 0.0 < threshold < 1.0:
            raise ValueError("el umbral debe estar entre 0 y 1, sin incluirlos")

        self._threshold = threshold
        self._tracker = MatchStateTracker()
        # Último precio vigente de cada operador en cada mercado. Es lo que
        # queda expuesto mientras el operador no reacciona.
        self._books: dict[tuple[str, Market], OddsUpdate] = {}

    @property
    def threshold(self) -> float:
        """Umbral declarado del detector."""
        return self._threshold

    @property
    def state(self) -> MatchState:
        """Estado del partido con el que se está evaluando ahora mismo."""
        return self._tracker.state()

    def apply_match_event(self, event: MatchEvent) -> list[DiscrepancySignal]:
        """Actualiza el estado y revisa los precios que quedaron desfasados.

        Args:
            event: Evento del partido, ya deduplicado y en orden.

        Returns:
            Las señales que provoca el evento. Sólo un gol o una expulsión
            mueven la probabilidad lo bastante como para dejar rancio un precio;
            revisar en cada pase sería ruido y coste sin información.
        """
        self._tracker.apply(event)

        if event.event_type not in MARKET_MOVING_EVENTS:
            return []

        signals: list[DiscrepancySignal] = []
        for update in self._books.values():
            signals.extend(self._compare(update, at=event.event_time))
        return signals

    def evaluate(self, update: OddsUpdate) -> list[DiscrepancySignal]:
        """Contrasta una actualización de cuotas contra el modelo.

        Args:
            update: Cuotas publicadas por un operador para un mercado.

        Returns:
            Una señal por cada resultado que se separe más del umbral. La lista
            vacía es el caso normal: que el mercado y el modelo coincidan no es
            noticia.
        """
        self._books[(update.operator, update.market)] = update
        return self._compare(update, at=update.event_time)

    def _compare(self, update: OddsUpdate, at: datetime) -> list[DiscrepancySignal]:
        """Contrasta un precio contra el modelo en el instante indicado."""
        state = self._tracker.state()
        model = model_probabilities(update.market, state)
        # Aquí está la mitad del trabajo de la historia: el precio se convierte
        # en probabilidad descontando el margen, no dividiendo uno entre la cuota.
        market = implied_probabilities(update.odds)

        signals = []
        for outcome, believed in model.items():
            priced = market.get(outcome)
            if priced is None or abs(believed - priced) < self._threshold:
                continue

            signals.append(
                DiscrepancySignal(
                    detected_at=at,
                    match_id=update.match_id,
                    operator=update.operator,
                    market=update.market,
                    outcome=outcome,
                    model_probability=round(believed, 4),
                    market_probability=round(priced, 4),
                    minute=round(self._tracker.minute, 1),
                )
            )
        return signals


def detect_discrepancies(
    match_events: list[MatchEvent],
    odds_updates: list[OddsUpdate],
    threshold: float = DEFAULT_THRESHOLD,
) -> list[DiscrepancySignal]:
    """Recorre los dos flujos entrelazados por tiempo y devuelve las señales.

    Es la referencia batch de la HU-19: ve los dos flujos completos y los mezcla
    por ``event_time``, que es el orden en el que habrían llegado. Un consumidor
    en vivo usa ``DiscrepancyDetector`` directamente.

    Args:
        match_events: Eventos del partido, en orden cronológico.
        odds_updates: Actualizaciones de cuotas, en orden cronológico.
        threshold: Separación mínima para emitir.

    Returns:
        Las señales, en orden cronológico.
    """
    detector = DiscrepancyDetector(threshold=threshold)
    signals: list[DiscrepancySignal] = []

    # Se intercalan por tiempo de evento: una cuota tiene que evaluarse contra el
    # partido tal como estaba cuando se publicó, no contra el partido entero.
    pending = iter(match_events)
    current = next(pending, None)

    for update in odds_updates:
        while current is not None and current.event_time <= update.event_time:
            signals.extend(detector.apply_match_event(current))
            current = next(pending, None)
        signals.extend(detector.evaluate(update))

    # El partido sigue después de la última cuota publicada, y un gol en ese
    # tramo deja rancio todo lo que quedaba en el mercado.
    while current is not None:
        signals.extend(detector.apply_match_event(current))
        current = next(pending, None)

    return signals
