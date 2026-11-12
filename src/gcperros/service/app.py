"""El motor detrás de una URL: lo que Cloud Run despliega (decisiones, sección 6).

Pub/Sub entrega cada mensaje por push a ``/pubsub/push``: un sobre JSON con el
mensaje en base64 y la suscripción de la que sale, de la que se deduce el flujo.
Hay un motor por partido, y cada entrega que cambia el estado reescribe su
documento vivo en Firestore. Se contesta 204 a lo decidido —también a lo que
incumple el contrato, que no mejora reintentándolo—, 400 a un sobre inválido y
500 si Firestore falló, para que Pub/Sub reintente.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from datetime import datetime

from fastapi import FastAPI, HTTPException, Response

from gcperros.core.contracts import JsonValue, MatchEvent
from gcperros.engine.basketball_state import basketball_engine
from gcperros.engine.pipeline import MatchEngine, StreamEngine
from gcperros.firestore.document import LiveMatchDocument
from gcperros.firestore.store import DocumentStore, DocumentStoreError
from gcperros.governance.gate import (
    IngestionGate,
    basketball_event_gate,
    basketball_odds_gate,
    match_event_gate,
    odds_update_gate,
)
from gcperros.governance.quarantine import InMemoryInvalidStore, InvalidEventStore, utc_now

#: Cómo se aplica cada flujo de eventos: el estado de su deporte.
ENGINES: dict[str, Callable[[], StreamEngine[object]]] = {
    "match-events": MatchEngine,
    "basketball-events": basketball_engine,
}

#: Los flujos de cuotas: se juzgan en la frontera y se confirman.
ODDS_STREAMS = ("odds-updates", "basketball-odds")

#: Sufijo de la suscripción push de cada flujo (``locals.tf``).
ENGINE_SUBSCRIPTION_SUFFIX = "-engine"


def stream_of(subscription: str) -> str:
    """El flujo de ``projects/<p>/subscriptions/<prefijo><flujo>-engine``; ``ValueError`` si no."""
    name = subscription.rsplit("/", 1)[-1]
    if name.endswith(ENGINE_SUBSCRIPTION_SUFFIX):
        name = name.removesuffix(ENGINE_SUBSCRIPTION_SUFFIX)
        for stream in (*ENGINES, *ODDS_STREAMS):
            if name == stream or name.endswith(f"-{stream}"):
                return stream
    raise ValueError(f"{subscription!r} no es la suscripción del motor de ningún flujo")


def _payload(envelope: dict[str, object]) -> tuple[str, str]:
    """El flujo y el mensaje en claro de un sobre push."""
    message = envelope.get("message")
    subscription = envelope.get("subscription")
    if not isinstance(message, dict) or not isinstance(subscription, str):
        raise ValueError("el sobre no trae «message» y «subscription»")
    data = message.get("data")
    if not isinstance(data, str):
        raise ValueError("el mensaje no trae «data»")
    try:
        text = base64.b64decode(data, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as error:
        raise ValueError("«data» no es base64 de texto UTF-8") from error
    return stream_of(subscription), text


class EngineService:
    """Un motor por partido y una frontera por flujo, detrás del endpoint push."""

    __slots__ = ("_clock", "_dirty", "_engines", "_gates", "_odds", "_store")

    def __init__(
        self,
        store: DocumentStore,
        invalid: InvalidEventStore | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Crea el servicio vacío: los partidos aparecen con su primer evento."""
        quarantine = invalid if invalid is not None else InMemoryInvalidStore()
        self._store = store
        self._clock = clock
        self._engines: dict[str, StreamEngine[object]] = {}
        # Partidos cuyo documento no se pudo escribir: el reintento de Pub/Sub
        # es una repetición que el motor descarta, así que hay que recordarlos.
        self._dirty: set[str] = set()
        self._gates: dict[str, IngestionGate[MatchEvent]] = {
            "match-events": match_event_gate(quarantine, clock),
            "basketball-events": basketball_event_gate(quarantine, clock),
        }
        self._odds = {
            "odds-updates": odds_update_gate(quarantine, clock),
            "basketball-odds": basketball_odds_gate(quarantine, clock),
        }

    def matches(self) -> tuple[str, ...]:
        """Los partidos que el servicio está siguiendo."""
        return tuple(self._engines)

    def receive(self, stream: str, message: str) -> None:
        """Juzga una entrega, la aplica a su partido y reescribe su documento."""
        if stream in self._odds:
            self._odds[stream].admit(message)
            return
        event = self._gates[stream].admit(message)
        if event is None:
            return  # rechazado por la frontera: ya está archivado con su causa
        engine = self._engines.setdefault(event.match_id, ENGINES[stream]())
        before = engine.state.event_count
        engine.process(event, arrived_at=self._clock())
        if engine.state.event_count != before or event.match_id in self._dirty:
            self._publish(event.match_id, engine)

    def _publish(self, match_id: str, engine: StreamEngine[object]) -> None:
        document = LiveMatchDocument.project_state(match_id, engine.state, updated_at=self._clock())
        try:
            self._store.set(match_id, document.to_firestore_document())
        except DocumentStoreError:
            self._dirty.add(match_id)
            raise
        self._dirty.discard(match_id)


def create_service(service: EngineService) -> FastAPI:
    """La aplicación que sirve Cloud Run."""
    app = FastAPI(title="GCPerros · motor")

    @app.get("/healthz", response_model=None)
    def health() -> dict[str, JsonValue]:
        return {"status": "ok", "matches": len(service.matches())}

    @app.post("/pubsub/push", status_code=204)
    def push(envelope: dict[str, object]) -> Response:
        try:
            stream, message = _payload(envelope)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        try:
            service.receive(stream, message)
        except DocumentStoreError as error:
            raise HTTPException(
                status_code=500, detail="Firestore no aceptó el documento"
            ) from error
        return Response(status_code=204)

    return app
