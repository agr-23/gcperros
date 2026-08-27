"""Repositorio de eventos inválidos (HU-16).

Donde va a parar un mensaje que incumple el contrato, con la causa registrada.

No se confunde con el *dead letter* de Pub/Sub, y la distinción es de fondo:

- Aquí llega lo que **incumple el contrato**. Se rechaza en la frontera, antes
  de gastar cómputo, y el problema está en quien lo produjo.
- Al dead letter llega lo que es **contractualmente válido pero el motor no
  logró procesar** tras varios intentos. El problema está en el consumidor.

Causas distintas, responsables distintos, repositorios distintos. Mezclarlos
haría que arreglar un productor y arreglar un consumidor se parecieran, y no se
parecen en nada.

El mensaje se archiva **crudo, tal como llegó**. Normalizarlo antes de guardarlo
—recortar espacios, reordenar claves, rellenar lo que falta— destruiría
justamente la evidencia por la que se archiva: si el registro no reproduce lo
que el productor mandó, no sirve para demostrarle qué mandó mal.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, TextIO

from gcperros.core.contracts import JsonValue, format_event_time
from gcperros.governance.validation import ValidationResult

#: Espacio de nombres de los identificadores de rechazo. Constante, como el de
#: los eventos, para que el mismo mensaje rechazado en la misma posición del
#: mismo flujo reciba siempre el mismo identificador y dos ejecuciones se puedan
#: comparar.
_REJECTION_NAMESPACE = uuid.UUID("c4e1b7a3-9f52-5d08-b6c1-3a7e0d2f4b95")


def payload_digest(payload: str) -> str:
    """Huella del mensaje archivado.

    Permite reconocer que dos rechazos distintos traían exactamente la misma
    basura, que es la señal de un productor averiado y no de un mensaje suelto
    con mala suerte.
    """
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def new_rejection_id(stream: str, payload: str, sequence: int) -> str:
    """Deriva el identificador de un rechazo.

    Se usa UUID v5 y no ``uuid4`` por la misma razón que en el contrato: un
    identificador aleatorio haría que dos ejecuciones sobre la misma entrada
    produjeran repositorios distintos, y comparar dos corridas dejaría de tener
    sentido.
    """
    return str(uuid.uuid5(_REJECTION_NAMESPACE, f"{stream}:{payload_digest(payload)}:{sequence}"))


def utc_now() -> datetime:
    """Instante actual, en UTC.

    Es el reloj por defecto de la frontera. Se inyecta en lugar de llamarse
    directamente para que las pruebas puedan fijarlo: el proyecto prohíbe
    ``datetime.now()`` en el código de generación (regla 3 de `CONTRIBUTING.md`)
    porque rompe el determinismo, y aunque un rechazo sí ocurre en un instante
    real, un repositorio que no se pueda reproducir en una prueba tampoco se
    puede verificar.
    """
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class InvalidRecord:
    """Un mensaje apartado, con todo lo necesario para explicar por qué.

    Attributes:
        rejection_id: Identificador del rechazo.
        stream: Flujo del que salió el mensaje.
        contract_version: Versión del contrato contra la que se juzgó. Sin ella
            el registro no se puede interpretar más adelante: el mismo mensaje
            puede ser inválido bajo ``v1`` y perfectamente válido bajo ``v2``.
        rejected_at: Cuándo se apartó.
        rules: Motivos, del vocabulario cerrado de ``ViolationRule``.
        causes: Las mismas violaciones, redactadas para que las lea una persona.
        payload: El mensaje crudo, exactamente como llegó.
        digest: Huella del mensaje crudo.
    """

    rejection_id: str
    stream: str
    contract_version: str
    rejected_at: datetime
    rules: tuple[str, ...]
    causes: tuple[str, ...]
    payload: str
    digest: str

    def to_dict(self) -> dict[str, JsonValue]:
        """Proyecta el registro a la estructura que se persiste."""
        return {
            "rejection_id": self.rejection_id,
            "stream": self.stream,
            "contract_version": self.contract_version,
            "rejected_at": format_event_time(self.rejected_at),
            "rules": list(self.rules),
            "causes": list(self.causes),
            "payload": self.payload,
            "digest": self.digest,
        }

    def to_json(self) -> str:
        """Serializa el registro como una línea JSON estable."""
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )


def build_record(
    result: ValidationResult,
    payload: str,
    sequence: int,
    rejected_at: datetime,
) -> InvalidRecord:
    """Arma el registro de archivo a partir del veredicto que lo rechazó.

    Toma el flujo, la versión del contrato y las causas del propio veredicto en
    lugar de recibirlos sueltos: así no puede archivarse un rechazo atribuido a
    un contrato distinto del que lo juzgó.

    Args:
        result: Veredicto que rechazó el mensaje.
        payload: Mensaje crudo, tal como llegó.
        sequence: Posición del mensaje en la sesión de ingestión.
        rejected_at: Instante del rechazo.

    Returns:
        El registro listo para archivar.
    """
    return InvalidRecord(
        rejection_id=new_rejection_id(result.stream, payload, sequence),
        stream=result.stream,
        contract_version=result.contract_version,
        rejected_at=rejected_at,
        rules=result.rules,
        causes=result.causes,
        payload=payload,
        digest=payload_digest(payload),
    )


class InvalidEventStore(Protocol):
    """Lo mínimo que la frontera necesita de un repositorio de inválidos.

    Es un protocolo por la misma razón que ``Transport`` lo es en la capa de
    publicación: el destino real —hoy un fichero, mañana la tabla de
    cuarentena de BigQuery (HU-14)— no debe decidir cómo se prueba la frontera.
    """

    def record(self, record: InvalidRecord) -> None:
        """Archiva un mensaje rechazado."""
        ...

    def close(self) -> None:
        """Cierra el repositorio y asegura que lo escrito quedó en su sitio."""
        ...


class InMemoryInvalidStore:
    """Repositorio en memoria, para pruebas y para el modo de ensayo."""

    __slots__ = ("_closed", "records")

    def __init__(self) -> None:
        """Crea un repositorio vacío."""
        self.records: list[InvalidRecord] = []
        self._closed = False

    @property
    def closed(self) -> bool:
        """Indica si ya se cerró."""
        return self._closed

    def record(self, record: InvalidRecord) -> None:
        """Guarda el registro en la lista."""
        self.records.append(record)

    def close(self) -> None:
        """Marca el repositorio como cerrado."""
        self._closed = True


class JsonlInvalidStore:
    """Repositorio en fichero JSON Lines, una línea por rechazo.

    Se abre en modo **añadir** y nunca se reescribe: un registro archivado es
    evidencia, y la evidencia no se edita. Si dos ejecuciones apuntan al mismo
    fichero, la segunda continúa la primera en lugar de borrarla.

    El fichero se crea al primer rechazo y no al construir el repositorio: una
    ingestión limpia no debe dejar tras de sí un fichero vacío que haga dudar de
    si el mecanismo llegó a correr.
    """

    __slots__ = ("_handle", "_path")

    def __init__(self, path: Path) -> None:
        """Crea el repositorio sobre la ruta indicada.

        Args:
            path: Fichero donde se acumulan los rechazos.
        """
        self._path = path
        self._handle: TextIO | None = None

    @property
    def path(self) -> Path:
        """Ruta del fichero de rechazos."""
        return self._path

    def record(self, record: InvalidRecord) -> None:
        """Añade el registro al final del fichero."""
        handle = self._open()
        handle.write(record.to_json() + "\n")

    def close(self) -> None:
        """Cierra el fichero si llegó a abrirse."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def _open(self) -> TextIO:
        if self._handle is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # `newline=""` evita que Windows convierta el salto en CRLF: el
            # repositorio tiene que salir idéntico byte a byte en cualquier
            # sistema, igual que los ficheros de los generadores.
            self._handle = self._path.open("a", encoding="utf-8", newline="")
        return self._handle
