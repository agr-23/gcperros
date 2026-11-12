"""El resumen batch de un partido de fútbol americano: la referencia del harness.

Recorre el flujo entero, limpio, de una vez, como ``core/stats.py`` en fútbol y
``core/basketball_stats.py`` en baloncesto. El estado vivo del motor tiene que
proyectarse exactamente a esto.
"""

from __future__ import annotations

from dataclasses import dataclass

from gcperros.core import gridiron
from gcperros.core.contracts import MatchEvent
from gcperros.core.kicking import conversion_value
from gcperros.core.stats import as_float

#: Los contadores enteros del resumen, por equipo, en el orden en que se informan.
COUNTERS: tuple[str, ...] = (
    "points",
    "touchdowns",
    "field_goals_attempted",
    "field_goals_made",
    "plays",
    "yards",
    "turnovers",
    "punts",
    "timeouts",
    "possessions",
)


@dataclass(frozen=True, slots=True)
class AmericanFootballSummary:
    """Lo que un partido de fútbol americano dice de cada equipo."""

    event_count: int
    points: dict[str, int]
    kick_expected_points: dict[str, float]
    touchdowns: dict[str, int]
    field_goals_attempted: dict[str, int]
    field_goals_made: dict[str, int]
    plays: dict[str, int]
    yards: dict[str, int]
    turnovers: dict[str, int]
    punts: dict[str, int]
    timeouts: dict[str, int]
    possessions: dict[str, int]


#: Lo que suman los eventos que siempre suman lo mismo.
_FIXED: dict[str, dict[str, int]] = {
    "touchdown": {"points": gridiron.TOUCHDOWN, "touchdowns": 1},
    "safety": {"points": gridiron.SAFETY},
    "turnover": {"turnovers": 1},
    "punt": {"punts": 1},
    "timeout": {"timeouts": 1},
    "possession_change": {"possessions": 1},
}


def scoring(event: MatchEvent) -> dict[str, int]:
    """Cuánto suma un evento a cada contador de su equipo (también los puntos)."""
    attrs = event.attrs
    made = attrs.get("made") is True
    if event.event_type == "play":
        return {"plays": 1, "yards": int(as_float(attrs["yards"]))}
    if event.event_type == "conversion":
        return {"points": conversion_value(str(attrs["kind"])) if made else 0}
    if event.event_type == "field_goal":
        made_points = gridiron.FIELD_GOAL if made else 0
        return {"points": made_points, "field_goals_attempted": 1, "field_goals_made": int(made)}
    return dict(_FIXED.get(event.event_type, {}))


def kick_value(event: MatchEvent) -> float:
    """Los puntos esperados de una patada o conversión: valor por probabilidad."""
    if event.event_type == "field_goal":
        return gridiron.FIELD_GOAL * as_float(event.attrs["make_probability"])
    if event.event_type == "conversion":
        kind = str(event.attrs["kind"])
        return conversion_value(kind) * as_float(event.attrs["make_probability"])
    return 0.0


def summarize_american_football(events: list[MatchEvent]) -> AmericanFootballSummary:
    """Recorre el flujo completo y resume cada equipo."""
    counters: dict[str, dict[str, int]] = {name: {} for name in COUNTERS}
    expected: dict[str, float] = {}
    for event in events:
        for name in COUNTERS:
            counters[name].setdefault(event.team, 0)
        expected.setdefault(event.team, 0.0)
        for name, amount in scoring(event).items():
            counters[name][event.team] += amount
        expected[event.team] += kick_value(event)
    return AmericanFootballSummary(
        event_count=len(events),
        kick_expected_points={team: round(value, 4) for team, value in expected.items()},
        **counters,
    )
