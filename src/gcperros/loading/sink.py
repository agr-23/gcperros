"""Destino donde se persiste la capa Raw, y la forma exacta de un registro (HU-14).

El cargador escribe en un ``RawSink``, no en BigQuery directamente, por la
misma razón que ``InvalidEventStore`` es un protocolo en
``gcperros.governance``: el destino real no debe decidir cómo se prueba el
cargador.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from gcperros.core.contracts import JsonValue, format_event_time


class SinkError(RuntimeError):
    """Fallo al persistir un lote en la capa Raw.

    Es *el* fallo que hace que el cargador no confirme el lote: mejor dejar
    que Pub/Sub vuelva a entregarlo que arriesgarse a perder eventos porque la
    escritura en BigQuery no se pudo completar.
    """


@dataclass(frozen=True, slots=True)
class RawRecord:
    """Un mensaje persistido sin transformar, tal como llegó del broker.

    Es deliberadamente un espejo casi literal de ``PulledMessage``: la
    historia pide guardar el evento **crudo**, y la única libertad que se toma
    este registro es decodificar la carga útil a texto y anotar cuándo se
    cargó. No se interpreta ``attrs``, no se valida contra el contrato, no se
    deduplica por ``event_id`` —eso es trabajo del motor sobre el estado vivo,
    no de la capa histórica—.

    Attributes:
        stream: Flujo de origen (``match-events`` u ``odds-updates``), para
            poder auditar la tabla sin tener que abrir la carga útil.
        message_id: Identificador que Pub/Sub asignó al mensaje. Estable entre
            entregas: permite reconocer en la tabla que dos filas vinieron del
            mismo mensaje, aunque el broker lo haya entregado más de una vez.
        publish_time: Cuándo se publicó, según el broker.
        payload: Carga útil cruda, tal como la escribió el productor. Es
            deliberadamente una cadena y no un objeto ya interpretado: la capa
            Raw promete reproducir el mensaje, no una lectura de él.
        attributes: Atributos del mensaje, sin interpretar.
        loaded_at: Cuándo lo persistió el cargador. Es la marca de tiempo de
            ingestión, y es en la que se particiona la tabla: a diferencia de
            ``event_time`` o ``publish_time``, nunca varía con reprocesos ni
            con relojes de otros sistemas.
    """

    stream: str
    message_id: str
    publish_time: datetime
    payload: str
    attributes: dict[str, str]
    loaded_at: datetime

    def to_bigquery_row(self) -> dict[str, JsonValue]:
        """Proyecta el registro a la fila que espera la tabla Raw.

        Los atributos se serializan como JSON en vez de como un campo
        repetido: la tabla Raw no necesita filtrar por ellos —para eso están
        los atributos del mensaje mientras vive en el topic—, y una cadena es
        más simple de declarar y de leer sin perder ninguno.
        """
        return {
            "message_id": self.message_id,
            "publish_time": format_event_time(self.publish_time),
            "stream": self.stream,
            "payload": self.payload,
            "attributes": (
                json.dumps(self.attributes, sort_keys=True, separators=(",", ":"))
                if self.attributes
                else None
            ),
            "loaded_at": format_event_time(self.loaded_at),
        }


class RawSink(Protocol):
    """Lo mínimo que el cargador necesita de un destino de persistencia."""

    def write(self, records: list[RawRecord]) -> None:
        """Persiste un lote de registros.

        Se recibe el lote completo y no registro a registro: es lo que
        permite que el adaptador real haga una sola inserción por sondeo en
        vez de una llamada por mensaje.

        Raises:
            SinkError: Si la escritura falló. El cargador no confirmará el
                lote ante el broker cuando esto ocurra.
        """
        ...

    def close(self) -> None:
        """Libera los recursos del cliente."""
        ...


class InMemoryRawSink:
    """Destino de mentira que guarda los registros en una lista.

    Sirve para dos cosas: probar el cargador sin BigQuery, y ofrecer el modo
    de ensayo de la línea de comandos que recorre todo el camino sin GCP.
    """

    __slots__ = ("_closed", "_fail_times", "_failures_left", "records")

    def __init__(self, fail_times: int = 0) -> None:
        """Crea el destino.

        Args:
            fail_times: Cuántas escrituras consecutivas deben fallar antes de
                que empiece a aceptar. Permite ejercitar el camino en el que
                el cargador no confirma el lote.
        """
        self.records: list[RawRecord] = []
        self._fail_times = fail_times
        self._failures_left = fail_times
        self._closed = False

    @property
    def closed(self) -> bool:
        """Indica si ya se cerró."""
        return self._closed

    def write(self, records: list[RawRecord]) -> None:
        """Guarda el lote, fallando las primeras veces si así se configuró."""
        if self._failures_left > 0:
            self._failures_left -= 1
            raise SinkError(f"fallo simulado ({self._failures_left} restantes)")

        self.records.extend(records)

    def reset_failures(self) -> None:
        """Vuelve a armar los fallos, para el siguiente lote."""
        self._failures_left = self._fail_times

    def close(self) -> None:
        """Marca el destino como cerrado."""
        self._closed = True
