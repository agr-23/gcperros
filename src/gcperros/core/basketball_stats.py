"""Agregados de un partido de baloncesto: el plano batch de referencia (#88).

Es el equivalente de ``core/stats.py`` para el segundo deporte, y vive en
``core`` por la misma razón: el motor de streaming tendrá que llegar a esta
misma estructura evento a evento (#89), y el motor no puede depender de un
generador.

Los puntos no se cuentan con un evento aparte, como el gol: salen de los tiros
y los tiros libres anotados. Los puntos esperados son el xG del baloncesto: lo
que vale cada tiro por la probabilidad de anotarlo.
"""

from __future__ import annotations

from dataclasses import dataclass

from gcperros.core import court
from gcperros.core.contracts import MatchEvent
from gcperros.core.stats import as_float, teams_in_order


@dataclass(frozen=True, slots=True)
class BasketballSummary:
    """Indicadores de un partido de baloncesto, derivados del flujo de eventos."""

    event_count: int
    points: dict[str, int]
    expected_points: dict[str, float]
    two_attempted: dict[str, int]
    two_made: dict[str, int]
    three_attempted: dict[str, int]
    three_made: dict[str, int]
    free_throws_attempted: dict[str, int]
    free_throws_made: dict[str, int]
    offensive_rebounds: dict[str, int]
    defensive_rebounds: dict[str, int]
    turnovers: dict[str, int]
    fouls: dict[str, int]
    timeouts: dict[str, int]
    possessions: dict[str, int]


def summarize_basketball(events: list[MatchEvent]) -> BasketballSummary:
    """Calcula los indicadores del partido recorriendo el flujo completo."""
    teams = teams_in_order(events)

    def zero() -> dict[str, int]:
        return dict.fromkeys(teams, 0)

    points, two_att, two_made, three_att, three_made = zero(), zero(), zero(), zero(), zero()
    ft_att, ft_made, off_reb, def_reb = zero(), zero(), zero(), zero()
    turnovers, fouls, timeouts, possessions = zero(), zero(), zero(), zero()
    expected = dict.fromkeys(teams, 0.0)

    for event in events:
        team, attrs = event.team, event.attrs
        match event.event_type:
            case "shot":
                value = int(as_float(attrs["points_value"]))
                attempted, made = (
                    (three_att, three_made) if value == court.THREE_POINTS else (two_att, two_made)
                )
                attempted[team] += 1
                expected[team] += value * as_float(attrs["make_probability"])
                if attrs["made"] is True:
                    made[team] += 1
                    points[team] += value
            case "free_throw":
                ft_att[team] += 1
                expected[team] += as_float(attrs["make_probability"])
                if attrs["made"] is True:
                    ft_made[team] += 1
                    points[team] += 1
            case "rebound":
                (off_reb if attrs["kind"] == "offensive" else def_reb)[team] += 1
            case "turnover":
                turnovers[team] += 1
            case "foul":
                fouls[team] += 1
            case "timeout":
                timeouts[team] += 1
            case "possession_change":
                possessions[team] += 1

    return BasketballSummary(
        event_count=len(events),
        points=points,
        expected_points={team: round(value, 4) for team, value in expected.items()},
        two_attempted=two_att,
        two_made=two_made,
        three_attempted=three_att,
        three_made=three_made,
        free_throws_attempted=ft_att,
        free_throws_made=ft_made,
        offensive_rebounds=off_reb,
        defensive_rebounds=def_reb,
        turnovers=turnovers,
        fouls=fouls,
        timeouts=timeouts,
        possessions=possessions,
    )
