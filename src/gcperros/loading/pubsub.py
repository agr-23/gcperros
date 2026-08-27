"""Adaptador real hacia una suscripción pull de Google Cloud Pub/Sub.

Deliberadamente delgado, por el mismo motivo que ``publishing/pubsub.py``:
traduce la llamada y convierte cualquier fallo del cliente en
``SubscriptionError``, que es lo único que el cargador sabe interpretar (no
confirmar y volver a intentarlo en el siguiente sondeo). Toda la lógica que sí
se puede probar vive en ``raw_loader.py``.

La librería cliente es una dependencia opcional y se importa de forma
diferida, igual que en el lado de publicación.
"""

from __future__ import annotations

from typing import Any

from gcperros.loading.subscriber import PulledMessage, SubscriptionError

#: Reexportado desde el lado de publicación: es la misma variable de entorno,
#: el mismo cliente y el mismo emulador. Dos funciones idénticas en dos
#: ficheros acabarían divergiendo si algún día cambia cómo se detecta.
from gcperros.publishing.pubsub import using_emulator

__all__ = ["PubSubPullSubscriber", "using_emulator"]


class PubSubPullSubscriber:
    """Extrae y confirma mensajes de una suscripción pull real."""

    __slots__ = ("_client", "_subscription_path", "_timeout")

    def __init__(self, project_id: str, subscription: str, timeout_s: float = 30.0) -> None:
        """Crea el cliente de suscripción.

        Args:
            project_id: Proyecto de GCP donde vive la suscripción.
            subscription: Nombre corto de la suscripción (sin la ruta
                completa), tal como la declara Terraform.
            timeout_s: Tiempo máximo de espera por llamada.

        Raises:
            RuntimeError: Si falta la librería cliente.
        """
        try:
            # Se importa el submódulo por su ruta completa (y se referencia
            # así, sin alias) en vez de `from google.cloud import pubsub_v1`:
            # con esa segunda forma, y el import diferido de `bigquery` que
            # hace `loading/bigquery.py` en el mismo paquete de espacio de
            # nombres, mypy pierde la resolución del atributo al comprobar
            # ambos ficheros en la misma pasada — una limitación conocida del
            # *stub* de `google-cloud-pubsub` con paquetes de espacio de
            # nombres, no del código. Esta forma la evita sin suprimir el
            # tipado con `type: ignore`.
            import google.cloud.pubsub_v1
        except ImportError as error:  # pragma: no cover - depende del entorno
            raise RuntimeError(
                "falta google-cloud-pubsub. Instálalo con: pip install -e '.[pubsub]'"
            ) from error

        self._timeout = timeout_s
        self._client = google.cloud.pubsub_v1.SubscriberClient()
        self._subscription_path = self._client.subscription_path(project_id, subscription)

    def pull(self, max_messages: int) -> list[PulledMessage]:
        """Extrae hasta ``max_messages`` mensajes pendientes de la suscripción.

        Se usa la RPC de extracción síncrona (``pull``) y no el flujo continuo
        (``StreamingPull``): la historia pide un consumidor mínimo, y un
        cargador que sondea por lotes es más simple de operar, probar y
        desplegar como trabajo programado que uno con una conexión de larga
        duración. El coste es más latencia entre sondeos, y es un coste que
        HU-14 acepta a propósito; ``docs/decisiones-de-diseno.md`` sección 10
        registra la alternativa descartada.

        Raises:
            SubscriptionError: Si la extracción falló.
        """
        from google.api_core import exceptions

        try:
            response: Any = self._client.pull(
                request={
                    "subscription": self._subscription_path,
                    "max_messages": max_messages,
                },
                timeout=self._timeout,
                retry=None,
            )
        except exceptions.DeadlineExceeded:
            # Sondear una suscripción sin mensajes agota el timeout: no es un
            # fallo, es la forma en la que la RPC síncrona dice «nada por
            # ahora». El cargador lo trata igual que una lista vacía.
            return []
        except Exception as error:
            raise SubscriptionError(f"Pub/Sub rechazó la extracción: {error}") from error

        return [
            PulledMessage(
                ack_id=received.ack_id,
                message_id=received.message.message_id,
                publish_time=received.message.publish_time,
                data=received.message.data,
                attributes=dict(received.message.attributes),
            )
            for received in response.received_messages
        ]

    def ack(self, ack_ids: list[str]) -> None:
        """Confirma los mensajes indicados.

        Raises:
            SubscriptionError: Si la confirmación falló.
        """
        if not ack_ids:
            return
        try:
            self._client.acknowledge(
                request={"subscription": self._subscription_path, "ack_ids": ack_ids},
                timeout=self._timeout,
            )
        except Exception as error:
            raise SubscriptionError(f"Pub/Sub rechazó la confirmación: {error}") from error

    def close(self) -> None:
        """Cierra el cliente y su canal subyacente."""
        self._client.close()
