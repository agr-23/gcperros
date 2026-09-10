"""Posesión medida en tiempo, acumulada y por ventana móvil (HU-20).

Hasta aquí el proyecto contaba *cuántas veces* cada equipo recuperó el balón.
Eso no es la posesión que se ve en una retransmisión: la posesión es la
**fracción del tiempo de juego** que cada equipo tuvo el balón, y son cosas
distintas. Un equipo puede recuperar el balón el doble de veces que el rival y
tener la mitad de posesión.

Dos lecturas del mismo dato
---------------------------
El acumulado de todo el partido responde «quién ha mandado». La ventana de cinco
minutos responde «quién manda ahora», que es lo que un apostador en vivo
necesita y lo que el promedio del partido esconde: un 55-45 global puede tapar
que en el último cuarto de hora el marcador de posesión es 30-70.

La ventana y la marca de agua
-----------------------------
Una ventana se cierra cuando la marca de agua del motor (HU-12) pasa su borde
derecho, no cuando llega un evento posterior. Es la misma promesa de la marca de
agua aplicada a un agregado: cerrada la ventana, **ya no puede llegar nada que
pertenezca a ella**, así que su cifra es definitiva y no se reabre. Un evento
rezagado que caería dentro ya fue descartado antes de llegar aquí.

El tiempo que no es de nadie
----------------------------
La posesión se acumula entre eventos consecutivos y se atribuye a quien tuviera
el balón. Un hueco mayor que ``MAX_IN_PLAY_GAP_S`` no cuenta para nadie: el
juego estaba detenido. Sin esa regla, el equipo que tuviera el balón al final
del primer tiempo se llevaría los quince minutos del descanso como posesión.

El umbral no es una intuición. El reparto de huecos entre eventos, medido sobre
doce partidos (n = 14.623), tiene una banda vacía justo donde hace falta:

======================= ========== ==========================================
 Hueco                   Huecos     Qué es
======================= ========== ==========================================
 menos de 8 s              13.725   Juego: la duración de un pase y su ruido
 entre 8 y 14 s                 3   **Nada**
 14 s o más                   895   Balón parado: saque de banda, falta, gol
======================= ========== ==========================================

Diez segundos cae en mitad de esa banda vacía, así que mover el umbral unos
segundos arriba o abajo no cambia el resultado. Con él, el tiempo de juego
atribuido queda en unos 65 min por partido. La referencia del fútbol real está
entre 55 y 60: la diferencia no viene del umbral sino del generador (HU-8), cuyo
modelo de balón parado es más ligero que la realidad. Queda anotado como
limitación en lugar de disimularse ajustando el corte hasta que cuadre.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from gcperros.core.contracts import MatchEvent

#: Anchura de la ventana móvil. Cinco minutos es el horizonte que la historia
#: pide: suficiente para que un cambio de dinámica se note, corto para que no lo
#: diluya el resto del partido.
POSSESSION_WINDOW_S = 300.0

#: Hueco máximo entre eventos que sigue contando como juego. Elegido dentro de
#: la banda vacía que separa el juego del balón parado; ver el encabezado.
MAX_IN_PLAY_GAP_S = 10.0


@dataclass(frozen=True, slots=True)
class PossessionWindow:
    """Una ventana de posesión ya cerrada, con su cifra definitiva."""

    index: int
    start: datetime
    end: datetime
    seconds: dict[str, float]

    @property
    def in_play_seconds(self) -> float:
        """Tiempo de juego atribuido dentro de la ventana."""
        return sum(self.seconds.values())

    @property
    def share(self) -> dict[str, float]:
        """Fracción de posesión por equipo dentro de la ventana.

        Una ventana sin juego —el descanso, por ejemplo— devuelve un reparto
        vacío en lugar de dividir por cero. Que exista y esté vacía es
        información: dice que en esos cinco minutos no se jugó.
        """
        total = self.in_play_seconds
        if total <= 0.0:
            return {}
        return {team: value / total for team, value in self.seconds.items()}


@dataclass(frozen=True, slots=True)
class PossessionSnapshot:
    """Lo que la posesión dice en este instante."""

    running_seconds: dict[str, float]
    open_window_seconds: dict[str, float]

    @property
    def running_share(self) -> dict[str, float]:
        """Reparto de posesión de todo el partido hasta ahora."""
        total = sum(self.running_seconds.values())
        if total <= 0.0:
            return {}
        return {team: value / total for team, value in self.running_seconds.items()}

    @property
    def in_play_seconds(self) -> float:
        """Tiempo de juego acumulado, sin contar los parones."""
        return sum(self.running_seconds.values())


class PossessionTracker:
    """Acumula posesión por tiempo y la reparte en ventanas de anchura fija.

    Consume los eventos **en orden cronológico**. En el motor eso lo garantiza el
    reordenador por marca de agua; en el plano batch, el propio flujo ya viene
    ordenado.
    """

    __slots__ = (
        "_holder",
        "_last_time",
        "_max_gap",
        "_next_open",
        "_origin",
        "_running",
        "_teams",
        "_window_s",
        "_windows",
    )

    def __init__(
        self,
        window_s: float = POSSESSION_WINDOW_S,
        max_in_play_gap_s: float = MAX_IN_PLAY_GAP_S,
    ) -> None:
        """Crea un acumulador vacío.

        Args:
            window_s: Anchura de cada ventana, en segundos.
            max_in_play_gap_s: Hueco por encima del cual se entiende que el
                juego estaba detenido y el tiempo no se atribuye.

        Raises:
            ValueError: Si la anchura o el hueco no son positivos.
        """
        if window_s <= 0:
            raise ValueError("la anchura de la ventana debe ser positiva")
        if max_in_play_gap_s <= 0:
            raise ValueError("el hueco máximo debe ser positivo")

        self._window_s = window_s
        self._max_gap = max_in_play_gap_s
        self._origin: datetime | None = None
        self._holder: str | None = None
        self._last_time: datetime | None = None
        self._running: dict[str, float] = {}
        self._teams: dict[str, None] = {}
        self._windows: dict[int, dict[str, float]] = {}
        # Índice de la primera ventana todavía abierta. Sólo avanza, nunca
        # retrocede: es la misma monotonía que garantiza la marca de agua.
        self._next_open = 0

    # -- consumo --------------------------------------------------------------

    def apply(self, event: MatchEvent) -> None:
        """Incorpora un evento, atribuyendo el tiempo transcurrido desde el anterior."""
        self._teams.setdefault(event.team, None)
        self._running.setdefault(event.team, 0.0)

        if self._origin is None:
            self._origin = event.event_time

        # El intervalo que acaba de cerrarse pertenece a quien tuviera el balón
        # *antes* de este evento, así que se atribuye antes de actualizar nada.
        if self._holder is not None and self._last_time is not None:
            self._accrue(self._holder, self._last_time, event.event_time)

        if event.event_type == "possession_change":
            self._holder = event.team

        self._last_time = event.event_time

    def _accrue(self, team: str, start: datetime, end: datetime) -> None:
        """Reparte un intervalo entre las ventanas que atraviesa."""
        seconds = (end - start).total_seconds()
        if seconds <= 0 or seconds > self._max_gap:
            # Ni tiempo hacia atrás ni parones: ese tiempo no es de nadie.
            return

        self._running[team] = self._running.get(team, 0.0) + seconds

        # Un intervalo puede cruzar el borde de una ventana, así que se parte y
        # cada trozo va a la suya. Sin esto, la posesión de los últimos segundos
        # de una ventana se le regalaría a la siguiente.
        cursor = start
        while cursor < end:
            index = self._window_index(cursor)
            boundary = min(end, self._window_start(index + 1))
            bucket = self._windows.setdefault(index, {})
            bucket[team] = bucket.get(team, 0.0) + (boundary - cursor).total_seconds()
            cursor = boundary

    # -- ventanas -------------------------------------------------------------

    def _window_index(self, moment: datetime) -> int:
        if self._origin is None:
            return 0
        return int((moment - self._origin).total_seconds() // self._window_s)

    def _window_start(self, index: int) -> datetime:
        if self._origin is None:
            raise RuntimeError("no hay ventanas hasta que llega el primer evento")
        return self._origin + timedelta(seconds=index * self._window_s)

    def _build(self, index: int) -> PossessionWindow:
        seconds = self._windows.get(index, {})
        return PossessionWindow(
            index=index,
            start=self._window_start(index),
            end=self._window_start(index + 1),
            seconds={team: round(seconds.get(team, 0.0), 3) for team in self._teams},
        )

    def close_through(self, watermark: datetime) -> list[PossessionWindow]:
        """Cierra las ventanas que la marca de agua ya rebasó.

        Args:
            watermark: Reloj de confianza del motor. Una ventana se cierra sólo
                cuando su borde derecho queda por detrás de él.

        Returns:
            Las ventanas cerradas, contiguas y en orden. Se devuelven también las
            que quedaron vacías: la serie temporal no debe tener huecos, y una
            ventana a cero dice que en esos cinco minutos no se jugó.
        """
        if self._origin is None:
            return []

        closed: list[PossessionWindow] = []
        while self._window_start(self._next_open + 1) <= watermark:
            closed.append(self._build(self._next_open))
            self._next_open += 1
        return closed

    @property
    def open_window_index(self) -> int:
        """Índice de la ventana que sigue admitiendo tiempo."""
        return self._next_open

    # -- consulta -------------------------------------------------------------

    def snapshot(self) -> PossessionSnapshot:
        """Estado actual: acumulado del partido y ventana todavía abierta."""
        open_window = self._windows.get(self._next_open, {})
        return PossessionSnapshot(
            running_seconds={team: round(value, 3) for team, value in self._running.items()},
            open_window_seconds={
                team: round(open_window.get(team, 0.0), 3) for team in self._teams
            },
        )


def possession_totals(events: list[MatchEvent]) -> dict[str, float]:
    """Posesión acumulada de un flujo completo, en segundos por equipo.

    Es la referencia batch de la HU-20: recorre el flujo entero de una vez, sin
    ventanas ni marcas de agua. El motor tiene que llegar al mismo número por el
    camino incremental, y esa igualdad es lo que valida la maquinaria, no la
    fórmula —que es la misma en ambos lados a propósito—.
    """
    tracker = PossessionTracker()
    for event in events:
        tracker.apply(event)
    return tracker.snapshot().running_seconds
