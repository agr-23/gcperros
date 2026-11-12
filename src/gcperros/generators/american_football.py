"""Generador determinista de partidos de fútbol americano, el tercer deporte.

El partido es una **secuencia de series ofensivas**: el ataque tiene cuatro
downs para avanzar diez yardas, y cada serie acaba en touchdown, gol de campo,
despeje, pérdida o pérdida de balón en downs. Como en baloncesto hay dos
relojes: el de juego, que viaja en ``clock_s``, y el de pared, que es el
``event_time`` y avanza también con el juego parado.

Lo que más lo distingue de los otros dos es **cómo se para**: entre jugada y
jugada pasan treinta o cuarenta segundos sin un solo evento, y cada anotación
trae un parón largo. Es la prueba más dura para una marca de agua que sólo
avanzaba con las llegadas.

Todo el azar sale de un único ``random.Random(seed)``: la misma semilla da el
mismo partido. La calibración contra la NFL está en
``tests/test_american_football_generator.py`` y en la sección 22.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from gcperros.core import gridiron
from gcperros.core.contracts import AmericanFootballEventType, JsonValue, MatchEvent, new_event_id
from gcperros.core.kicking import (
    conversion_probability,
    conversion_value,
    field_goal_probability,
)

DEFAULT_KICKOFF = datetime(2026, 11, 15, 18, 0, 0, tzinfo=UTC)

QUARTER_BREAK_S = 2 * 60
HALF_TIME_S = 13 * 60
#: Lo que se para el juego tras una anotación: celebración, conversión y anuncios.
SCORE_BREAK_S = (60, 120)
TIMEOUT_BREAK_S = (60, 90)

#: Cuánto reloj de juego consume cada clase de jugada, y cuánta pared añade el
#: corrillo cuando el reloj está parado (pase incompleto).
RUN_CLOCK_S = (28, 40)
INCOMPLETE_CLOCK_S = (4, 8)
HUDDLE_S = (18, 28)

PASS_RATE = 0.57
COMPLETION_RATE = 0.64
SACK_RATE = 0.065
INTERCEPTION_RATE = 0.027
FUMBLE_RATE = 0.012
#: En cuarto y corto en campo rival se arriesga en vez de despejar.
GO_FOR_IT_RATE = 0.55
GO_FOR_IT_FROM = 45
GO_FOR_IT_MAX_TO_GO = 2
BIG_PLAY_RATE = 0.025
TWO_POINT_RATE = 0.08
TIMEOUT_RATE = 0.02
#: Desde dónde se patea a palos: a 37 yardas o menos de la zona de anotación.
FIELD_GOAL_RANGE = gridiron.FIELD_YARDS - 37
TOUCHBACK = 25


@dataclass(frozen=True, slots=True)
class AmericanFootballConfig:
    """El partido que se quiere generar."""

    match_id: str = "nfl-0001"
    home_team: str = "KC"
    away_team: str = "BUF"
    kickoff: datetime = DEFAULT_KICKOFF


class _Game:
    """El estado del generador mientras emite: reloj, marcador y quién ataca."""

    def __init__(self, seed: int, config: AmericanFootballConfig) -> None:
        self.rng = random.Random(seed)
        self.config = config
        self.events: list[MatchEvent] = []
        self.wall = config.kickoff
        self.period = 1
        self.clock = float(gridiron.PERIOD_DURATION_S)
        self.score = {config.home_team: 0, config.away_team: 0}

    def other(self, team: str) -> str:
        return self.config.away_team if team == self.config.home_team else self.config.home_team

    def emit(
        self, event_type: AmericanFootballEventType, team: str, gap_s: float, **attrs: JsonValue
    ) -> None:
        self.wall += timedelta(seconds=gap_s)
        attrs = {"period": self.period, "clock_s": round(max(self.clock, 0.0), 1), **attrs}
        self.events.append(
            MatchEvent(
                event_id=new_event_id(self.config.match_id, len(self.events)),
                event_time=self.wall,
                match_id=self.config.match_id,
                team=team,
                event_type=event_type,
                attrs=attrs,
            )
        )

    def gap(self, bounds: tuple[float, float]) -> float:
        return self.rng.uniform(*bounds)

    def change(self, to_team: str, reason: str, gap_s: float) -> None:
        self.emit(
            "possession_change",
            to_team,
            gap_s,
            from_team=self.other(to_team),
            to_team=to_team,
            reason=reason,
        )


def _yards(game: _Game) -> tuple[str, int, float]:
    """Una jugada: su clase, las yardas que gana y el reloj de juego que consume."""
    rng = game.rng
    if rng.random() < PASS_RATE:
        if rng.random() < SACK_RATE:
            return "sack", -rng.randint(4, 9), game.gap(RUN_CLOCK_S)
        if rng.random() < COMPLETION_RATE:
            gained = max(-2, round(rng.gauss(11.5, 8.0)))
            return "pass_complete", gained, game.gap(RUN_CLOCK_S)
        return "pass_incomplete", 0, game.gap(INCOMPLETE_CLOCK_S)
    return "run", max(-5, round(rng.gauss(4.5, 4.5))), game.gap(RUN_CLOCK_S)


def _fourth_down(game: _Game, offense: str, yardline: int) -> tuple[str, int, str]:
    """Cuarto down sin arriesgar: gol de campo si hay distancia, despeje si no."""
    rng = game.rng
    if yardline >= FIELD_GOAL_RANGE:
        distance = gridiron.FIELD_YARDS - yardline + 17
        probability = field_goal_probability(distance)
        made = rng.random() < probability
        game.clock -= 5
        game.emit(
            "field_goal",
            offense,
            game.gap(RUN_CLOCK_S),
            distance_yd=distance,
            made=made,
            make_probability=probability,
        )
        game.score[offense] += gridiron.FIELD_GOAL if made else 0
        missed_at = max(gridiron.FIELD_YARDS - yardline - 7, 20)
        return game.other(offense), TOUCHBACK if made else missed_at, "field_goal"
    punt = min(max(round(rng.gauss(45, 7)), 25), gridiron.MAX_PLAY_YARDS)
    game.clock -= 8
    game.emit("punt", offense, game.gap(RUN_CLOCK_S), yards=punt)
    landing = yardline + punt
    received = 20 if landing >= gridiron.FIELD_YARDS else gridiron.FIELD_YARDS - landing
    return game.other(offense), received, "punt"


def _touchdown(game: _Game, offense: str) -> None:
    """Seis puntos y la conversión: pateada casi siempre, jugada a veces."""
    rng = game.rng
    game.score[offense] += gridiron.TOUCHDOWN
    game.emit("touchdown", offense, game.gap((1, 3)))
    kind = "two_point" if rng.random() < TWO_POINT_RATE else "kick"
    probability = conversion_probability(kind)
    made = rng.random() < probability
    game.score[offense] += conversion_value(kind) if made else 0
    game.emit(
        "conversion",
        offense,
        game.gap(SCORE_BREAK_S),
        kind=kind,
        made=made,
        make_probability=probability,
    )


def _drive(game: _Game, offense: str, start: int) -> tuple[str, int, str | None]:
    """Juega una serie: quién ataca después, desde qué yarda y por qué.

    El motivo es ``None`` si la serie no acabó, sino el reloj del cuarto: sigue
    en el siguiente con el mismo ataque, sin cambio de posesión.
    """
    rng = game.rng
    yardline, down, to_go = start, 1, 10
    while game.clock > 0:
        go_for_it = to_go <= GO_FOR_IT_MAX_TO_GO and GO_FOR_IT_FROM <= yardline < FIELD_GOAL_RANGE
        if down == gridiron.DOWNS and not (go_for_it and rng.random() < GO_FOR_IT_RATE):
            return _fourth_down(game, offense, yardline)

        kind, gained, used = _yards(game)
        if rng.random() < BIG_PLAY_RATE and gained > 0:
            gained += rng.randint(15, 50)
        gained = min(gained, gridiron.FIELD_YARDS - yardline)
        wall = used + (game.gap(HUDDLE_S) if kind == "pass_incomplete" else 0.0)
        game.clock -= used
        game.emit("play", offense, wall, kind=kind, yards=gained, down=down)

        passing = kind.startswith("pass")
        if rng.random() < (INTERCEPTION_RATE if passing else FUMBLE_RATE):
            lost = "interception" if passing else "fumble"
            game.emit("turnover", offense, game.gap((1, 3)), kind=lost)
            received = max(min(gridiron.FIELD_YARDS - yardline - gained, 95), 5)
            return game.other(offense), received, "turnover"

        yardline += gained
        if yardline >= gridiron.FIELD_YARDS:
            _touchdown(game, offense)
            return game.other(offense), TOUCHBACK, "touchdown"
        if yardline <= 0:
            game.score[game.other(offense)] += gridiron.SAFETY
            game.emit("safety", game.other(offense), game.gap((1, 3)))
            return game.other(offense), TOUCHBACK, "safety"
        if gained < to_go and down == gridiron.DOWNS:
            return game.other(offense), gridiron.FIELD_YARDS - yardline, "downs"

        down, to_go = (
            (1, min(10, gridiron.FIELD_YARDS - yardline))
            if gained >= to_go
            else (down + 1, to_go - gained)
        )
        if rng.random() < TIMEOUT_RATE:
            game.emit("timeout", offense, game.gap(TIMEOUT_BREAK_S))
    return offense, max(yardline, 1), None


def simulate_american_football(
    seed: int, config: AmericanFootballConfig | None = None
) -> list[MatchEvent]:
    """Genera un partido completo, determinista para cada semilla."""
    game = _Game(seed, config or AmericanFootballConfig())
    home, away = game.config.home_team, game.config.away_team
    offense, start = home, TOUCHBACK
    reason: str | None = "kickoff"
    while True:
        if reason is not None:
            game.change(offense, reason, game.gap((8, 15)))
        offense, start, reason = _drive(game, offense, start)
        if game.clock > 0:
            continue
        # Se acabó el cuarto: descanso, prórroga si hay empate, o final.
        game.period += 1
        tied = game.score[home] == game.score[away]
        if game.period > gridiron.MAX_PERIOD or (game.period == gridiron.MAX_PERIOD and not tied):
            return game.events
        overtime = game.period == gridiron.MAX_PERIOD
        game.clock = float(gridiron.OVERTIME_DURATION_S if overtime else gridiron.PERIOD_DURATION_S)
        second_half = game.period == gridiron.SECOND_HALF_START
        game.wall += timedelta(seconds=HALF_TIME_S if second_half else QUARTER_BREAK_S)
        if second_half or overtime:
            offense, start, reason = (away if second_half else home), TOUCHBACK, "half_start"
