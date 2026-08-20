"""Generador determinista de eventos de partido (HU-8).

El partido se modela como una **secuencia de posesiones**, no como una lista de
eventos sueltos. La diferencia importa: una posesión encadena pases que avanzan
el balón y termina por una causa concreta —pérdida, remate, gol o falta—, lo que
produce correlaciones temporales y espaciales que un muestreo independiente de
eventos no reproduce. La posesión acumulada, que es uno de los indicadores del
proyecto, solo tiene sentido si el generador la produce como consecuencia del
juego y no como un parámetro fijado de antemano.

Determinismo
------------
Todo el azar del módulo procede de una única instancia ``random.Random(seed)``.
No se usa el generador global de ``random``, ni ``uuid4``, ni ``datetime.now()``:
cualquiera de los tres haría que dos ejecuciones con la misma semilla difirieran.
Bajo semilla fija, ``simulate_match`` devuelve exactamente los mismos eventos,
con los mismos identificadores y las mismas marcas de tiempo.

Calibración
-----------
Las constantes no son arbitrarias: se ajustaron para que los agregados del
partido caigan en los rangos de referencia del dominio, que es el criterio de
verificación del OE-1. Medias observadas sobre 60 partidos, contra el rango que
declara la documentación del proyecto:

======================= ========== ==============
Métrica (ambos equipos)   Simulado   Referencia
======================= ========== ==============
Eventos por partido           1214    1200 - 1500
Pases                          937     900 - 1100
Pases completados           83.5 %       80 - 85 %
Remates                       26.4            ~25
xG por remate                0.116          ~0.11
xG acumulado                  3.06           ~2.7
Goles                         2.92           ~2.7
Faltas                        23.5            ~22
Posesiones                     224      200 - 250
======================= ========== ==============

``tests/test_match_statistics.py`` vuelve a comprobar estos rangos en cada
ejecución, de modo que un cambio de constantes que desplace la simulación fuera
del dominio plausible rompa la construcción en vez de pasar inadvertido.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from gcperros.core import pitch
from gcperros.core.contracts import EventType, JsonValue, MatchEvent, new_event_id
from gcperros.core.xg import expected_goals

# Hora de comienzo por defecto. Es una constante y no `datetime.now()` porque
# el instante de ejecución no puede filtrarse en un artefacto reproducible.
DEFAULT_KICKOFF = datetime(2026, 8, 26, 19, 0, 0, tzinfo=UTC)

FIRST_HALF = 1
SECOND_HALF = 2
HALF_DURATION_S = 45 * 60
HALF_TIME_BREAK_S = 15 * 60
STOPPAGE_RANGE_S = (60, 240)

# --- Pases -------------------------------------------------------------------
# La probabilidad de completar un pase decae al acercarse al área rival: es donde
# el rival defiende más junto y el espacio se cierra. El exponente hace que la
# caída sea suave en campo propio y pronunciada en los últimos metros, en vez de
# lineal a lo largo de todo el campo.
PASS_COMPLETION_AT_OWN_GOAL = 0.93
PASS_COMPLETION_AT_RIVAL_GOAL = 0.60
PASS_PRESSURE_EXPONENT = 2.2

PASS_ADVANCE_MEAN_M = 8.0
PASS_ADVANCE_STDEV_M = 6.5
PASS_LATERAL_STDEV_M = 6.5

# Atracción del pase hacia el eje longitudinal del campo. Un pase real cerca de
# la banda se juega hacia dentro; sin este término la dispersión lateral es una
# caminata aleatoria que manda el balón fuera mucho más de lo que ocurre en un
# partido.
PASS_CENTRING_PULL = 0.18

# Pérdidas que no provienen de un pase fallido: entradas, balones divididos,
# salidas por línea. Sin este término las posesiones se alargarían de forma
# irreal, porque el pase se completa demasiado a menudo.
LOOSE_BALL_PROBABILITY = 0.055

# --- Remates -----------------------------------------------------------------
# Solo se remata dentro de esta franja, y la propensión crece al acercarse.
SHOT_ZONE_START_X = pitch.LENGTH - 32.0
SHOT_BASE_PROBABILITY = 0.24
SHOT_ZONE_EXPONENT = 0.5

# --- Faltas ------------------------------------------------------------------
FOUL_PROBABILITY_PER_TOUCH = 0.024

# --- Duraciones (segundos) ---------------------------------------------------
PASS_DURATION_MEAN_S = 3.9
PASS_DURATION_STDEV_S = 1.2
PASS_DURATION_MIN_S = 0.8
SHOT_DURATION_S = 2.5
TURNOVER_DURATION_S = 1.5
DEAD_BALL_AFTER_FOUL_S = 22.0
DEAD_BALL_AFTER_SHOT_S = 18.0
DEAD_BALL_AFTER_GOAL_S = 65.0
DEAD_BALL_AFTER_THROW_IN_S = 14.0
DEAD_BALL_AFTER_GOAL_KICK_S = 25.0

# Punto desde el que se reanuda un saque de puerta, en el marco del equipo que
# saca.
GOAL_KICK_X = 8.0

# Corta posesiones patológicas. En una simulación bien parametrizada no debería
# activarse casi nunca, pero evita que un ajuste desafortunado de constantes
# produzca una posesión que no termina.
MAX_TOUCHES_PER_POSSESSION = 60


@dataclass(frozen=True, slots=True)
class MatchConfig:
    """Parámetros de un partido a simular."""

    match_id: str = "match-0001"
    home_team: str = "HOME"
    away_team: str = "AWAY"
    kickoff: datetime = DEFAULT_KICKOFF


@dataclass(frozen=True, slots=True)
class _PassOutcome:
    """Resultado de un pase: si llegó, si sacó el balón del campo y dónde acabó."""

    completed: bool
    left_the_field: bool
    end_x: float
    end_y: float


@dataclass(frozen=True, slots=True)
class MatchSummary:
    """Agregados de un partido, calculados sobre los eventos ya emitidos.

    Se derivan del propio flujo y no del estado interno del simulador: es la
    misma operación que hará el plano batch de referencia, de modo que el motor
    de streaming pueda contrastarse contra ella (OE-2).
    """

    event_count: int
    goals: dict[str, int]
    shots: dict[str, int]
    total_xg: dict[str, float]
    passes: dict[str, int]
    completed_passes: dict[str, int]
    fouls: dict[str, int]
    possessions: dict[str, int]


def pass_completion_probability(x: float) -> float:
    """Probabilidad de completar un pase iniciado a ``x`` metros del fondo propio."""
    progress = min(max(x / pitch.LENGTH, 0.0), 1.0)
    drop = PASS_COMPLETION_AT_OWN_GOAL - PASS_COMPLETION_AT_RIVAL_GOAL
    return float(PASS_COMPLETION_AT_OWN_GOAL - drop * progress**PASS_PRESSURE_EXPONENT)


def shot_probability(x: float) -> float:
    """Propensión a rematar desde ``x``, nula fuera de la zona de remate."""
    if x < SHOT_ZONE_START_X:
        return 0.0
    depth = (x - SHOT_ZONE_START_X) / (pitch.LENGTH - SHOT_ZONE_START_X)
    return float(SHOT_BASE_PROBABILITY * depth**SHOT_ZONE_EXPONENT)


class _MatchSimulator:
    """Máquina de estados del partido. Uso interno: la API pública es `simulate_match`."""

    def __init__(self, seed: int, config: MatchConfig) -> None:
        self._rng = random.Random(seed)
        self._config = config
        self._events: list[MatchEvent] = []
        self._sequence = 0
        self._clock_s = 0.0
        self._period = 1

    # -- emisión --------------------------------------------------------------

    def _emit(self, team: str, event_type: EventType, attrs: dict[str, JsonValue]) -> None:
        self._sequence += 1
        attrs["period"] = self._period
        self._events.append(
            MatchEvent(
                event_id=new_event_id(self._config.match_id, self._sequence),
                event_time=self._config.kickoff + timedelta(seconds=self._clock_s),
                match_id=self._config.match_id,
                team=team,
                event_type=event_type,
                attrs=attrs,
            )
        )

    def _advance(self, seconds: float) -> None:
        self._clock_s += seconds

    def _opponent(self, team: str) -> str:
        return self._config.away_team if team == self._config.home_team else self._config.home_team

    # -- simulación -----------------------------------------------------------

    def run(self) -> list[MatchEvent]:
        """Juega los dos tiempos reglamentarios y devuelve el flujo de eventos."""
        for period in (FIRST_HALF, SECOND_HALF):
            self._period = period
            self._play_half(period)
        return self._events

    def _play_half(self, period: int) -> None:
        # El descanso avanza el reloj de pared: los `event_time` del segundo
        # tiempo deben reflejar que pasaron 15 minutos sin juego.
        if period == SECOND_HALF:
            self._advance(HALF_TIME_BREAK_S)

        half_start_s = self._clock_s
        stoppage_s = self._rng.uniform(*STOPPAGE_RANGE_S)
        half_end_s = half_start_s + HALF_DURATION_S + stoppage_s

        # Saca el visitante en el segundo tiempo, como en el reglamento.
        team = self._config.home_team if period == FIRST_HALF else self._config.away_team
        previous_team = self._opponent(team)
        x, y = pitch.CENTER_SPOT
        reason = "kickoff"

        while self._clock_s < half_end_s:
            self._emit(
                team,
                "possession_change",
                {
                    "from_team": previous_team,
                    "to_team": team,
                    "reason": reason,
                    "start_x": round(x, 2),
                    "start_y": round(y, 2),
                },
            )
            previous_team = team
            team, x, y, reason = self._play_possession(team, x, y, half_end_s)

    def _play_possession(
        self, team: str, x: float, y: float, half_end_s: float
    ) -> tuple[str, float, float, str]:
        """Juega una posesión completa.

        Returns:
            El equipo que pasa a tener el balón, la posición desde la que lo
            iniciará —ya traducida a su propio marco de ataque— y la causa por
            la que cambió la posesión.
        """
        opponent = self._opponent(team)

        for _ in range(MAX_TOUCHES_PER_POSSESSION):
            if self._clock_s >= half_end_s:
                return opponent, *pitch.mirror(x, y), "half_end"

            if self._rng.random() < shot_probability(x):
                return self._resolve_shot(team, x, y)

            if self._rng.random() < FOUL_PROBABILITY_PER_TOUCH:
                # La falta la comete el defensor; el atacante conserva el balón
                # y saca desde donde se cometió, así que la posesión continúa.
                self._emit(
                    opponent,
                    "foul",
                    {"x": round(x, 2), "y": round(y, 2), "against_team": team},
                )
                self._advance(DEAD_BALL_AFTER_FOUL_S)
                continue

            outcome = self._attempt_pass(team, x, y)
            x, y = outcome.end_x, outcome.end_y

            if outcome.left_the_field:
                # El balón sale: reposición desde donde marca el reglamento, no
                # desde el punto imposible al que iba dirigido el pase.
                return self._restart_after_ball_out(opponent, x, y)

            if not outcome.completed:
                self._advance(TURNOVER_DURATION_S)
                return opponent, *pitch.mirror(x, y), "incomplete_pass"

            if self._rng.random() < LOOSE_BALL_PROBABILITY:
                self._advance(TURNOVER_DURATION_S)
                return opponent, *pitch.mirror(x, y), "loose_ball"

        return opponent, *pitch.mirror(x, y), "possession_exhausted"

    def _restart_after_ball_out(
        self, restarting_team: str, x: float, y: float
    ) -> tuple[str, float, float, str]:
        """Devuelve el balón al juego tras salir por línea de fondo o de banda."""
        if x > pitch.LENGTH:
            # Fondo: saque de puerta del rival desde su propia área.
            self._advance(DEAD_BALL_AFTER_GOAL_KICK_S)
            return restarting_team, GOAL_KICK_X, pitch.GOAL_CENTER_Y, "out_for_goal_kick"

        # Banda: saque de banda desde el punto por donde salió.
        self._advance(DEAD_BALL_AFTER_THROW_IN_S)
        return restarting_team, *pitch.mirror(*pitch.clamp_to_pitch(x, y)), "out_for_throw_in"

    def _attempt_pass(self, team: str, x: float, y: float) -> _PassOutcome:
        """Emite un pase y devuelve cómo terminó."""
        probability = pass_completion_probability(x)
        reached_target = self._rng.random() < probability

        target_x = x + self._rng.gauss(PASS_ADVANCE_MEAN_M, PASS_ADVANCE_STDEV_M)
        target_y = (
            y
            + self._rng.gauss(0.0, PASS_LATERAL_STDEV_M)
            + PASS_CENTRING_PULL * (pitch.GOAL_CENTER_Y - y)
        )

        # Un pase que apunta fuera del rectángulo saca el balón del juego. Antes
        # se recortaba la coordenada al borde del campo, lo que acumulaba una
        # masa artificial de eventos sobre las líneas —incluidos remates desde
        # la propia línea de gol— y distorsionaba la distribución espacial.
        left_the_field = not (0.0 <= target_x <= pitch.LENGTH and 0.0 <= target_y <= pitch.WIDTH)
        completed = reached_target and not left_the_field

        duration = max(
            PASS_DURATION_MIN_S,
            self._rng.gauss(PASS_DURATION_MEAN_S, PASS_DURATION_STDEV_S),
        )
        self._advance(duration)

        # Lo que se registra es el punto por el que el balón cruzó la línea, no
        # la coordenada imposible a la que apuntaba: así lo hacen los proveedores
        # reales de datos de eventos.
        recorded_x, recorded_y = pitch.clamp_to_pitch(target_x, target_y)

        self._emit(
            team,
            "pass",
            {
                "start_x": round(x, 2),
                "start_y": round(y, 2),
                "end_x": round(recorded_x, 2),
                "end_y": round(recorded_y, 2),
                "completed": completed,
                "left_the_field": left_the_field,
                "completion_probability": round(probability, 4),
            },
        )

        # El balón queda donde murió el pase, no donde iba dirigido. Se conserva
        # la coordenada sin recortar para poder distinguir el saque de puerta
        # (salió por el fondo) del saque de banda.
        return _PassOutcome(
            completed=completed,
            left_the_field=left_the_field,
            end_x=target_x if left_the_field else recorded_x,
            end_y=target_y if left_the_field else recorded_y,
        )

    def _resolve_shot(self, team: str, x: float, y: float) -> tuple[str, float, float, str]:
        """Emite el remate y, si acaba en gol, el evento de gol redundante."""
        opponent = self._opponent(team)
        xg = expected_goals(x, y)
        is_goal = self._rng.random() < xg

        self._advance(SHOT_DURATION_S)
        self._emit(
            team,
            "shot",
            {
                "x": round(x, 2),
                "y": round(y, 2),
                "xg": xg,
                "is_goal": is_goal,
            },
        )

        if is_goal:
            # Evento redundante exigido por el contrato (HU-1): el gol es un
            # hecho de negocio con vida propia, contable sin interpretar el tiro.
            self._emit(
                team,
                "goal",
                {"x": round(x, 2), "y": round(y, 2), "xg": xg},
            )
            self._advance(DEAD_BALL_AFTER_GOAL_S)
            return opponent, *pitch.CENTER_SPOT, "goal"

        self._advance(DEAD_BALL_AFTER_SHOT_S)
        # Tras un remate fallido el rival repone desde su propia área.
        return opponent, 8.0, pitch.GOAL_CENTER_Y, "shot"


def simulate_match(seed: int, config: MatchConfig | None = None) -> list[MatchEvent]:
    """Simula un partido completo de forma determinista.

    Args:
        seed: Semilla del generador pseudoaleatorio. La misma semilla y la misma
            configuración producen siempre el mismo partido, evento por evento.
        config: Identificadores y hora de comienzo. Por defecto, un partido
            genérico con hora de comienzo fija.

    Returns:
        Los eventos del partido en orden cronológico no decreciente.
    """
    return _MatchSimulator(seed, config or MatchConfig()).run()


def _as_float(value: JsonValue) -> float:
    """Lee un número de ``attrs`` rechazando lo que no lo sea.

    Un agregador que sumara silenciosamente lo que le llega convertiría un
    evento mal formado en un indicador plausible pero incorrecto, que es
    exactamente el fallo que la capa de gobernanza busca evitar.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"se esperaba un número y llegó {type(value).__name__}")
    return float(value)


