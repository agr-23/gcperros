"""El estado vivo de la repetición, con la forma que publicaría Firestore (#30).

La instantánea es **el documento de Firestore** (``LiveMatchDocument``) más tres
claves: el reloj, la posesión y lo que la marca de agua todavía retiene. Es
deliberado: el front depende de ese contrato, no del motor, y el día que exista
el proyecto de GCP la fuente pasa a ser un listener de Firestore sin que la
página cambie.
"""

from __future__ import annotations

from dataclasses import dataclass

from gcperros.core.contracts import JsonValue
from gcperros.demo.market import MarketView
from gcperros.demo.replay import MatchReplay, ReplayClock
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

    def to_json(self) -> dict[str, JsonValue]:
        """Lo que recibe el front: el documento tal cual, con tres claves más.

        Y una cuarta, ``market``, cuando la demostración lleva cuotas.
        """
        payload = self.document.to_firestore_document()
        payload["clock"] = {
            "elapsed_s": self.clock.elapsed_s,
            "period": self.clock.period,
            "minute": self.clock.minute,
            "phase": self.clock.phase,
        }
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
                "minute": signal.minute,
                "operator": signal.operator,
                "market": signal.market,
                "outcome": signal.outcome,
                "model_probability": signal.model_probability,
                "market_probability": signal.market_probability,
                "divergence": signal.divergence,
            }
            for signal in view.recent_signals
        ],
    }


def take_snapshot(replay: MatchReplay, market: MarketView | None = None) -> LiveSnapshot:
    """Proyecta el estado de la repetición en el instante actual.

    Sólo cuenta lo que el motor **ya aplicó**: lo retenido por la marca de agua
    aparece en ``pending``, a la vista, en lugar de esconderse.
    """
    engine = replay.engine
    state = engine.state
    possession = engine.possession
    return LiveSnapshot(
        document=LiveMatchDocument.project(
            match_id=replay.match_id,
            teams=state.teams,
            summary=state.summary(),
            updated_at=replay.now,
        ),
        clock=replay.clock(),
        running_share=_share(possession.running_seconds),
        window_share=_share(possession.open_window_seconds),
        pending=engine.pending,
        market=market,
    )
