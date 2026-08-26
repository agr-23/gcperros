"""Adaptador real hacia Google Cloud Pub/Sub.

Deliberadamente delgado: traduce la llamada y convierte cualquier fallo del
cliente en ``TransportError``, que es lo que el publicador sabe reintentar. Toda
la lógica de reintento, espera y registro vive en ``publisher.py``, donde sí se
puede probar.

La librería cliente es una dependencia **opcional**: quien solo quiera generar
ficheros no tiene por qué instalarla. Se importa dentro del constructor para que
el resto del paquete siga funcionando sin ella.

Contra el emulador, sin nube ni tarjeta
---------------------------------------
El cliente respeta la variable ``PUBSUB_EMULATOR_HOST``. Si está definida, habla
con el emulador local en lugar de con Google, y no pide credenciales::

    gcloud components install pubsub-emulator
    gcloud beta emulators pubsub start --project=gcperros-local

    export PUBSUB_EMULATOR_HOST=localhost:8085
    gcperros-publish --seed 20260826 --project gcperros-local --create-topics

El mismo código, sin cambiar una línea, publica en el proyecto real en cuanto se
quita esa variable.
"""

from __future__ import annotations

import os
from typing import Any

from gcperros.publishing.transport import TransportError

#: Variable que desvía el cliente hacia el emulador local.
EMULATOR_ENV_VAR = "PUBSUB_EMULATOR_HOST"


def using_emulator() -> bool:
    """Indica si el cliente hablará con el emulador en vez de con Google."""
    return bool(os.environ.get(EMULATOR_ENV_VAR))


class PubSubTransport:
    """Entrega mensajes a topics reales de Pub/Sub."""

    __slots__ = ("_client", "_project_id", "_timeout")

    def __init__(self, project_id: str, timeout_s: float = 30.0) -> None:
        """Crea el cliente de publicación.

        Args:
            project_id: Proyecto de GCP donde viven los topics.
            timeout_s: Tiempo máximo de espera por mensaje.

        Raises:
            RuntimeError: Si falta la librería cliente.
        """
        try:
            from google.cloud import pubsub_v1
        except ImportError as error:  # pragma: no cover - depende del entorno
            raise RuntimeError(
                "falta google-cloud-pubsub. Instálalo con: pip install -e '.[pubsub]'"
            ) from error

        self._project_id = project_id
        self._timeout = timeout_s
        self._client = pubsub_v1.PublisherClient()

    def topic_path(self, topic: str) -> str:
        """Ruta completa del topic, tal como la espera la API."""
        path: str = self._client.topic_path(self._project_id, topic)
        return path

    def ensure_topic(self, topic: str) -> None:
        """Crea el topic si no existe.

        Sólo tiene sentido contra el emulador, que arranca vacío. En un proyecto
        real los topics los crea Terraform (HU-13) y el publicador no debería
        tener permiso para crearlos.
        """
        from google.api_core import exceptions

        try:
            self._client.create_topic(request={"name": self.topic_path(topic)})
        except exceptions.AlreadyExists:
            return

    def publish(self, topic: str, payload: bytes, attributes: dict[str, str]) -> str:
        """Publica un mensaje y espera confirmación del broker.

        Se espera el resultado en lugar de dejar el envío en vuelo: sin esperar,
        un fallo se descubriría demasiado tarde para reintentarlo, y el
        publicador no podría cumplir lo que promete.
        """
        # Se captura cualquier excepción del cliente a propósito: la librería
        # levanta una jerarquía amplia (red, autenticación, cuota) y toda ella
        # se normaliza a TransportError, que es lo único que el publicador sabe
        # reintentar.
        try:
            future: Any = self._client.publish(self.topic_path(topic), payload, **attributes)
            message_id: str = future.result(timeout=self._timeout)
        except Exception as error:
            raise TransportError(f"Pub/Sub rechazó el mensaje: {error}") from error
        return message_id

    def close(self) -> None:
        """Vacía lo pendiente y cierra el cliente."""
        self._client.stop()
