"""Extracción de mensajes desde una suscripción pull (HU-14).

El cargador habla con un ``PullSubscriber``, no con Pub/Sub directamente. Es
la misma razón que sostiene ``Transport`` en ``gcperros.publishing``: la
historia exige que un fallo de escritura en BigQuery no confirme el mensaje
—para que el broker vuelva a entregarlo—, y eso no se puede ensayar contra un
broker real, porque no hay forma de pedirle a Pub/Sub que entregue un mensaje
concreto a voluntad. Con un extractor inyectable la prueba controla
exactamente qué llega y cuándo, y el adaptador real queda tan delgado que
apenas tiene lógica propia que pueda romperse sin que las pruebas lo vean.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class SubscriptionError(RuntimeError):
    """Fallo al extraer o confirmar mensajes de la suscripción.

    Representa un fallo *reintentable*: el cargador simplemente lo intentará
    en el siguiente sondeo. No hay reintento inmediato como en la publicación
    porque no hace falta: un mensaje no confirmado no se pierde, Pub/Sub lo
    volverá a entregar tras el ``ack_deadline`` de la suscripción.
    """


@dataclass(frozen=True, slots=True)
class PulledMessage:
    """Un mensaje tal como lo entrega la suscripción, antes de interpretarlo.

    Attributes:
        ack_id: Identificador de confirmación de *esta* entrega. No es
            estable entre reintentos: cambia si el mismo mensaje se vuelve a
            entregar, así que nunca se persiste ni se usa para deduplicar.
        message_id: Identificador que Pub/Sub asignó al mensaje al publicarlo.
            Este sí es estable entre entregas, y es lo que permite reconocer
            en la tabla Raw que dos filas vinieron del mismo mensaje.
        publish_time: Cuándo se publicó, según el broker.
        data: Carga útil cruda, exactamente como llegó.
        attributes: Atributos del mensaje (los que el publicador adjuntó para
            filtrar sin abrir la carga útil).
    """

    ack_id: str
    message_id: str
    publish_time: datetime
    data: bytes
    attributes: dict[str, str]


class PullSubscriber(Protocol):
    """Lo mínimo que el cargador necesita de una suscripción pull."""

    def pull(self, max_messages: int) -> list[PulledMessage]:
        """Extrae hasta ``max_messages`` mensajes pendientes.

        Devuelve una lista vacía si no hay nada disponible ahora mismo; no es
        un error, es el estado normal de una suscripción al día.

        Raises:
            SubscriptionError: Si la extracción falló.
        """
        ...

    def ack(self, ack_ids: list[str]) -> None:
        """Confirma que los mensajes ya se persistieron y no deben repetirse.

        Raises:
            SubscriptionError: Si la confirmación falló.
        """
        ...

    def close(self) -> None:
        """Libera los recursos del cliente."""
        ...


class InMemorySubscriber:
    """Suscripción de mentira que entrega mensajes de una cola en memoria.

    Sirve para dos cosas: probar el cargador sin broker, y ofrecer el modo de
    ensayo de la línea de comandos que recorre todo el camino sin GCP.
    """

    __slots__ = ("_closed", "_delivered", "_pending", "acked")

    def __init__(self, messages: Iterable[PulledMessage] = ()) -> None:
        """Crea la suscripción con la cola de mensajes ya disponibles.

        Args:
            messages: Mensajes que ``pull`` irá entregando, en orden.
        """
        self._pending: list[PulledMessage] = list(messages)
        self._delivered: dict[str, PulledMessage] = {}
        self.acked: list[str] = []
        self._closed = False

    @property
    def closed(self) -> bool:
        """Indica si ya se cerró."""
        return self._closed

    @property
    def pending_count(self) -> int:
        """Mensajes que todavía no se han entregado en ningún ``pull``."""
        return len(self._pending)

    def pull(self, max_messages: int) -> list[PulledMessage]:
        """Entrega los siguientes mensajes de la cola, sin repetirlos.

        Un mensaje entregado y no confirmado se considera «en vuelo»: igual
        que Pub/Sub, esta suscripción no lo vuelve a ofrecer hasta que expire
        (aquí, nunca; el doble no simula la redelivery automática porque
        ninguna prueba la necesita todavía).
        """
        batch = self._pending[:max_messages]
        self._pending = self._pending[max_messages:]
        for message in batch:
            self._delivered[message.ack_id] = message
        return batch

    def ack(self, ack_ids: list[str]) -> None:
        """Marca los mensajes como confirmados y dejan de estar «en vuelo»."""
        for ack_id in ack_ids:
            self._delivered.pop(ack_id, None)
            self.acked.append(ack_id)

    def close(self) -> None:
        """Marca la suscripción como cerrada."""
        self._closed = True
