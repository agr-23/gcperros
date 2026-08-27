"""Frontera de ingestión: lo que decide qué llega al motor (HU-16).

Se interpone entre el broker y ``gcperros.engine``. Un mensaje conforme sale
convertido en el objeto del contrato; uno que no lo es se archiva en el
repositorio de inválidos con su causa y **no llega al motor**.

Por qué aquí y no dentro del motor: validar después de haber empezado a procesar
significa haber pagado ya el cómputo que se quería evitar, y significa además
que el motor tendría que saber qué hacer con lo que no entiende. Con la frontera
delante, el motor puede asumir que todo lo que recibe es conforme, y esa
suposición es lo que le permite ser tan simple como es.

El orden completo del recorrido de un mensaje queda así:

1. **Validar** contra el contrato y apartar lo no conforme (HU-16, este módulo).
2. **Deduplicar** por ``event_id`` (HU-11).
3. **Reordenar** por marca de agua (HU-12).
4. **Aplicar** al estado.

La validación va primero por el mismo argumento que sostiene el orden de los
otros tres pasos: cada uno descarta trabajo que los siguientes ya no tendrán que
hacer. Un mensaje inválido no merece ocupar sitio en la memoria del
deduplicador, y menos aún en el buffer de la marca de agua.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

from gcperros.core.contracts import (
    MatchEvent,
    OddsUpdate,
    parse_match_event,
    parse_odds_update,
)
from gcperros.core.schema import MATCH_EVENT_SCHEMA, ODDS_UPDATE_SCHEMA, StreamSchema
from gcperros.governance.quarantine import InvalidEventStore, build_record, utc_now
from gcperros.governance.validation import (
    ValidationResult,
    Violation,
    ViolationRule,
    validate_message,
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class GateStats:
    """Qué atravesó la frontera y qué se quedó fuera.

    Es la primera medición de calidad del pipeline y alimenta directamente la
    dimensión de *completitud* del marco de la HU-17: un flujo del que se cae el
    diez por ciento de los mensajes es un flujo incompleto, aunque todo lo que
    haya entrado esté impecable.

    Attributes:
        admitted: Mensajes conformes que siguieron hacia el motor.
        rejected: Mensajes apartados.
        by_rule: Cuántos rechazos presentaron cada motivo. Un mensaje con tres
            defectos distintos suma en los tres, de modo que los recuentos
            responden a «¿cuántos mensajes traían este problema?» y no a
            «¿cuántos mensajes se cayeron por esto?».
    """

    admitted: int
    rejected: int
    by_rule: dict[str, int]

    @property
    def seen(self) -> int:
        """Mensajes ofrecidos a la frontera."""
        return self.admitted + self.rejected

    @property
    def conformity(self) -> float:
        """Proporción de mensajes conformes.

        Un flujo sin mensajes se considera conforme: no hay evidencia de lo
        contrario, y devolver cero haría que un arranque en frío pareciera una
        avería.
        """
        return self.admitted / self.seen if self.seen else 1.0


class IngestionGate(Generic[T]):
    """Valida los mensajes de un flujo y aparta los que no cumplen el contrato."""

    __slots__ = ("_admitted", "_by_rule", "_clock", "_parse", "_schema", "_sequence", "_store")

    def __init__(
        self,
        schema: StreamSchema,
        parse: Callable[[bytes | str], T],
        store: InvalidEventStore,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Crea la frontera de un flujo.

        Args:
            schema: Contrato contra el que se juzgan los mensajes.
            parse: Lector que construye el objeto una vez validado.
            store: Dónde se archiva lo rechazado.
            clock: De dónde sale el instante del rechazo. Se inyecta para que
                las pruebas puedan fijarlo.
        """
        self._schema = schema
        self._parse = parse
        self._store = store
        self._clock = clock
        self._sequence = 0
        self._admitted = 0
        self._by_rule: dict[str, int] = {}

    @property
    def stats(self) -> GateStats:
        """Instantánea de los contadores."""
        return GateStats(
            admitted=self._admitted,
            rejected=self._sequence - self._admitted,
            by_rule=dict(self._by_rule),
        )

    def admit(self, message: bytes | str) -> T | None:
        """Juzga un mensaje y lo deja pasar o lo aparta.

        Args:
            message: Carga útil tal como la entregó el broker.

        Returns:
            El objeto del contrato si el mensaje es conforme; ``None`` si se
            archivó en el repositorio de inválidos.
        """
        self._sequence += 1
        # Se decodifica con reemplazo y no de forma estricta: un mensaje que ni
        # siquiera es UTF-8 también hay que poder archivarlo, y un repositorio
        # que se cae ante la basura peor formada es el que menos sirve.
        raw = message.decode("utf-8", errors="replace") if isinstance(message, bytes) else message

        result = validate_message(message, self._schema)
        if not result.is_valid:
            self._reject(result, raw)
            return None

        try:
            parsed = self._parse(message)
        except ValueError as error:
            # El esquema aprobó y el lector no pudo: discrepan entre sí, y el
            # defecto es del proyecto. Se archiva en vez de propagarse, porque
            # detener la ingestión por un desacuerdo interno castigaría al
            # productor por un error que no cometió.
            self._reject(self._unreadable(result, error), raw)
            return None

        self._admitted += 1
        return parsed

    def admit_all(self, messages: Iterable[bytes | str]) -> list[T]:
        """Juzga un lote y devuelve solo lo conforme, en orden de llegada.

        Acepta cualquier iterable y no una lista concreta: ``list`` es
        invariante en Python, de modo que una ``list[str]`` —lo que se tiene
        casi siempre— no encajaría en una ``list[bytes | str]``.
        """
        admitted: list[T] = []
        for message in messages:
            parsed = self.admit(message)
            if parsed is not None:
                admitted.append(parsed)
        return admitted

    def close(self) -> None:
        """Cierra el repositorio de inválidos."""
        self._store.close()

    def _unreadable(self, result: ValidationResult, error: ValueError) -> ValidationResult:
        return ValidationResult(
            stream=result.stream,
            contract_version=result.contract_version,
            violations=(Violation("<mensaje>", ViolationRule.UNREADABLE, str(error)),),
        )

    def _reject(self, result: ValidationResult, raw: str) -> None:
        for rule in result.rules:
            self._by_rule[rule] = self._by_rule.get(rule, 0) + 1
        self._store.record(build_record(result, raw, self._sequence, self._clock()))


def match_event_gate(
    store: InvalidEventStore, clock: Callable[[], datetime] = utc_now
) -> IngestionGate[MatchEvent]:
    """Frontera del flujo ``match-events``."""
    return IngestionGate(MATCH_EVENT_SCHEMA, parse_match_event, store, clock)


def odds_update_gate(
    store: InvalidEventStore, clock: Callable[[], datetime] = utc_now
) -> IngestionGate[OddsUpdate]:
    """Frontera del flujo ``odds-updates``."""
    return IngestionGate(ODDS_UPDATE_SCHEMA, parse_odds_update, store, clock)
