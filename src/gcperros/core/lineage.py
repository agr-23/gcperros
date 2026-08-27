"""Linaje de los indicadores: qué eventos formaron cada número (HU-18).

Un indicador sin linaje es un número que hay que creerse. Este módulo guarda,
para cada uno, la huella de los eventos que lo produjeron, de modo que cualquier
salida del sistema se pueda auditar sin depender de que alguien del equipo se
acuerde de cómo se calculó.

Por qué una huella y no la lista de identificadores
---------------------------------------------------
Guardar los `event_id` completos no escala: un partido emite del orden de 1.200
eventos y la temporada no está acotada. Guardar solo un hash tampoco vale por sí
solo, porque no permite comprobar nada contra el origen.

La salida está en una premisa que el proyecto ya sostiene: **el pipeline es
determinista y la capa Raw guarda el flujo sin transformar.** No hace falta
almacenar el linaje entero; hace falta que **la re-derivación sea verificable**.
Se reprocesa el partido, se vuelve a plegar la huella y se compara. Es el mismo
mecanismo que las huellas SHA-256 congeladas de `tests/test_pipeline.py`.

Por qué el pliegue conmuta
--------------------------
La huella se acumula **sumando** las huellas individuales, no encadenándolas: el
resultado no depende del orden en que llegaron los eventos.

No es comodidad, es coherencia. La sección 3 de `docs/decisiones-de-diseno.md`
justifica el desempate entre eventos del mismo instante diciendo que *"los
indicadores son recuentos y sumas, que conmutan, de modo que el desempate no
altera el estado"*. Si el linaje **no** conmutara, introduciría una dependencia
del orden que el propio indicador no tiene, y el plano batch y el de streaming
producirían huellas distintas para el mismo número.

Se suma en lugar de aplicar un XOR, que también conmuta, porque el XOR de un
valor consigo mismo se cancela: un identificador repetido desaparecería de la
huella sin dejar rastro. La deduplicación (HU-11) debería impedirlo, pero un
mecanismo de auditoría no debe apoyarse en que otro no falle.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from gcperros.core.contracts import JsonValue

#: Cuántos identificadores se conservan en claro por indicador. Sirven para
#: comprobar a mano contra la capa Raw sin tener que reprocesar el partido
#: entero; no son el linaje, son una muestra de él.
SAMPLE_SIZE = 3

_DIGEST_BYTES = 32
_DIGEST_MODULUS = 1 << (_DIGEST_BYTES * 8)

#: Huella de un conjunto vacío. Se nombra en vez de escribir sesenta y cuatro
#: ceros allí donde haga falta compararla.
EMPTY_DIGEST = "0" * (_DIGEST_BYTES * 2)


def event_fingerprint(event_id: str) -> int:
    """Huella numérica de un identificador, para poder plegarla sumando."""
    return int.from_bytes(hashlib.sha256(event_id.encode("utf-8")).digest(), "big")


@dataclass(frozen=True, slots=True)
class LineageRecord:
    """De dónde sale un indicador.

    Attributes:
        indicator: Qué número se está explicando.
        scope: A quién pertenece: un equipo, o el partido entero.
        event_count: Cuántos eventos lo formaron.
        digest: Huella conmutativa de sus identificadores.
        sample: Unos pocos identificadores en claro, los menores en orden
            lexicográfico. Se eligen así y no "los primeros" porque el pliegue
            no depende del orden, de modo que "primero" no significaría lo mismo
            en dos ejecuciones; el menor sí.
    """

    indicator: str
    scope: str
    event_count: int
    digest: str
    sample: tuple[str, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        """Proyecta el linaje a la estructura que se persiste."""
        return {
            "indicator": self.indicator,
            "scope": self.scope,
            "event_count": self.event_count,
            "digest": self.digest,
            "sample": list(self.sample),
        }

    def to_json(self) -> str:
        """Serializa el linaje como una línea JSON estable."""
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )


class LineageAccumulator:
    """Pliega los identificadores de un indicador según van llegando.

    Ocupa memoria constante: un contador, una suma y la muestra acotada. Es lo
    que permite trazar todos los indicadores de un partido sin guardar ni un
    solo identificador de más.
    """

    __slots__ = ("_count", "_sample", "_total")

    def __init__(self) -> None:
        """Crea un acumulador vacío."""
        self._count = 0
        self._total = 0
        self._sample: list[str] = []

    @property
    def count(self) -> int:
        """Cuántos eventos se han plegado."""
        return self._count

    @property
    def digest(self) -> str:
        """Huella acumulada, en hexadecimal."""
        return f"{self._total % _DIGEST_MODULUS:0{_DIGEST_BYTES * 2}x}"

    @property
    def sample(self) -> tuple[str, ...]:
        """Los identificadores menores vistos hasta ahora."""
        return tuple(self._sample)

    def add(self, event_id: str) -> None:
        """Incorpora un evento al linaje del indicador."""
        self._count += 1
        self._total = (self._total + event_fingerprint(event_id)) % _DIGEST_MODULUS

        # La muestra se mantiene ordenada y acotada: insertar y recortar cuesta
        # lo mismo que comparar, porque nunca tiene más de SAMPLE_SIZE entradas.
        if len(self._sample) < SAMPLE_SIZE or event_id < self._sample[-1]:
            self._sample.append(event_id)
            self._sample.sort()
            del self._sample[SAMPLE_SIZE:]

    def record(self, indicator: str, scope: str) -> LineageRecord:
        """Cierra el linaje acumulado en un registro."""
        return LineageRecord(
            indicator=indicator,
            scope=scope,
            event_count=self._count,
            digest=self.digest,
            sample=self.sample,
        )
