"""Publicación de los flujos hacia el broker, con reintento y registro (HU-10).

Saca los eventos de la memoria del proceso y los pone en el topic que les
corresponde, que es lo que da a la capa de ingestión tráfico real que consumir.

El reintento usa espera creciente con jitter, y agotados los intentos el
publicador se detiene con error en vez de descartar el evento en silencio. El
porqué de ambas decisiones: ver `docs/decisiones-de-diseno.md`, sección 4.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from gcperros.core.contracts import MatchEvent, OddsUpdate
from gcperros.publishing.transport import Transport, TransportError

logger = logging.getLogger(__name__)

#: Nombres de los topics. Son los del contrato de datos y los mismos que
#: declara la infraestructura en `infra/terraform`.
MATCH_EVENTS_TOPIC = "match-events"
ODDS_UPDATES_TOPIC = "odds-updates"

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_INITIAL_BACKOFF_S = 0.5
DEFAULT_MAX_BACKOFF_S = 30.0
DEFAULT_BACKOFF_MULTIPLIER = 2.0


class PublishError(RuntimeError):
    """Un evento no pudo publicarse tras agotar todos los intentos."""


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Cuántas veces reintentar y cuánto esperar entre intentos."""

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    initial_backoff_s: float = DEFAULT_INITIAL_BACKOFF_S
    max_backoff_s: float = DEFAULT_MAX_BACKOFF_S
    multiplier: float = DEFAULT_BACKOFF_MULTIPLIER

    def __post_init__(self) -> None:
        """Valida la política.

        Raises:
            ValueError: Si los parámetros no describen una espera creciente.
        """
        if self.max_attempts < 1:
            raise ValueError("hacen falta al menos un intento")
        if self.initial_backoff_s < 0 or self.max_backoff_s < 0:
            raise ValueError("las esperas no pueden ser negativas")
        if self.multiplier < 1:
            raise ValueError("el multiplicador debe hacer crecer la espera")

    def backoff_for(self, attempt: int) -> float:
        """Espera base antes del intento número ``attempt``, empezando en 1."""
        growth = self.initial_backoff_s * self.multiplier ** (attempt - 1)
        return min(growth, self.max_backoff_s)


@dataclass(slots=True)
class PublishStats:
    """Qué se publicó y cuánto costó."""

    published: int = 0
    retries: int = 0
    failed: int = 0
    by_topic: dict[str, int] = field(default_factory=dict)

    @property
    def retry_rate(self) -> float:
        """Reintentos por mensaje publicado."""
        return self.retries / self.published if self.published else 0.0


class StreamPublisher:
    """Publica eventos en su topic, reintentando los fallos transitorios."""

    __slots__ = ("_policy", "_sleep", "_stats", "_transport")

    def __init__(
        self,
        transport: Transport,
        policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        """Crea el publicador.

        Args:
            transport: A dónde se entregan los mensajes.
            policy: Política de reintento.
            sleep: Función de espera. Se inyecta para que las pruebas no tarden
                lo que tardaría el backoff de verdad.
        """
        self._transport = transport
        self._policy = policy or RetryPolicy()
        self._sleep = sleep or time.sleep
        self._stats = PublishStats()

    @property
    def stats(self) -> PublishStats:
        """Contadores de la sesión de publicación."""
        return self._stats

    def publish_match_events(self, events: list[MatchEvent]) -> None:
        """Publica el flujo del partido en ``match-events``."""
        for event in events:
            self._publish(
                MATCH_EVENTS_TOPIC,
                event.to_json().encode("utf-8"),
                {
                    "event_type": event.event_type,
                    "match_id": event.match_id,
                    "team": event.team,
                },
            )

    def publish_odds_updates(self, updates: list[OddsUpdate]) -> None:
        """Publica el flujo de cuotas en ``odds-updates``."""
        for update in updates:
            self._publish(
                ODDS_UPDATES_TOPIC,
                update.to_json().encode("utf-8"),
                {
                    "match_id": update.match_id,
                    "operator": update.operator,
                    "market": update.market,
                },
            )

    def _publish(self, topic: str, payload: bytes, attributes: dict[str, str]) -> None:
        """Entrega un mensaje, reintentando mientras queden intentos.

        Raises:
            PublishError: Si se agotaron los intentos sin conseguirlo.
        """
        last_error: TransportError | None = None

        for attempt in range(1, self._policy.max_attempts + 1):
            try:
                self._transport.publish(topic, payload, attributes)
            except TransportError as error:
                last_error = error
                self._stats.retries += 1

                if attempt == self._policy.max_attempts:
                    break

                delay = self._policy.backoff_for(attempt)
                # El jitter evita que todos los reintentos caigan a la vez y
                # reproduzcan el pico que provocó el fallo.
                wait = random.uniform(delay / 2, delay)
                logger.warning(
                    "fallo al publicar en %s (intento %d de %d): %s. Reintento en %.2fs",
                    topic,
                    attempt,
                    self._policy.max_attempts,
                    error,
                    wait,
                )
                self._sleep(wait)
                continue
            else:
                self._stats.published += 1
                self._stats.by_topic[topic] = self._stats.by_topic.get(topic, 0) + 1
                return

        self._stats.failed += 1
        logger.error(
            "descartada la publicación en %s tras %d intentos: %s",
            topic,
            self._policy.max_attempts,
            last_error,
        )
        raise PublishError(
            f"no se pudo publicar en {topic} tras {self._policy.max_attempts} intentos"
        ) from last_error

    def close(self) -> None:
        """Cierra el transporte subyacente."""
        self._transport.close()
