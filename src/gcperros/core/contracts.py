"""Contrato de datos del flujo ``match-events``.

Implementa el esquema fijado en la HU-1: la estructura que todos los componentes
—generador, motor, cargador de la capa Raw— acuerdan antes de escribir código,
para que nadie invente su propia interpretación de qué es un evento.

Aquí vive únicamente la *forma* del evento y su serialización. El mecanismo de
validación y aislamiento de mensajes no conformes es la HU-16 y se implementa
por separado: esto describe el contrato, no lo hace cumplir.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeAlias

CONTRACT_VERSION = "v1"

#: Valor admisible dentro de ``attrs``. El contrato acepta JSON plano.
JsonValue: TypeAlias = str | int | float | bool | list["JsonValue"] | dict[str, "JsonValue"] | None

#: Tipos de evento del flujo. El gol se emite de forma **redundante** junto al
#: tiro que lo produjo (decisión deliberada de la HU-1): el tiro conserva su xG
#: para el modelo y el gol es un hecho de negocio autónomo, que los consumidores
#: pueden contar sin tener que entender la semántica de un remate.
EventType: TypeAlias = Literal["pass", "shot", "goal", "foul", "possession_change"]

#: Espacio de nombres fijo para derivar identificadores. Al ser constante, el
#: mismo partido con la misma semilla produce los mismos `event_id`, que es lo
#: que permite comparar dos ejecuciones byte a byte.
_EVENT_NAMESPACE = uuid.UUID("2f5c8a1e-6d4b-5c3a-9e7f-1a2b3c4d5e6f")


def new_event_id(match_id: str, sequence: int) -> str:
    """Deriva un identificador estable a partir del partido y el orden de emisión.

    Se usa UUID v5 en lugar de v4 porque ``uuid4`` es aleatorio y rompería la
    reproducibilidad: dos ejecuciones con la misma semilla generarían el mismo
    partido con identificadores distintos, y la comparación byte a byte de la
    HU-8 dejaría de tener sentido.
    """
    return str(uuid.uuid5(_EVENT_NAMESPACE, f"{match_id}:{sequence}"))


def format_event_time(moment: datetime) -> str:
    """Formatea un instante como ISO-8601 UTC con milisegundos.

    La precisión se fija en milisegundos para que la representación sea estable
    y comparable entre ejecuciones y entre lenguajes.
    """
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


@dataclass(frozen=True, slots=True)
class MatchEvent:
    """Un evento del flujo ``match-events``."""

    event_id: str
    event_time: datetime
    match_id: str
    team: str
    event_type: EventType
    attrs: dict[str, JsonValue]

    def to_dict(self) -> dict[str, JsonValue]:
        """Proyecta el evento a la estructura que viaja por el broker."""
        return {
            "event_id": self.event_id,
            "event_time": format_event_time(self.event_time),
            "match_id": self.match_id,
            "team": self.team,
            "event_type": self.event_type,
            "contract_version": CONTRACT_VERSION,
            "attrs": self.attrs,
        }

    def to_json(self) -> str:
        """Serializa el evento como una línea JSON.

        ``sort_keys`` y separadores sin espacios no son cosmética: fijan una
        representación única por evento, de modo que dos ejecuciones con la
        misma semilla produzcan ficheros idénticos byte a byte.
        """
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
