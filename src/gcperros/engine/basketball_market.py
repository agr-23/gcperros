"""La señal de discrepancia (HU-19) para el baloncesto (#90).

El detector es el mismo del fútbol: el mismo umbral, el mismo descuento del
margen, la misma vigilancia del precio rancio y el mismo linaje. Lo único que se
le inyecta es cómo se lee el partido y qué cree el modelo.

En fútbol sólo un gol o una roja dejan viejo un precio. En baloncesto **cada
canasta** lo deja viejo: a mitad de partido una de dos mueve la probabilidad de
ganar unos 8 puntos. El detector revisa los precios vigentes tras cada punto.

¿Sigue valiendo el umbral de 0,05?
----------------------------------
Medido sobre 8 partidos, **en significado sí y en volumen no**. Como en fútbol,
todas las señales caen en los segundos que tarda una casa en repreciar tras una
canasta: detecta precios rancios, y el sesgo de cada casa se queda por debajo.
Pero dispara 386 señales por partido frente a las 72 del fútbol, porque las
discrepancias del baloncesto son el doble de anchas (p90 de 0,070 frente a
0,036). Con la misma regla que deja el umbral del fútbol en 1,4 veces su p90, el
del baloncesto sale en **0,10**, con unas 102 señales por partido.
"""

from __future__ import annotations

from gcperros.core import basketball_odds, court
from gcperros.core.basketball_matchstate import BasketballStateTracker, points_scored
from gcperros.core.basketball_odds import moneyline_probabilities, total_points_probabilities
from gcperros.core.contracts import MatchEvent, OddsUpdate
from gcperros.engine.signals import DiscrepancySignal, detect_discrepancies

#: El umbral del baloncesto, elegido con la misma regla que el del fútbol.
BASKETBALL_THRESHOLD = 0.10


class BasketballMarketReader:
    """El baloncesto: periodo, reloj y marcador, con el modelo normal."""

    model_version = basketball_odds.MODEL_VERSION

    def __init__(self, home_team: str, away_team: str) -> None:
        """Crea el lector. Los equipos se declaran: el salto inicial no dice quién es local."""
        self._tracker = BasketballStateTracker(home_team, away_team)

    @property
    def minute(self) -> float:
        """Minutos de juego transcurridos, prórrogas incluidas."""
        state = self._tracker.state()
        if state.period <= court.REGULATION_PERIODS:
            played = (state.period - 1) * court.PERIOD_DURATION_S
            length = court.PERIOD_DURATION_S
        else:
            overtimes = state.period - court.REGULATION_PERIODS - 1
            played = (
                court.REGULATION_PERIODS * court.PERIOD_DURATION_S
                + overtimes * court.OVERTIME_DURATION_S
            )
            length = court.OVERTIME_DURATION_S
        return (played + length - state.clock_s) / 60.0

    def apply(self, event: MatchEvent) -> bool:
        """Cada punto mueve el mercado; un rebote o una falta, no."""
        self._tracker.apply(event)
        return points_scored(event) > 0

    def fixes_state(self, event: MatchEvent) -> bool:
        """Las canastas ponen el marcador, que es lo que el modelo lee."""
        return points_scored(event) > 0

    def probabilities(self, update: OddsUpdate) -> dict[str, float] | None:
        """El ganador, o el total sobre la línea que trae la propia cuota."""
        state = self._tracker.state()
        if update.market == "moneyline":
            return moneyline_probabilities(state)
        if update.market == "total_points" and update.line is not None:
            return total_points_probabilities(state, update.line)
        return None


def detect_basketball_discrepancies(
    match_events: list[MatchEvent],
    odds_updates: list[OddsUpdate],
    teams: tuple[str, str],
    threshold: float = BASKETBALL_THRESHOLD,
) -> list[DiscrepancySignal]:
    """La referencia batch de la señal, para un partido de baloncesto."""
    reader = BasketballMarketReader(*teams)
    return detect_discrepancies(match_events, odds_updates, threshold=threshold, reader=reader)
