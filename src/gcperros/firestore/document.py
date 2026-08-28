"""La forma exacta del documento de estado vivo de un partido (HU-15).

Un único documento por partido, denormalizado: trae los indicadores de los
dos equipos ya calculados y anidados por nombre, para que el dashboard no
tenga que cruzar varias colecciones ni volver a sumar nada. Es la traducción
directa de ``gcperros.core.stats.MatchSummary`` —la misma estructura que ya
comparten el plano batch y el motor— a la forma de un documento de Firestore.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from gcperros.core.contracts import JsonValue, format_event_time
from gcperros.core.stats import MatchSummary

#: Los ocho indicadores que trae cada equipo dentro de ``indicators``, en el
#: orden en que se escriben. Es la misma lista de campos de ``MatchSummary``
#: sin ``event_count`` (ese es del partido entero, no de un equipo).
_TEAM_INDICATOR_FIELDS = (
    "goals",
    "shots",
    "total_xg",
    "passes",
    "completed_passes",
    "fouls",
    "red_cards",
    "possessions",
)


@dataclass(frozen=True, slots=True)
class LiveMatchDocument:
    """El documento de estado vivo de un partido, ya listo para persistir.

    Attributes:
        match_id: Identificador del partido. Es también el identificador del
            documento dentro de la colección (``live_matches/{match_id}``):
            un partido tiene como mucho un documento vivo a la vez, nunca dos.
        teams: Equipos del partido, en el orden en que aparecieron en el
            flujo. Ese orden es el que ``LiveMatchState.teams`` ya preserva, y
            se conserva aquí para que el documento sea reproducible: la misma
            semilla produce siempre el mismo orden.
        event_count: Cuántos eventos del partido se han aplicado hasta este
            documento. Le permite al dashboard distinguir «no ha pasado nada»
            de «el listener se desconectó y dejó de recibir actualizaciones».
        updated_at: Cuándo se generó *este* documento. No es la hora del
            último evento del partido (``event_time``): es la hora de
            publicación, la que le dice al dashboard qué tan fresco es lo que
            está viendo.
        indicators: Los ocho indicadores de ``MatchSummary``, anidados por
            equipo. Deliberadamente anidado y no en paralelo (como los guarda
            ``MatchSummary`` internamente, un diccionario por indicador): un
            documento pensado para leerse en un dashboard responde mejor a
            «dame todo el Real Madrid» que a cruzar ocho diccionarios por el
            nombre del equipo.
    """

    match_id: str
    teams: tuple[str, ...]
    event_count: int
    updated_at: datetime
    indicators: dict[str, dict[str, JsonValue]]

    @classmethod
    def project(
        cls,
        match_id: str,
        teams: Sequence[str],
        summary: MatchSummary,
        updated_at: datetime,
    ) -> LiveMatchDocument:
        """Deriva el documento a partir de un resumen ya calculado.

        Es una función pura: no lee el estado del motor por sí misma, para
        que se pueda probar con cualquier ``MatchSummary`` —el del motor en
        vivo o el del plano batch— sin tener que levantar un partido
        completo.

        Args:
            match_id: Identificador del partido.
            teams: Equipos del partido, en el orden a conservar en el
                documento. Normalmente ``LiveMatchState.teams``.
            summary: Los indicadores ya agregados, del motor o del plano
                batch: ambos producen la misma estructura.
            updated_at: Instante de esta publicación.

        Raises:
            KeyError: Si algún equipo de ``teams`` no aparece en ``summary``.
                Sería un error de quien llama, no un dato de partido legítimo:
                ``summary`` siempre trae una entrada por cada equipo que
                registró al menos un evento.
        """
        indicators: dict[str, dict[str, JsonValue]] = {
            team: {
                "goals": summary.goals[team],
                "shots": summary.shots[team],
                "total_xg": summary.total_xg[team],
                "passes": summary.passes[team],
                "completed_passes": summary.completed_passes[team],
                "fouls": summary.fouls[team],
                "red_cards": summary.red_cards[team],
                "possessions": summary.possessions[team],
            }
            for team in teams
        }
        return cls(
            match_id=match_id,
            teams=tuple(teams),
            event_count=summary.event_count,
            updated_at=updated_at,
            indicators=indicators,
        )

    def to_firestore_document(self) -> dict[str, JsonValue]:
        """Proyecta el documento a lo que recibe el cliente de Firestore.

        ``updated_at`` se serializa con el mismo formato que el resto del
        contrato (``format_event_time``) y no como un tipo nativo de
        Firestore: mantiene una única representación de marca temporal en
        todo el proyecto, y sigue siendo comparable byte a byte entre
        ejecuciones, la misma promesa que ya sostienen los otros contratos.
        """
        return {
            "match_id": self.match_id,
            "teams": list(self.teams),
            "event_count": self.event_count,
            "updated_at": format_event_time(self.updated_at),
            # `dict` es invariante en su tipo de valor, así que mypy no puede
            # ver por sí mismo que `dict[str, dict[str, JsonValue]]` es un
            # caso particular de `JsonValue` (su propia definición es
            # recursiva e incluye exactamente esa forma). El `cast` no
            # silencia una comprobación real: declara una relación que sí se
            # sostiene, y que la variancia del tipo genérico no puede expresar.
            "indicators": cast("dict[str, JsonValue]", self.indicators),
        }
