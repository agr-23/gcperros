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
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from gcperros.core.contracts import JsonValue
from gcperros.demo.market import MarketTape
from gcperros.demo.replay import Replay
from gcperros.demo.signal_trace import SignalTrace, trace_signal
from gcperros.demo.snapshot import LiveSnapshot, take_snapshot
from gcperros.demo.trace import Trace, trace_indicator

#: Minutos de partido por minuto real. A 30, el partido entero dura unos tres
#: minutos y medio con el descanso: bastante para seguirlo, poco para aburrir.
DEFAULT_SPEED = 30.0

#: Cada cuánto tiempo de partido se guarda un punto de la historia (#96): un
#: minuto, la misma resolución con la que la página dibuja sus gráficas.
HISTORY_STEP_S = 60.0

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

    __slots__ = ("_clock", "_history", "_market", "_replay", "_sampled_s", "_speed", "_started")

    def __init__(
        self,
        replay: Replay[object],
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
        # Un punto por minuto de partido, para que quien llega tarde vea las
        # gráficas desde el principio y no desde que abrió la página (#96).
        self._history: list[dict[str, JsonValue]] = []
        self._sampled_s = 0.0

    @property
    def match_id(self) -> str:
        """El partido que sirve esta fuente."""
        return self._replay.match_id

    @property
    def sport(self) -> str:
        """El deporte del partido, para el selector de la página (#92)."""
        return self._replay.sport

    def current(self) -> LiveSnapshot:
        """El estado del partido ahora mismo, según cuánto tiempo real pasó."""
        now = self._clock()
        if self._started is None:
            self._started = now
        target = (now - self._started) * self._speed
        # Se avanza minuto a minuto hasta ahora, guardando cada uno: un salto
        # de media parte deja igualmente su historia.
        while self._sampled_s + HISTORY_STEP_S <= min(target, self._replay.duration_s):
            self._sampled_s += HISTORY_STEP_S
            self._advance(self._sampled_s)
            self._history.append(_history_point(self._snapshot()))
        self._advance(target)
        return self._snapshot()

    def _advance(self, elapsed_s: float) -> None:
        self._replay.advance_to(elapsed_s)
        if self._market is not None:
            self._market.advance_to(self._replay.now)

    def _snapshot(self) -> LiveSnapshot:
        if self._market is None:
            return take_snapshot(self._replay)
        return take_snapshot(self._replay, self._market.view())

    def history(self) -> list[dict[str, JsonValue]]:
        """Lo que ya pasó, un punto por minuto: indicadores y, si hay, el mercado."""
        return list(self._history)

    def trace(self, indicator: str, scope: str) -> Trace:
        """De dónde sale un indicador en el estado que la página ya está viendo.

        No avanza el reloj: explica el número que se pulsó, no uno posterior.
        """
        return trace_indicator(self._replay, indicator, scope)

    def trace_signal(self, index: int) -> SignalTrace:
        """De dónde sale una señal del feed; ``IndexError`` si no hay mercado o aún no salió."""
        if self._market is None:
            raise IndexError("esta demostración no lleva mercado")
        return trace_signal(self._market, index, self._replay.minute_at)


def _history_point(snapshot: LiveSnapshot) -> dict[str, JsonValue]:
    """Lo que las gráficas necesitan de un instante, y nada más."""
    payload = snapshot.to_json()
    point: dict[str, JsonValue] = {
        "minute": snapshot.clock.minute,
        "indicators": payload["indicators"],
    }
    if snapshot.market is not None:
        point["model"] = dict(snapshot.market.model)
        point["operators"] = {op: dict(book) for op, book in snapshot.market.operators.items()}
    return point


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
    source: LiveSource | Sequence[LiveSource],
    poll_s: float = DEFAULT_POLL_S,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    reports_dir: Path | None = None,
) -> FastAPI:
    """Construye la aplicación sobre una o varias fuentes de estado vivo.

    Con varias, una por deporte, la página ofrece un selector (#92); la primera
    es la que abre por defecto.

    ``sleep`` se inyecta para que las pruebas recorran un partido entero sin
    esperar a que pase de verdad. ``reports_dir`` es la carpeta de la que se
    leen los informes; sin ella, la demo funciona igual y los informes constan
    como no generados.
    """
    app = FastAPI(title="GCPerros · demostración", docs_url="/api/docs", redoc_url=None)
    sources = [source] if isinstance(source, LiveSource) else list(source)
    by_id = {live.match_id: live for live in sources}

    def _source(match_id: str) -> LiveSource:
        live = by_id.get(match_id)
        if live is None:
            raise HTTPException(status_code=404, detail=f"no hay partido {match_id}")
        return live

    @app.get("/api/matches")
    def matches() -> list[str]:
        """Los partidos disponibles, el de por defecto primero."""
        return [live.match_id for live in sources]

    @app.get("/api/sports")
    def sports() -> list[dict[str, str]]:
        """Qué deporte es cada partido, para el selector de la página."""
        return [{"match_id": live.match_id, "sport": live.sport} for live in sources]

    # Sin modelo de respuesta: el documento ya cumple su propio contrato, y
    # pydantic no sabe derivar un esquema del tipo recursivo `JsonValue`.
    @app.get("/api/matches/{match_id}/state", response_model=None)
    def state(match_id: str) -> dict[str, JsonValue]:
        """El estado vivo del partido, con la forma del documento de Firestore."""
        return _source(match_id).current().to_json()

    @app.get("/api/matches/{match_id}/stream")
    def stream(match_id: str) -> StreamingResponse:
        """El estado en vivo, empujado al navegador por Server-Sent Events."""
        return StreamingResponse(
            stream_snapshots(_source(match_id), poll_s, sleep),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/api/matches/{match_id}/history", response_model=None)
    def history(match_id: str) -> list[JsonValue]:
        """Un punto por minuto de lo ya jugado, para dibujar las gráficas enteras (#96)."""
        return list(_source(match_id).history())

    @app.get("/api/matches/{match_id}/trace/{indicator}/{scope}", response_model=None)
    def trace(match_id: str, indicator: str, scope: str) -> dict[str, JsonValue]:
        """Los eventos que formaron un número del marcador, con su huella verificada."""
        live = _source(match_id)
        try:
            return live.trace(indicator, scope).to_json()
        except (KeyError, AttributeError) as error:
            raise HTTPException(
                status_code=404, detail=f"no se mide {indicator} en {scope}"
            ) from error

    @app.get("/api/matches/{match_id}/signals/{index}/trace", response_model=None)
    def signal_trace(match_id: str, index: int) -> dict[str, JsonValue]:
        """Los eventos y la cuota que produjeron una señal, con su huella verificada."""
        live = _source(match_id)
        try:
            return live.trace_signal(index).to_json()
        except IndexError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

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
