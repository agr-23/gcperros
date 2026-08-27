"""El cargador de la capa Raw (HU-14): extrae, persiste y confirma.

El recorrido de un mensaje es deliberadamente corto, y el orden importa:

1. **Extraer** un lote de la suscripción pull.
2. **Persistir** el lote, sin transformarlo, en la tabla Raw.
3. **Confirmar** ante el broker sólo si el paso anterior tuvo éxito.

Confirmar antes de escribir perdería mensajes ante cualquier fallo entre
medias: el broker daría por hecho que ya están a salvo y dejaría de
reentregarlos. Escribir y confirmar en ese orden es lo único que sostiene la
promesa de la historia —"toda la información necesaria queda persistida
íntegramente y sin pérdida"— frente a un fallo transitorio de BigQuery.

Lo que este cargador **no** hace es tan deliberado como lo que hace: no
deduplica por ``event_id``, no reordena por marca de agua, no valida contra
el contrato. Las tres son responsabilidades ya resueltas en otra capa
—``gcperros.engine`` sobre el estado vivo, ``gcperros.governance`` en la
frontera de ingestión— y repetirlas aquí no añadiría nada: al contrario,
descartar una repetición antes de guardarla convertiría la capa Raw en una
copia *filtrada* del flujo, que es exactamente lo que una capa histórica no
puede permitirse ser. Ver ``docs/decisiones-de-diseno.md``, sección 10.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from gcperros.governance.quarantine import utc_now
from gcperros.loading.sink import RawRecord, RawSink, SinkError
from gcperros.loading.subscriber import PulledMessage, PullSubscriber

logger = logging.getLogger(__name__)

DEFAULT_MAX_MESSAGES = 100
DEFAULT_IDLE_BACKOFF_S = 5.0


@dataclass(slots=True)
class LoaderStats:
    """Qué se cargó y qué se quedó sin confirmar."""

    pulled: int = 0
    loaded: int = 0
    failed: int = 0
    empty_polls: int = 0

    @property
    def success_rate(self) -> float:
        """Proporción de lo extraído que terminó persistido y confirmado."""
        return self.loaded / self.pulled if self.pulled else 1.0


class RawLoader:
    """Consume una suscripción de un flujo y persiste todo, sin transformar."""

    __slots__ = ("_clock", "_sink", "_stats", "_stream", "_subscriber")

    def __init__(
        self,
        subscriber: PullSubscriber,
        sink: RawSink,
        stream: str,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Crea el cargador de un flujo.

        Args:
            subscriber: De dónde se extraen los mensajes.
            sink: Dónde se persisten.
            stream: Nombre del flujo (``match-events`` u ``odds-updates``),
                tal como se anota en cada fila para poder auditar la tabla.
            clock: De dónde sale ``loaded_at``. Se inyecta para que las
                pruebas puedan fijarlo, igual que en el resto del proyecto.
        """
        self._subscriber = subscriber
        self._sink = sink
        self._stream = stream
        self._clock = clock
        self._stats = LoaderStats()

    @property
    def stats(self) -> LoaderStats:
        """Contadores de la sesión de carga."""
        return self._stats

    def poll(self, max_messages: int = DEFAULT_MAX_MESSAGES) -> int:
        """Ejecuta un ciclo: extrae, persiste y confirma un único lote.

        Devuelve cuántos mensajes quedaron persistidos y confirmados. Un
        fallo de escritura no se propaga: se registra, el lote queda sin
        confirmar —así que el broker volverá a entregarlo— y el método
        devuelve cero. Es la misma filosofía que el resto del proyecto aplica
        a los fallos transitorios: más ruidoso detenerse a mitad de sondeo que
        perder eventos en silencio.

        Raises:
            SubscriptionError: Si la propia extracción o confirmación falló
                (no la escritura). Es un fallo del transporte, no de los
                datos, y no hay nada razonable que el cargador pueda hacer con
                él salvo dejar que quien lo invoque decida.
        """
        messages = self._subscriber.pull(max_messages)
        if not messages:
            self._stats.empty_polls += 1
            return 0

        self._stats.pulled += len(messages)
        records = [self._to_record(message) for message in messages]

        try:
            self._sink.write(records)
        except SinkError:
            logger.exception(
                "no se pudo persistir un lote de %d mensajes del flujo %s; "
                "queda sin confirmar y Pub/Sub lo reentregará",
                len(records),
                self._stream,
            )
            self._stats.failed += len(records)
            return 0

        self._subscriber.ack([message.ack_id for message in messages])
        self._stats.loaded += len(records)
        logger.info("persistidos %d mensajes del flujo %s", len(records), self._stream)
        return len(records)

    def drain(
        self,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        empty_polls_before_stop: int = 1,
    ) -> LoaderStats:
        """Agota lo disponible ahora mismo y se detiene.

        Es el modo del trabajo programado: se invoca, procesa lo que
        encuentra y termina. ``empty_polls_before_stop`` existe para el modo
        de ensayo y las pruebas, donde un sondeo vacío es indistinguible de
        «todavía no llegó» y de «no va a llegar más»; en producción, uno solo
        basta.
        """
        empty_streak = 0
        while empty_streak < empty_polls_before_stop:
            loaded = self.poll(max_messages)
            empty_streak = 0 if loaded else empty_streak + 1
        return self._stats

    def run_forever(
        self,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        idle_backoff_s: float = DEFAULT_IDLE_BACKOFF_S,
        sleep: Callable[[float], None] = time.sleep,
        stop: Callable[[], bool] | None = None,
    ) -> None:
        """Sondea sin parar: para un servicio de larga duración.

        Cuando un sondeo no encuentra nada, espera ``idle_backoff_s`` antes
        del siguiente en vez de reintentar de inmediato: sondear sin pausa una
        suscripción al día sólo gastaría cuota sin ganar nada, porque un
        mensaje nuevo no llega más rápido por preguntar más seguido.

        Args:
            max_messages: Mensajes por lote de extracción.
            idle_backoff_s: Espera, en segundos, tras un sondeo vacío.
            sleep: Función de espera. Se inyecta para que las pruebas no
                tarden lo que tardaría la espera real.
            stop: Condición de parada, comprobada entre sondeos. Se inyecta
                para que las pruebas puedan acotar el bucle; en producción se
                deja en blanco y el proceso corre hasta que lo maten.
        """
        should_stop = stop or (lambda: False)
        while not should_stop():
            loaded = self.poll(max_messages)
            if not loaded:
                sleep(idle_backoff_s)

    def close(self) -> None:
        """Cierra la suscripción y el destino."""
        self._subscriber.close()
        self._sink.close()

    def _to_record(self, message: PulledMessage) -> RawRecord:
        # Se decodifica con reemplazo y no de forma estricta, igual que en la
        # frontera de ingestión (`governance/gate.py`): un mensaje que ni
        # siquiera es UTF-8 también hay que poder archivarlo, y una capa Raw
        # que se cae ante la basura peor formada es la que menos sirve.
        payload = message.data.decode("utf-8", errors="replace")
        return RawRecord(
            stream=self._stream,
            message_id=message.message_id,
            publish_time=message.publish_time,
            payload=payload,
            attributes=dict(message.attributes),
            loaded_at=self._clock(),
        )


__all__ = ["DEFAULT_IDLE_BACKOFF_S", "DEFAULT_MAX_MESSAGES", "LoaderStats", "RawLoader"]
