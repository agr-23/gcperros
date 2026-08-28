"""Adaptador real hacia Firestore.

Deliberadamente delgado, por el mismo motivo que los demás adaptadores reales
del proyecto: traduce la llamada y convierte cualquier fallo del cliente en
``DocumentStoreError``, que es lo único que el publicador sabe interpretar. La
librería cliente es una dependencia opcional y se importa de forma diferida.
"""

from __future__ import annotations

from gcperros.core.contracts import JsonValue
from gcperros.firestore.publisher import LIVE_MATCHES_COLLECTION
from gcperros.firestore.store import DocumentStoreError


class FirestoreDocumentStore:
    """Escribe el documento de un partido en una colección de Firestore."""

    __slots__ = ("_client", "_collection")

    def __init__(
        self,
        project_id: str,
        collection: str = LIVE_MATCHES_COLLECTION,
        database: str = "(default)",
    ) -> None:
        """Crea el cliente de Firestore.

        Args:
            project_id: Proyecto de GCP donde vive la base de datos.
            collection: Colección donde vive un documento por partido.
                Coincide por defecto con la que ya usa ``LiveStatePublisher``,
                para que nadie tenga que repetir el nombre al conectar los
                dos extremos.
            database: Base de datos Firestore dentro del proyecto. GCP
                permite crear varias bases con nombre propio en un mismo
                proyecto, pero este despliegue usa una sola, la que
                ``infra/terraform/firestore.tf`` declara como la
                predeterminada (``(default)``); el parámetro existe para no
                tener que tocar el código el día que eso cambie.

        Raises:
            RuntimeError: Si falta la librería cliente.
        """
        try:
            from google.cloud import firestore
        except ImportError as error:  # pragma: no cover - depende del entorno
            raise RuntimeError(
                "falta google-cloud-firestore. Instálalo con: pip install -e '.[firestore]'"
            ) from error

        self._client = firestore.Client(project=project_id, database=database)
        self._collection = collection

    def set(self, document_id: str, document: dict[str, JsonValue]) -> None:
        """Sobrescribe el documento del partido.

        Es un ``set`` sin ``merge``: cada escritura reemplaza el documento
        entero por el que acaba de proyectar el publicador, igual que exige
        el protocolo ``DocumentStore``.

        Raises:
            DocumentStoreError: Si Firestore rechazó la escritura.
        """
        try:
            self._client.collection(self._collection).document(document_id).set(document)
        except Exception as error:
            raise DocumentStoreError(f"Firestore rechazó la escritura: {error}") from error

    def close(self) -> None:
        """Cierra el cliente."""
        self._client.close()
