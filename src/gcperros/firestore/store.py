"""Destino donde se persiste el documento de estado vivo (HU-15).

El publicador escribe en un ``DocumentStore``, no en Firestore directamente,
por la misma razón que ``RawSink`` es un protocolo en
``gcperros.loading.sink``: la prueba necesita poder comprobar exactamente qué
se escribió y cuándo, sin depender de un proyecto de GCP ni de un emulador.
"""

from __future__ import annotations

from typing import Protocol

from gcperros.core.contracts import JsonValue


class DocumentStoreError(RuntimeError):
    """Fallo al escribir el documento de un partido."""


class DocumentStore(Protocol):
    """Lo mínimo que el publicador necesita de un destino de documentos."""

    def set(self, document_id: str, document: dict[str, JsonValue]) -> None:
        """Sobrescribe el documento con el identificador dado.

        Es una sobrescritura completa (``set``, no ``update``): el publicador
        siempre envía el documento entero recién proyectado, así que no hay
        nada parcial que fusionar, y una sobrescritura completa es más simple
        de razonar —el documento nunca arrastra un campo de una versión
        anterior que la versión actual ya no calcula.

        Raises:
            DocumentStoreError: Si la escritura falló.
        """
        ...

    def close(self) -> None:
        """Libera los recursos del cliente."""
        ...


class InMemoryDocumentStore:
    """Destino de mentira que guarda los documentos en un diccionario.

    Sirve para probar el publicador sin Firestore. Al ser un ``dict`` por
    identificador, cada ``set`` sobre el mismo ``document_id`` reemplaza al
    anterior — igual que Firestore con un documento real.
    """

    __slots__ = ("_closed", "_fail_times", "_failures_left", "documents", "writes")

    def __init__(self, fail_times: int = 0) -> None:
        """Crea el destino.

        Args:
            fail_times: Cuántas escrituras consecutivas deben fallar antes de
                que empiece a aceptar. Permite ejercitar el camino en el que
                el publicador no logra escribir.
        """
        self.documents: dict[str, dict[str, JsonValue]] = {}
        #: Historial completo de escrituras, en orden. A diferencia de
        #: ``documents`` (que sólo guarda la última versión de cada partido,
        #: como haría Firestore), esto permite comprobar en una prueba
        #: *cuántas veces* se escribió, no sólo el resultado final.
        self.writes: list[tuple[str, dict[str, JsonValue]]] = []
        self._fail_times = fail_times
        self._failures_left = fail_times
        self._closed = False

    @property
    def closed(self) -> bool:
        """Indica si ya se cerró."""
        return self._closed

    def set(self, document_id: str, document: dict[str, JsonValue]) -> None:
        """Guarda el documento, fallando las primeras veces si así se configuró."""
        if self._failures_left > 0:
            self._failures_left -= 1
            raise DocumentStoreError(f"fallo simulado ({self._failures_left} restantes)")

        self.documents[document_id] = document
        self.writes.append((document_id, document))

    def close(self) -> None:
        """Marca el destino como cerrado."""
        self._closed = True
