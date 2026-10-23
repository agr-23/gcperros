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
from gcperros.demo.market import MarketTape
from gcperros.demo.replay import MatchReplay
from gcperros.demo.snapshot import LiveSnapshot, take_snapshot
from gcperros.demo.trace import Trace, trace_indicator

#: Minutos de partido por minuto real. A 30, el partido entero dura unos tres
#: minutos y medio con el descanso: bastante para seguirlo, poco para aburrir.
DEFAULT_SPEED = 30.0

#: Segundos reales entre dos envíos del canal en vivo. A velocidad 30 son
#: quince segundos de partido: la página se mueve sin saturar al navegador.
DEFAULT_POLL_S = 0.5

#: La página de la demostración. Va dentro del paquete para que la instale pip.
STATIC_DIR = Path(__file__).parent / "static"

#: Informes que la pantalla «Por qué confiar» sabe leer, y el fichero de cada
#: uno. Son los que escriben las CLI con ``--report``. Lista cerrada a propósito:
#: el nombre que llega en la URL nunca se convierte en ruta, así que no hay forma
#: de pedir un fichero fuera de la carpeta.
REPORTS = {
    "validacion": "validacion.json",
    "carga": "carga.json",
    "calidad": "calidad.json",
}


class LiveSource:
    """Lleva la repetición al segundo de partido que toca según el reloj de pared."""

    __slots__ = ("_clock", "_market", "_replay", "_speed", "_started")

    def __init__(
        self,
        replay: MatchReplay,
        speed: float = DEFAULT_SPEED,
        clock: Callable[[], float] = time.monotonic,
        market: MarketTape | None = None,
    ) -> None:
        """Deja el partido listo para empezar con la primera consulta.

        Con ``market``, las cuotas y las señales avanzan al mismo reloj.

        Raises:
            ValueError: Si la velocidad no es positiva.
        """
        if speed <= 0.0:
            raise ValueError("la velocidad debe ser positiva")
        self._replay = replay
        self._speed = speed
        self._clock = clock
        self._market = market
        # El partido empieza cuando alguien lo mira, no al lanzar el servidor:
        # si no, quien tarda un minuto en abrir la página se pierde media parte.
        self._started: float | None = None

    @property
    def match_id(self) -> str:
        """El partido que sirve esta fuente."""
        return self._replay.match_id

    def current(self) -> LiveSnapshot:
        """El estado del partido ahora mismo, según cuánto tiempo real pasó."""
        now = self._clock()
        if self._started is None:
            self._started = now
        self._replay.advance_to((now - self._started) * self._speed)
        if self._market is None:
            return take_snapshot(self._replay)
        self._market.advance_to(self._replay.now)
        return take_snapshot(self._replay, self._market.view())

    def trace(self, indicator: str, scope: str) -> Trace:
        """De dónde sale un indicador en el estado que la página ya está viendo.

        No avanza el reloj: explica el número que se pulsó, no uno posterior.
        """
        return trace_indicator(self._replay, indicator, scope)


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
    reports_dir: Path | None = None,
) -> FastAPI:
    """Construye la aplicación sobre una fuente de estado vivo.

    ``sleep`` se inyecta para que las pruebas recorran un partido entero sin
    esperar a que pase de verdad. ``reports_dir`` es la carpeta de la que se
    leen los informes; sin ella, la demo funciona igual y los informes constan
    como no generados.
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

    @app.get("/api/matches/{match_id}/trace/{indicator}/{scope}", response_model=None)
    def trace(match_id: str, indicator: str, scope: str) -> dict[str, JsonValue]:
        """Los eventos que formaron un número del marcador, con su huella verificada."""
        if match_id != source.match_id:
            raise HTTPException(status_code=404, detail=f"no hay partido {match_id}")
        try:
            return source.trace(indicator, scope).to_json()
        except (KeyError, AttributeError) as error:
            raise HTTPException(
                status_code=404, detail=f"no se mide {indicator} en {scope}"
            ) from error

    def _report_path(name: str) -> Path | None:
        if reports_dir is None or name not in REPORTS:
            return None
        path = reports_dir / REPORTS[name]
        return path if path.is_file() else None

    @app.get("/api/reports")
    def reports() -> dict[str, bool]:
        """Qué informes hay generados, para que la página diga cuáles faltan."""
        return {name: _report_path(name) is not None for name in REPORTS}

    @app.get("/api/reports/{name}", response_model=None)
    def report(name: str) -> JsonValue:
        """Un informe tal como lo escribió su CLI, sin reinterpretarlo."""
        path = _report_path(name)
        if path is None:
            raise HTTPException(status_code=404, detail=f"no hay informe {name}")
        loaded: JsonValue = json.loads(path.read_text(encoding="utf-8"))
        return loaded

    # La página, al final: así las rutas de /api tienen prioridad sobre ella.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="page")
    return app
