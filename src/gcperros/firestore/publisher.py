"""Cuándo se publica el documento de estado vivo (HU-15).

La pregunta de *cuándo* escribir importa tanto como la de *qué* escribir.
Dos diseños se consideraron:

- **Por reloj**: un temporizador aparte que, cada cierto intervalo, toma el
  estado actual y lo escribe, haya cambiado o no. Necesita un hilo propio con
  su propio ciclo de vida (¿quién lo detiene, y cuándo?), y puede escribir un
  documento idéntico al anterior si no llegó ningún evento en la ventana.
- **Por evento** (la elegida): se publica en cuanto el motor aplica uno o más
  eventos al estado. No hace falta un reloj aparte —se apoya en el flujo que
  el motor ya recorre—, y nunca escribe un documento que no cambió.

``PublishingMatchEngine`` implementa la segunda opción envolviendo
``MatchEngine`` sin tocarlo: compara ``state.event_count`` antes y después de
cada llamada y publica sólo si avanzó. Es deliberadamente un envoltorio y no
un cambio a ``MatchEngine`` — el motor no necesita saber que alguien lo está
publicando, igual que no sabe si alguien está leyendo su estado por otro
lado, y sus pruebas y las de HU-11/HU-12 siguen intactas.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from gcperros.core.contracts import MatchEvent
from gcperros.engine.pipeline import MatchEngine, Outcome
from gcperros.engine.state import LiveMatchState
from gcperros.firestore.document import LiveMatchDocument
from gcperros.firestore.store import DocumentStore
from gcperros.governance.quarantine import utc_now

#: Nombre de la colección donde vive un documento por partido. Constante y no
#: configurable por ahora: nada en el proyecto necesita todavía más de una
#: colección de estado vivo, y añadir la opción antes de que haga falta sólo
#: sería superficie sin usar.
LIVE_MATCHES_COLLECTION = "live_matches"


class LiveStatePublisher:
    """Proyecta el estado del motor a un documento y lo escribe."""

    __slots__ = ("_clock", "_match_id", "_store")

    def __init__(
        self,
        store: DocumentStore,
        match_id: str,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Crea el publicador de un partido.

        Args:
            store: Dónde se escribe el documento.
            match_id: Identificador del partido y del documento
                (``live_matches/{match_id}``).
            clock: De dónde sale ``updated_at``. Se inyecta para que las
                pruebas puedan fijarlo, igual que en el resto del proyecto.
        """
        self._store = store
        self._match_id = match_id
        self._clock = clock

    def publish(self, state: LiveMatchState) -> None:
        """Proyecta el estado actual y sobrescribe el documento del partido.

        Raises:
            DocumentStoreError: Si el destino rechazó la escritura. Se deja
                propagar: a diferencia del cargador de la capa Raw (HU-14),
                aquí no hay un broker que reintente la entrega si se traga el
                fallo — quien orqueste la publicación (``PublishingMatchEngine``)
                es quien decide qué hacer con él.
        """
        document = LiveMatchDocument.project(
            match_id=self._match_id,
            teams=state.teams,
            summary=state.summary(),
            updated_at=self._clock(),
        )
        self._store.set(self._match_id, document.to_firestore_document())


class PublishingMatchEngine:
    """Un ``MatchEngine`` que publica su estado cada vez que cambia.

    Envuelve al motor en vez de modificarlo: cada método delega en el motor
    real y, si el estado avanzó, publica. Quien ya use ``MatchEngine`` puede
    cambiar a esta clase sin tocar el resto del código —misma interfaz,
    ``process``/``flush``—, y quien no necesite publicar sigue usando
    ``MatchEngine`` a secas, sin arrastrar una dependencia de Firestore.
    """

    __slots__ = ("_engine", "_last_published_count", "_publisher")

    def __init__(self, engine: MatchEngine, publisher: LiveStatePublisher) -> None:
        """Crea el envoltorio sobre un motor y un publicador ya construidos."""
        self._engine = engine
        self._publisher = publisher
        self._last_published_count = 0

    @property
    def state(self) -> LiveMatchState:
        """Estado vivo del motor envuelto."""
        return self._engine.state

    def process(self, event: MatchEvent) -> Outcome:
        """Procesa el evento y publica si el estado avanzó.

        Un evento aceptado no siempre publica: si queda retenido esperando a
        la marca de agua (HU-12), el estado todavía no cambió y no hay nada
        nuevo que escribir. Uno duplicado o descartado por tardío tampoco.
        """
        outcome = self._engine.process(event)
        self._publish_if_changed()
        return outcome

    def flush(self) -> None:
        """Vacía lo retenido y publica el estado final del partido."""
        self._engine.flush()
        self._publish_if_changed()

    def _publish_if_changed(self) -> None:
        count = self._engine.state.event_count
        if count == self._last_published_count:
            return
        self._publisher.publish(self._engine.state)
        self._last_published_count = count
