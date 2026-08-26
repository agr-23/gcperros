"""Estado vivo del partido, construido evento a evento.

Es la contraparte en streaming de ``core.stats.summarize_events``. El plano
batch ve el flujo entero de una vez y puede permitirse recorrerlo con calma;
este acumulador recibe los eventos de uno en uno, sin saber cuántos faltan, y
tiene que sostener en todo momento un estado consultable.

Ambos deben coincidir. Esa igualdad es la validación del OE-2 y aquí queda
preparada: el acumulador expone ``summary()``, que devuelve exactamente la misma
estructura que produce el plano batch.

Este estado es también lo que alimentará el documento agregado por partido de
Firestore (HU-15): un único documento denormalizado, no un documento por evento.
"""

from __future__ import annotations

from gcperros.core.contracts import MatchEvent
from gcperros.core.stats import MatchSummary, as_float


class LiveMatchState:
    """Acumula los indicadores del partido a medida que llegan los eventos."""

    __slots__ = (
        "_completed_passes",
        "_event_count",
        "_fouls",
        "_goals",
        "_passes",
        "_possessions",
        "_red_cards",
        "_shots",
        "_teams",
        "_total_xg",
    )

    def __init__(self) -> None:
        """Crea un estado vacío, sin equipos conocidos todavía."""
        # Los equipos se aprenden del propio flujo, en orden de aparición: el
        # motor consume de un topic y no recibe la alineación por otro canal.
        self._teams: dict[str, None] = {}
        self._event_count = 0
        self._goals: dict[str, int] = {}
        self._shots: dict[str, int] = {}
        self._total_xg: dict[str, float] = {}
        self._passes: dict[str, int] = {}
        self._completed_passes: dict[str, int] = {}
        self._fouls: dict[str, int] = {}
        self._red_cards: dict[str, int] = {}
        self._possessions: dict[str, int] = {}

    def _register(self, team: str) -> None:
        if team in self._teams:
            return
        self._teams[team] = None
        for counter in (
            self._goals,
            self._shots,
            self._passes,
            self._completed_passes,
            self._fouls,
            self._red_cards,
            self._possessions,
        ):
            counter[team] = 0
        self._total_xg[team] = 0.0

    def apply(self, event: MatchEvent) -> None:
        """Incorpora un evento al estado.

        No comprueba duplicados ni orden: eso ocurre antes, en el motor. Este
        objeto asume que todo lo que le llega debe aplicarse, y esa separación es
        lo que lo mantiene simple y comparable con el plano batch.
        """
        self._register(event.team)
        self._event_count += 1

        match event.event_type:
            case "goal":
                self._goals[event.team] += 1
            case "shot":
                self._shots[event.team] += 1
                self._total_xg[event.team] += as_float(event.attrs["xg"])
            case "pass":
                self._passes[event.team] += 1
                if event.attrs["completed"]:
                    self._completed_passes[event.team] += 1
            case "foul":
                self._fouls[event.team] += 1
            case "red_card":
                self._red_cards[event.team] += 1
            case "possession_change":
                self._possessions[event.team] += 1

    def summary(self) -> MatchSummary:
        """Proyecta el estado actual a la misma estructura del plano batch."""
        return MatchSummary(
            event_count=self._event_count,
            goals=dict(self._goals),
            shots=dict(self._shots),
            total_xg={team: round(value, 4) for team, value in self._total_xg.items()},
            passes=dict(self._passes),
            completed_passes=dict(self._completed_passes),
            fouls=dict(self._fouls),
            red_cards=dict(self._red_cards),
            possessions=dict(self._possessions),
        )
