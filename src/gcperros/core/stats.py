"""Agregados del partido, compartidos por el plano batch y el motor.

``summarize_events`` es el **plano batch de referencia**: recorre el flujo
completo, sin estado previo y sin sorpresas, y produce los indicadores del
partido. El motor de streaming (``gcperros.engine``) calcula esos mismos
indicadores incrementalmente, evento a evento, bajo duplicación y desorden.

Que ambos produzcan exactamente la misma estructura no es comodidad: es lo que
convierte la validación streaming-contra-batch del OE-2 en una comparación
directa en vez de una traducción entre formatos.
"""

from __future__ import annotations

from dataclasses import dataclass

from gcperros.core.contracts import JsonValue, MatchEvent


@dataclass(frozen=True, slots=True)
class MatchSummary:
    """Indicadores de un partido, derivados del flujo de eventos."""

    event_count: int
    goals: dict[str, int]
    shots: dict[str, int]
    total_xg: dict[str, float]
    passes: dict[str, int]
    completed_passes: dict[str, int]
    fouls: dict[str, int]
    red_cards: dict[str, int]
    possessions: dict[str, int]


def as_float(value: JsonValue) -> float:
    """Lee un número de ``attrs`` rechazando lo que no lo sea.

    Un agregador que sumara silenciosamente lo que le llega convertiría un
    evento mal formado en un indicador plausible pero incorrecto, que es
    exactamente el fallo que la capa de gobernanza busca evitar.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"se esperaba un número y llegó {type(value).__name__}")
    return float(value)


def teams_in_order(events: list[MatchEvent]) -> list[str]:
    """Equipos presentes en el flujo, en orden de primera aparición.

    Deliberadamente **no** se usa un conjunto. El orden de iteración de un
    conjunto de cadenas depende de ``PYTHONHASHSEED`` y cambia entre procesos,
    de modo que los diccionarios del resumen saldrían con las claves en distinto
    orden en cada ejecución. Con ``==`` daría igual, pero en cuanto el resumen se
    serialice —el documento vivo de Firestore, un informe de calidad— la salida
    dejaría de ser idéntica byte a byte, que es la promesa del proyecto.
    """
    ordered: dict[str, None] = {}
    for event in events:
        ordered.setdefault(event.team, None)
    return list(ordered)


def summarize_events(events: list[MatchEvent]) -> MatchSummary:
    """Calcula los indicadores del partido recorriendo el flujo completo.

    Es el plano batch de referencia: opera sobre el registro histórico ya
    cerrado, sin preocuparse de duplicados ni de desorden, porque los ve todos
    a la vez. El motor de streaming tiene que llegar al mismo resultado sin ese
    lujo.
    """
    teams = teams_in_order(events)
    goals = dict.fromkeys(teams, 0)
    shots = dict.fromkeys(teams, 0)
    passes = dict.fromkeys(teams, 0)
    completed_passes = dict.fromkeys(teams, 0)
    fouls = dict.fromkeys(teams, 0)
    red_cards = dict.fromkeys(teams, 0)
    possessions = dict.fromkeys(teams, 0)
    total_xg = dict.fromkeys(teams, 0.0)

    for event in events:
        match event.event_type:
            case "goal":
                goals[event.team] += 1
            case "shot":
                shots[event.team] += 1
                total_xg[event.team] += as_float(event.attrs["xg"])
            case "pass":
                passes[event.team] += 1
                if event.attrs["completed"]:
                    completed_passes[event.team] += 1
            case "foul":
                fouls[event.team] += 1
            case "red_card":
                red_cards[event.team] += 1
            case "possession_change":
                possessions[event.team] += 1

    return MatchSummary(
        event_count=len(events),
        goals=goals,
        shots=shots,
        total_xg={team: round(value, 4) for team, value in total_xg.items()},
        passes=passes,
        completed_passes=completed_passes,
        fouls=fouls,
        red_cards=red_cards,
        possessions=possessions,
    )
