"""Servidor local de la demostración: el estado vivo como API (#30).

Traduce reloj de pared a reloj de partido: a velocidad 30, un minuto real son
treinta de partido, y los noventa y tantos minutos caben en unos tres. La
repetición avanza cuando alguien pregunta, no con un temporizador: entre dos
peticiones no hay nada que calcular, y así el servidor no necesita hilos.

La respuesta es el contrato de Firestore más reloj y posesión
(``demo.snapshot``). Es lo único que el front conoce del sistema.

El canal en vivo es Server-Sent Events y no WebSocket: el estado sólo viaja
del servidor a la página, el navegador reconecta solo y no hace falta más que
HTTP. Es lo mismo que haría un listener de Firestore: empujar cada cambio.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from gcperros.core.contracts import JsonValue
from gcperros.demo.replay import MatchReplay
from gcperros.demo.snapshot import LiveSnapshot, take_snapshot

#: Minutos de partido por minuto real. A 30, el partido entero dura unos tres
#: minutos y medio con el descanso: bastante para seguirlo, poco para aburrir.
DEFAULT_SPEED = 30.0

#: Segundos reales entre dos envíos del canal en vivo. A velocidad 30 son
#: quince segundos de partido: la página se mueve sin saturar al navegador.
DEFAULT_POLL_S = 0.5

#: La página de la demostración. Va dentro del paquete para que la instale pip.
STATIC_DIR = Path(__file__).parent / "static"


class LiveSource:
    """Lleva la repetición al segundo de partido que toca según el reloj de pared."""

    __slots__ = ("_clock", "_replay", "_speed", "_started")

    def __init__(
        self,
        replay: MatchReplay,
        speed: float = DEFAULT_SPEED,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Arranca el partido en el instante en que se crea la fuente.

        Raises:
            ValueError: Si la velocidad no es positiva.
        """
        if speed <= 0.0:
            raise ValueError("la velocidad debe ser positiva")
        self._replay = replay
        self._speed = speed
        self._clock = clock
        self._started = clock()

    @property
    def match_id(self) -> str:
        """El partido que sirve esta fuente."""
        return self._replay.match_id

    def current(self) -> LiveSnapshot:
        """El estado del partido ahora mismo, según cuánto tiempo real pasó."""
        self._replay.advance_to((self._clock() - self._started) * self._speed)
        return take_snapshot(self._replay)


async def stream_snapshots(
    source: LiveSource,
    poll_s: float = DEFAULT_POLL_S,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[str]:
    """Emite el estado cada ``poll_s`` segundos, en formato SSE, hasta el pitido final.

    El último mensaje es el del partido terminado: después el canal se cierra,
    en vez de repetir para siempre un estado que ya no va a cambiar.
    """
    while True:
        snapshot = source.current()
        payload = json.dumps(snapshot.to_json(), ensure_ascii=False, sort_keys=True)
        yield f"data: {payload}\n\n"
        if snapshot.clock.phase == "final":
            return
        await sleep(poll_s)


def create_app(
    source: LiveSource,
    poll_s: float = DEFAULT_POLL_S,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> FastAPI:
    """Construye la aplicación sobre una fuente de estado vivo.

    ``sleep`` se inyecta para que las pruebas recorran un partido entero sin
    esperar a que pase de verdad.
    """
    app = FastAPI(title="GCPerros · demostración", docs_url="/api/docs", redoc_url=None)

    @app.get("/api/matches")
    def matches() -> list[str]:
        """Los partidos disponibles. En la demostración, uno."""
        return [source.match_id]

    # Sin modelo de respuesta: el documento ya cumple su propio contrato, y
    # pydantic no sabe derivar un esquema del tipo recursivo `JsonValue`.
    @app.get("/api/matches/{match_id}/state", response_model=None)
    def state(match_id: str) -> dict[str, JsonValue]:
        """El estado vivo del partido, con la forma del documento de Firestore."""
        if match_id != source.match_id:
            raise HTTPException(status_code=404, detail=f"no hay partido {match_id}")
        return source.current().to_json()

    @app.get("/api/matches/{match_id}/stream")
    def stream(match_id: str) -> StreamingResponse:
        """El estado en vivo, empujado al navegador por Server-Sent Events."""
        if match_id != source.match_id:
            raise HTTPException(status_code=404, detail=f"no hay partido {match_id}")
        return StreamingResponse(
            stream_snapshots(source, poll_s, sleep),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    # La página, al final: así las rutas de /api tienen prioridad sobre ella.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="page")
    return app
