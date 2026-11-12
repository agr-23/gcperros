"""El estado vivo de la repetición, con la forma que publicaría Firestore (#30).

La instantánea es **el documento de Firestore** (``LiveMatchDocument``) más
cuatro claves: el reloj, la posesión, lo que la marca de agua todavía retiene y
el deporte, que dice a la página cómo leer el documento (#92). Es deliberado:
el front depende de ese contrato, no del motor, y el día que exista el proyecto
de GCP la fuente pasa a ser un listener de Firestore sin que la página cambie.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from gcperros.core.american_football_stats import scoring
from gcperros.core.basketball_matchstate import points_scored
from gcperros.core.contracts import JsonValue, MatchEvent
from gcperros.demo.market import MarketView
from gcperros.demo.replay import Replay, ReplayClock
from gcperros.firestore.document import LiveMatchDocument


def _share(seconds: dict[str, float]) -> dict[str, float]:
    total = sum(seconds.values())
    if total <= 0.0:
        return {}
    return {team: round(value / total, 4) for team, value in seconds.items()}


@dataclass(frozen=True, slots=True)
class LiveSnapshot:
    """El estado vivo en un instante: el documento de Firestore más reloj y posesión."""

    document: LiveMatchDocument
    clock: ReplayClock
    running_share: dict[str, float]
    window_share: dict[str, float]
    pending: int
    market: MarketView | None = None
    #: El deporte, para que la página sepa cómo leer el documento (#92).
    sport: str = "football"
    #: Puntos de cada equipo por cuarto, en baloncesto.
    periods: dict[str, list[int]] | None = None

    def to_json(self) -> dict[str, JsonValue]:
        """Lo que recibe el front: el documento tal cual, con cuatro claves más.

        Y ``market`` cuando la demostración lleva cuotas, y ``periods`` —los
        puntos por cuarto— en baloncesto.
        """
        payload = self.document.to_firestore_document()
        clock: dict[str, JsonValue] = {
            "elapsed_s": self.clock.elapsed_s,
            "period": self.clock.period,
            "minute": self.clock.minute,
            "phase": self.clock.phase,
        }
        if self.clock.game_clock_s is not None:
            clock["game_clock_s"] = self.clock.game_clock_s
        payload["clock"] = clock
        payload["sport"] = self.sport
        if self.periods is not None:
            payload["periods"] = {team: list(points) for team, points in self.periods.items()}
        payload["possession"] = {
            "running_share": dict(self.running_share),
            "window_share": dict(self.window_share),
        }
        payload["pending"] = self.pending
        if self.market is not None:
            payload["market"] = _market_json(self.market)
        return payload


def _market_json(view: MarketView) -> dict[str, JsonValue]:
    return {
        "model": dict(view.model),
        "operators": {operator: dict(book) for operator, book in view.operators.items()},
        "total_signals": view.total_signals,
        "signals": [
            {
                # Posición en la cinta, para pedir su procedencia (historia #25).
                "index": view.total_signals - 1 - position,
                "minute": signal.minute,
                "operator": signal.operator,
                "market": signal.market,
                "outcome": signal.outcome,
                "model_probability": signal.model_probability,
                "market_probability": signal.market_probability,
                "divergence": signal.divergence,
            }
            for position, signal in enumerate(view.recent_signals)
        ],
    }


#: Lo que suma cada evento al marcador, en los deportes de cuartos.
_POINTS: dict[str, Callable[[MatchEvent], int]] = {
    "basketball": points_scored,
    "american_football": lambda event: scoring(event).get("points", 0),
}


def _points_by_period(replay: Replay[object]) -> dict[str, list[int]]:
    """Puntos por cuarto de lo que el motor ya aplicó.

    La repetición entrega en orden y la marca de agua suelta en orden, así que
    lo que sigue retenido son los últimos entregados: el resto ya está aplicado.
    """
    delivered = replay.delivered
    applied = delivered[: len(delivered) - replay.engine.pending]
    teams = replay.engine.state.teams
    last = max((_period_of(e.attrs.get("period")) for e in applied), default=1)
    periods = {team: [0] * last for team in teams}
    for event in applied:
        scored = _POINTS[replay.sport](event)
        if scored and event.team in periods:
            periods[event.team][_period_of(event.attrs.get("period")) - 1] += scored
    return periods


def _period_of(value: JsonValue) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 1


def take_snapshot(replay: Replay[object], market: MarketView | None = None) -> LiveSnapshot:
    """Proyecta el estado de la repetición en el instante actual.

    Sólo cuenta lo que el motor **ya aplicó**: lo retenido por la marca de agua
    aparece en ``pending``, a la vista, en lugar de esconderse.
    """
    engine = replay.engine
    state = engine.state
    possession = engine.possession
    return LiveSnapshot(
        document=LiveMatchDocument.project_state(
            replay.match_id, state, replay.now, teams=replay.teams
        ),
        clock=replay.clock(),
        running_share=_share(possession.running_seconds),
        window_share=_share(possession.open_window_seconds),
        pending=engine.pending,
        market=market,
        sport=replay.sport,
        periods=_points_by_period(replay) if replay.sport in _POINTS else None,
    )
