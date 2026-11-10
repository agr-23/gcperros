"""Generador determinista de partidos de baloncesto (#88).

Es la HU-8 para el segundo deporte, y con el mismo enfoque: el partido es una
**secuencia de posesiones**, no una lista de eventos sueltos. Cada posesión
termina en una canasta, un rebote defensivo, una pérdida o unos tiros libres, y
nunca dura más que el reloj de posesión.

Dos relojes
-----------
En baloncesto el reloj de juego se para con cada falta, cada tiro libre y cada
tiempo muerto. Por eso el generador lleva dos: el **reloj de juego**, que corre
sólo con el balón vivo y viaja en ``clock_s``, y el **reloj de pared**, que es
el ``event_time`` del contrato y avanza también con el juego parado. Esas
paradas son lo que pone a prueba la marca de agua.

Determinismo
------------
Como en el fútbol: todo el azar sale de un único ``random.Random(seed)`` y los
identificadores son UUID v5 del partido y el orden de emisión.

Calibración
-----------
Medias por equipo sobre 200 partidos, contra rangos de referencia de ligas
FIBA de primer nivel (``docs/decisiones-de-diseno.md``, sección 18).
``tests/test_basketball_statistics.py`` las vuelve a comprobar en cada
ejecución.

========================== ========== ==============
Métrica (por equipo)         Simulado   Referencia
========================== ========== ==============
Posesiones                       71.0        68 - 76
Puntos                           81.7        75 - 88
Puntos por posesión              1.15   1.05 - 1.18
Triples sobre tiros de campo     40 %       35 - 45 %
Acierto de dos                   54 %       50 - 57 %
Acierto de triple                34 %       32 - 38 %
Tiros libres por tiro            0.35   0.25 - 0.40
Acierto de tiro libre            76 %       72 - 80 %
Rebote ofensivo                  27 %       24 - 32 %
Pérdidas                         13.8        10 - 15
Faltas                           19.6        17 - 23
Tiempos muertos                   3.4         2 - 5
========================== ========== ==============

Un partido tiene unos 445 eventos en unos 93 minutos de pared, y uno de cada
20 se va a la prórroga.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from gcperros.core import court
from gcperros.core.basketball_stats import BasketballSummary, summarize_basketball
from gcperros.core.contracts import BasketballEventType, JsonValue, MatchEvent, new_event_id
from gcperros.core.expected_points import FREE_THROW_PROBABILITY, make_probability

#: Hora del salto inicial. Constante, como el saque del fútbol: el instante de
#: ejecución no puede filtrarse en un artefacto reproducible.
DEFAULT_TIPOFF = datetime(2026, 11, 12, 20, 0, 0, tzinfo=UTC)

# --- Descansos (segundos de pared) -------------------------------------------
BREAK_BETWEEN_PERIODS_S = 2 * 60
HALF_TIME_BREAK_S = 15 * 60

# --- Tiempo de cada intento ----------------------------------------------------
# Lo que tarda el ataque en resolver, en reloj de juego. Una posesión nueva
# empieza en campo propio; tras un rebote ofensivo se juega cerca del aro.
ATTEMPT_MEAN_S = 15.0
ATTEMPT_STDEV_S = 4.0
SECOND_CHANCE_MEAN_S = 6.0
SECOND_CHANCE_STDEV_S = 3.0
ATTEMPT_MIN_S = 1.5

#: El reloj de posesión que queda tras un rebote ofensivo o una falta en ataque.
SHOT_CLOCK_RESET_S = 14

# --- Cómo termina cada intento ------------------------------------------------
TURNOVER_PROBABILITY = 0.11
NON_SHOOTING_FOUL_PROBABILITY = 0.13
TURNOVER_KINDS: tuple[tuple[str, float], ...] = (
    ("steal", 0.45),
    ("bad_pass", 0.27),
    ("out_of_bounds", 0.16),
    ("offensive_foul", 0.12),
)

# --- Tiros --------------------------------------------------------------------
THREE_POINT_RATE = 0.40
#: Entre los tiros de dos, la proporción que se juega pegada al aro.
RIM_SHOT_RATE = 0.58
RIM_RANGE_M = (0.3, 1.8)
MID_RANGE_M = (1.8, 6.5)
THREE_RANGE_M = (court.THREE_POINT_DISTANCE, 8.2)
#: Ángulo máximo respecto al eje del aro.
MAX_SHOT_ANGLE = 1.2
#: FIBA: la línea de triple corre a 0,90 m de la banda. Un tiro lejano y muy
#: abierto quedaría fuera de la cancha, y la frontera lo rechazaría.
SIDELINE_MARGIN_M = 0.9

#: Un tiro con falta es un tiro defendido de cerca: entra mucho menos.
SHOOTING_FOUL_PROBABILITY = 0.12
FOULED_SHOT_PENALTY = 0.45

OFFENSIVE_REBOUND_AFTER_SHOT = 0.29
OFFENSIVE_REBOUND_AFTER_FREE_THROW = 0.14

#: En FIBA, desde la quinta falta de equipo en un cuarto cada falta da dos tiros.
TEAM_FOULS_FOR_BONUS = 4

# --- Paradas del reloj de juego (segundos de pared) --------------------------
STOP_AFTER_FOUL_S = 22.0
STOP_PER_FREE_THROW_S = 11.0
STOP_AFTER_DEAD_BALL_S = 9.0
STOP_FOR_TIMEOUT_S = 75.0
#: En los dos últimos minutos del último cuarto y de la prórroga, el reloj se
#: para también tras canasta.
CLUTCH_TIME_S = 2 * 60
STOP_AFTER_CLUTCH_BASKET_S = 6.0

# --- Tiempos muertos ------------------------------------------------------------
# FIBA: dos en la primera parte, tres en la segunda y uno por prórroga.
TIMEOUTS_FIRST_HALF = 2
TIMEOUTS_SECOND_HALF = 3
TIMEOUTS_PER_OVERTIME = 1
#: Una racha del rival a partir de la cual el entrenador para el partido.
RUN_THAT_CALLS_TIMEOUT = 8
#: La probabilidad de pedirlo, sin racha, en cada balón muerto.
SPONTANEOUS_TIMEOUT_PROBABILITY = 0.05


@dataclass(frozen=True, slots=True)
class BasketballConfig:
    """Parámetros de un partido de baloncesto a simular."""

    match_id: str = "match-0001"
    home_team: str = "HOME"
    away_team: str = "AWAY"
    tipoff: datetime = DEFAULT_TIPOFF


class _BasketballSimulator:
    """Máquina de estados del partido. La API pública es ``simulate_basketball``."""

    def __init__(self, seed: int, config: BasketballConfig) -> None:
        self._rng = random.Random(seed)
        self._config = config
        self._teams = (config.home_team, config.away_team)
        self._events: list[MatchEvent] = []
        self._sequence = 0
        self._wall_s = 0.0
        self._clock_s = 0.0
        self._period = 1
        self._score = dict.fromkeys(self._teams, 0)
        self._team_fouls = dict.fromkeys(self._teams, 0)
        self._timeouts_left = dict.fromkeys(self._teams, 0)
        # La racha en curso: quién la lleva y cuántos puntos seguidos suma.
        self._run_team = ""
        self._run_points = 0

    # -- emisión --------------------------------------------------------------

    def _emit(
        self, team: str, event_type: BasketballEventType, attrs: dict[str, JsonValue]
    ) -> None:
        self._sequence += 1
        attrs["period"] = self._period
        attrs["clock_s"] = round(self._clock_s, 1)
        self._events.append(
            MatchEvent(
                event_id=new_event_id(self._config.match_id, self._sequence),
                event_time=self._config.tipoff + timedelta(seconds=self._wall_s),
                match_id=self._config.match_id,
                team=team,
                event_type=event_type,
                attrs=attrs,
            )
        )

    def _opponent(self, team: str) -> str:
        return self._teams[1] if team == self._teams[0] else self._teams[0]

    def _play(self, seconds: float) -> None:
        """Corre el reloj de juego, y con él el de pared."""
        self._clock_s -= seconds
        self._wall_s += seconds

    def _stop(self, seconds: float) -> None:
        """Juego parado: sólo avanza el reloj de pared."""
        self._wall_s += seconds

    def _clutch(self) -> bool:
        return self._period >= court.REGULATION_PERIODS and self._clock_s <= CLUTCH_TIME_S

    # -- partido ----------------------------------------------------------------

    def run(self) -> list[MatchEvent]:
        """Juega los cuatro cuartos y las prórrogas que hagan falta."""
        home, away = self._teams
        # El salto inicial lo gana cualquiera; luego manda la flecha de
        # posesión alterna, que da cada periodo siguiente al otro equipo.
        jump_winner = self._rng.choice(self._teams)
        for period in range(1, court.MAX_PERIOD + 1):
            self._period = period
            starter = jump_winner if period % 2 == 1 else self._opponent(jump_winner)
            self._play_period(starter)
            tied = self._score[home] == self._score[away]
            if period >= court.REGULATION_PERIODS and not tied:
                break
        return self._events

    def _play_period(self, team: str) -> None:
        overtime = self._period > court.REGULATION_PERIODS
        if self._period == court.SECOND_HALF_START:
            self._stop(HALF_TIME_BREAK_S)
        elif self._period > 1:
            self._stop(BREAK_BETWEEN_PERIODS_S)

        if self._period in (1, court.SECOND_HALF_START):
            allowance = TIMEOUTS_FIRST_HALF if self._period == 1 else TIMEOUTS_SECOND_HALF
            self._timeouts_left = dict.fromkeys(self._teams, allowance)
        elif overtime:
            self._timeouts_left = dict.fromkeys(self._teams, TIMEOUTS_PER_OVERTIME)
        # Las faltas de la prórroga cuentan como del último cuarto.
        if not overtime:
            self._team_fouls = dict.fromkeys(self._teams, 0)

        self._clock_s = float(court.OVERTIME_DURATION_S if overtime else court.PERIOD_DURATION_S)
        reason = "jump_ball" if self._period == 1 else "period_start"
        while True:
            self._emit(
                team,
                "possession_change",
                {"from_team": self._opponent(team), "to_team": team, "reason": reason},
            )
            outcome = self._play_possession(team)
            # Una posesión que empezaría con el periodo ya acabado no se juega.
            if outcome is None or self._clock_s <= ATTEMPT_MIN_S:
                return
            team, reason = outcome

    # -- posesión ---------------------------------------------------------------

    def _play_possession(self, team: str) -> tuple[str, str] | None:
        """Juega una posesión. Devuelve quién sigue y por qué, o nada si acabó el periodo."""
        opponent = self._opponent(team)
        shot_clock = float(court.SHOT_CLOCK_S)
        mean, stdev = ATTEMPT_MEAN_S, ATTEMPT_STDEV_S

        while True:
            needed = max(ATTEMPT_MIN_S, self._rng.gauss(mean, stdev))
            if self._clock_s <= ATTEMPT_MIN_S:
                self._play(self._clock_s)
                return None
            if needed >= shot_clock and shot_clock < self._clock_s:
                self._play(shot_clock)
                return self._turnover(team, "shot_clock_violation")
            # Con el reloj de juego a punto de acabar se tira lo que quede.
            self._play(min(needed, self._clock_s))

            roll = self._rng.random()
            if roll < TURNOVER_PROBABILITY:
                return self._turnover(team, self._turnover_kind())
            if roll < TURNOVER_PROBABILITY + NON_SHOOTING_FOUL_PROBABILITY:
                free_throws = 2 if self._team_fouls[opponent] >= TEAM_FOULS_FOR_BONUS else 0
                self._foul(opponent, team, free_throws)
                if free_throws:
                    return self._free_throws(team, free_throws)
                shot_clock = max(shot_clock - needed, SHOT_CLOCK_RESET_S)
                continue

            result = self._shot(team)
            if result is not None:
                return result
            # Rebote ofensivo: la posesión sigue, cerca del aro.
            shot_clock = SHOT_CLOCK_RESET_S
            mean, stdev = SECOND_CHANCE_MEAN_S, SECOND_CHANCE_STDEV_S

    def _turnover_kind(self) -> str:
        kinds = [kind for kind, _ in TURNOVER_KINDS]
        weights = [weight for _, weight in TURNOVER_KINDS]
        return self._rng.choices(kinds, weights)[0]

    def _turnover(self, team: str, kind: str) -> tuple[str, str]:
        opponent = self._opponent(team)
        if kind == "offensive_foul":
            self._foul(team, opponent, 0)
        self._emit(team, "turnover", {"kind": kind})
        if kind != "steal":
            self._stop(STOP_AFTER_DEAD_BALL_S)
            self._maybe_timeout()
        return opponent, "turnover"

    def _foul(self, fouler: str, fouled: str, free_throws: int) -> None:
        self._team_fouls[fouler] += 1
        self._emit(fouler, "foul", {"against_team": fouled, "free_throws": free_throws})
        self._stop(STOP_AFTER_FOUL_S)
        self._maybe_timeout()

    def _shot(self, team: str) -> tuple[str, str] | None:
        """Un tiro de campo. Devuelve el cambio de posesión, o nada si hay rebote ofensivo."""
        three = self._rng.random() < THREE_POINT_RATE
        points_value = court.THREE_POINTS if three else court.TWO_POINTS
        if three:
            distance = self._rng.uniform(*THREE_RANGE_M)
        elif self._rng.random() < RIM_SHOT_RATE:
            distance = self._rng.uniform(*RIM_RANGE_M)
        else:
            distance = self._rng.uniform(*MID_RANGE_M)
        reach = (court.WIDTH / 2 - SIDELINE_MARGIN_M) / distance
        widest = min(MAX_SHOT_ANGLE, math.asin(min(1.0, reach)))
        angle = self._rng.uniform(-widest, widest)
        basket_x, basket_y = court.BASKET

        fouled = self._rng.random() < SHOOTING_FOUL_PROBABILITY
        probability = make_probability(points_value, distance)
        if fouled:
            probability = round(probability * FOULED_SHOT_PENALTY, 4)
        made = self._rng.random() < probability

        self._emit(
            team,
            "shot",
            {
                "x": round(basket_x - distance * math.cos(angle), 2),
                "y": round(basket_y + distance * math.sin(angle), 2),
                "points_value": points_value,
                "made": made,
                "make_probability": probability,
            },
        )
        if made:
            self._score_points(team, points_value)

        if fouled:
            self._foul(self._opponent(team), team, 1 if made else points_value)
            return self._free_throws(team, 1 if made else points_value)
        if made:
            if self._clutch():
                self._stop(STOP_AFTER_CLUTCH_BASKET_S)
            self._maybe_timeout()
            return self._opponent(team), "made_shot"
        return self._rebound(team, OFFENSIVE_REBOUND_AFTER_SHOT)

    def _free_throws(self, team: str, count: int) -> tuple[str, str] | None:
        made = False
        for _ in range(count):
            self._stop(STOP_PER_FREE_THROW_S)
            made = self._rng.random() < FREE_THROW_PROBABILITY
            self._emit(
                team, "free_throw", {"made": made, "make_probability": FREE_THROW_PROBABILITY}
            )
            if made:
                self._score_points(team, 1)
        if made:
            self._maybe_timeout()
            return self._opponent(team), "made_free_throw"
        return self._rebound(team, OFFENSIVE_REBOUND_AFTER_FREE_THROW)

    def _rebound(self, team: str, offensive_rate: float) -> tuple[str, str] | None:
        if self._rng.random() < offensive_rate:
            self._emit(team, "rebound", {"kind": "offensive"})
            return None
        opponent = self._opponent(team)
        self._emit(opponent, "rebound", {"kind": "defensive"})
        return opponent, "defensive_rebound"

    # -- marcador y tiempos muertos ---------------------------------------------

    def _score_points(self, team: str, points: int) -> None:
        self._score[team] += points
        if team == self._run_team:
            self._run_points += points
        else:
            self._run_team, self._run_points = team, points

    def _maybe_timeout(self) -> None:
        """Con el balón muerto, el entrenador que sufre una racha para el partido."""
        victim = self._opponent(self._run_team) if self._run_team else ""
        if victim and self._run_points >= RUN_THAT_CALLS_TIMEOUT and self._timeouts_left[victim]:
            self._call_timeout(victim)
            # Cortada la racha: el siguiente tiempo muerto necesitará otra.
            self._run_points = 0
            return
        if self._rng.random() < SPONTANEOUS_TIMEOUT_PROBABILITY:
            team = self._teams[self._rng.randrange(2)]
            if self._timeouts_left[team]:
                self._call_timeout(team)

    def _call_timeout(self, team: str) -> None:
        self._timeouts_left[team] -= 1
        self._emit(team, "timeout", {})
        self._stop(STOP_FOR_TIMEOUT_S)


def simulate_basketball(seed: int, config: BasketballConfig | None = None) -> list[MatchEvent]:
    """Simula un partido de baloncesto completo de forma determinista.

    Args:
        seed: Semilla. La misma semilla y configuración dan el mismo partido.
        config: Identificadores y hora del salto inicial.

    Returns:
        Los eventos del partido en orden cronológico no decreciente.
    """
    return _BasketballSimulator(seed, config or BasketballConfig()).run()


__all__ = [
    "BasketballConfig",
    "BasketballSummary",
    "simulate_basketball",
    "summarize_basketball",
]
