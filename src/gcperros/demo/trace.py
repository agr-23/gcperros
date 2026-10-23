"""De dónde sale un número del marcador, con prueba (#34).

El estado vivo no guarda la lista de eventos de cada indicador: guarda una
huella conmutativa de sus identificadores (HU-18). Eso permite algo mejor que
enseñar una lista: **reconstruirla y demostrar que es la buena**.

Para reconstruirla no se copian las reglas del motor —qué evento cuenta para qué
indicador—, que divergirían a la primera: cada evento entregado se aplica a un
estado vacío y se mira si tocó el indicador. Como la marca de agua aplica en
orden de tiempo, los que el motor ya aplicó son los primeros de esa lista. Al
final se pliega su huella y se compara con la del motor: si coinciden, la lista
es exactamente la que formó el número.
"""

from __future__ import annotations

from dataclasses import dataclass

from gcperros.core.contracts import JsonValue, MatchEvent
from gcperros.core.lineage import LineageAccumulator
from gcperros.demo.replay import MatchReplay
from gcperros.engine.state import LiveMatchState
from gcperros.governance.traceability import Explanation, explain


@dataclass(frozen=True, slots=True)
class TracedEvent:
    """Un evento que contribuyó al número, con lo que hace falta para leerlo."""

    event_id: str
    minute: int
    event_type: str
    team: str


@dataclass(frozen=True, slots=True)
class Trace:
    """Un indicador, los eventos que lo formaron y si su huella cuadra."""

    explanation: Explanation
    events: tuple[TracedEvent, ...]
    verified: bool

    def to_json(self) -> dict[str, JsonValue]:
        """La explicación de la HU-18 tal cual, más los eventos y el veredicto."""
        payload = self.explanation.to_dict()
        payload["verified"] = self.verified
        payload["events"] = [
            {
                "event_id": event.event_id,
                "minute": event.minute,
                "event_type": event.event_type,
                "team": event.team,
            }
            for event in self.events
        ]
        return payload


def _contributes(event: MatchEvent, indicator: str, scope: str) -> bool:
    scratch = LiveMatchState()
    scratch.apply(event)
    return scratch.lineage(indicator, scope).event_count > 0


def trace_indicator(replay: MatchReplay, indicator: str, scope: str) -> Trace:
    """Reconstruye los eventos de un indicador y verifica su huella contra el motor.

    Raises:
        KeyError: Si el indicador no se mide en ese alcance.
        AttributeError: Si el indicador no existe.
    """
    explanation = explain(replay.engine.state, indicator, scope)
    applied = [e for e in replay.delivered if _contributes(e, indicator, scope)][
        : explanation.lineage.event_count
    ]

    fold = LineageAccumulator()
    for event in applied:
        fold.add(event.event_id)

    return Trace(
        explanation=explanation,
        events=tuple(
            TracedEvent(e.event_id, replay.minute_at(e.event_time), e.event_type, e.team)
            for e in applied
        ),
        verified=fold.digest == explanation.lineage.digest
        and fold.count == explanation.lineage.event_count,
    )
