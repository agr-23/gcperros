"""Transporte de mensajes hacia el broker.

El publicador no habla con Pub/Sub directamente: habla con un ``Transport``.
Esa indirección tiene un propósito concreto y no es arquitectura por gusto.

La historia pide **reintento y registro ante fallo de publicación**, y eso no se
puede probar contra un broker real: no hay forma de pedirle a Pub/Sub que falle
las dos primeras veces y acierte a la tercera. Con un transporte inyectable, la
prueba provoca el fallo exacto que quiere y comprueba que el publicador se
comporta. El transporte real queda como un adaptador delgado, con tan poca
lógica propia que no hay casi nada que pueda romperse sin que las pruebas lo
vean.

Además mantiene el paquete utilizable sin la librería cliente instalada: quien
solo quiera generar ficheros no necesita arrastrar ``google-cloud-pubsub``.
"""

from __future__ import annotations

from typing import Protocol


class TransportError(RuntimeError):
    """Fallo al entregar un mensaje al broker.

    Representa un fallo *reintentable*: el publicador volverá a intentarlo. Un
    fallo permanente —un topic que no existe, credenciales inválidas— también
    llega como esta excepción y acaba agotando los reintentos, que es la
    respuesta correcta: mejor detenerse ruidosamente que seguir perdiendo
    eventos en silencio.
    """


class Transport(Protocol):
    """Lo mínimo que el publicador necesita de un broker."""

    def publish(self, topic: str, payload: bytes, attributes: dict[str, str]) -> str:
        """Entrega un mensaje y devuelve el identificador asignado por el broker.

        Raises:
            TransportError: Si la entrega falló.
        """
        ...

    def close(self) -> None:
        """Libera los recursos y espera a que salga lo pendiente."""
        ...


class InMemoryTransport:
    """Transporte de mentira que guarda los mensajes en una lista.

    Sirve para dos cosas: probar el publicador sin broker, y ofrecer un modo de
    ensayo en la línea de comandos que recorre todo el camino sin publicar nada.
    """

    __slots__ = ("_closed", "_fail_times", "_failures_left", "messages")

    def __init__(self, fail_times: int = 0) -> None:
        """Crea el transporte.

        Args:
            fail_times: Cuántas entregas consecutivas deben fallar antes de que
                empiece a aceptar. Es lo que permite ejercitar el reintento.
        """
        self.messages: list[tuple[str, bytes, dict[str, str]]] = []
        self._fail_times = fail_times
        self._failures_left = fail_times
        self._closed = False

    @property
    def closed(self) -> bool:
        """Indica si ya se cerró."""
        return self._closed

    def publish(self, topic: str, payload: bytes, attributes: dict[str, str]) -> str:
        """Guarda el mensaje, fallando las primeras veces si así se configuró."""
        if self._failures_left > 0:
            self._failures_left -= 1
            raise TransportError(f"fallo simulado ({self._failures_left} restantes)")

        self.messages.append((topic, payload, attributes))
        return f"in-memory-{len(self.messages)}"

    def reset_failures(self) -> None:
        """Vuelve a armar los fallos, para el siguiente mensaje."""
        self._failures_left = self._fail_times

    def close(self) -> None:
        """Marca el transporte como cerrado."""
        self._closed = True