def summarize_match(events: list[MatchEvent]) -> MatchSummary:
    """Agrega un flujo de eventos ya emitido.

    Recorre el flujo tal como llegaría a un consumidor, sin acceso al estado
    interno del simulador: por eso sirve como referencia contra la que medir el
    resultado del motor de streaming.
    """
    teams = {event.team for event in events}
    goals = dict.fromkeys(teams, 0)
    shots = dict.fromkeys(teams, 0)
    passes = dict.fromkeys(teams, 0)
    completed_passes = dict.fromkeys(teams, 0)
    fouls = dict.fromkeys(teams, 0)
    possessions = dict.fromkeys(teams, 0)
    total_xg = dict.fromkeys(teams, 0.0)

    for event in events:
        match event.event_type:
            case "goal":
                goals[event.team] += 1
            case "shot":
                shots[event.team] += 1
                total_xg[event.team] += _as_float(event.attrs["xg"])
            case "pass":
                passes[event.team] += 1
                if event.attrs["completed"]:
                    completed_passes[event.team] += 1
            case "foul":
                fouls[event.team] += 1
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
        possessions=possessions,
    )


def with_match_id(config: MatchConfig, match_id: str) -> MatchConfig:
    """Devuelve una copia de la configuración con otro identificador de partido."""
    return replace(config, match_id=match_id)
