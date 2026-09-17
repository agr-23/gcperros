"""Latencia extremo a extremo de cada evento, de que ocurre a que se aplica (#18).

La tensión de la sección 3 del documento de decisiones —un margen de 10 s en la
marca de agua contra un SLA de 2 s en p95— estaba enunciada, no medida. Este
módulo es lo que la mide: para cada evento aplicado al estado, cuánto pasó entre
que ocurrió y que el motor lo aplicó, y qué parte de ese tiempo la puso la red y
qué parte la puso el propio motor reteniéndolo.

La latencia se mide en **tiempo del flujo**, no en reloj de pared. El reloj del
motor es el último instante de llegada conocido, y con él se fecha cada
aplicación. Así la medida es reproducible desde una semilla y no depende de la
máquina en la que corre; el coste de cómputo por evento es otra medida y la
toma el banco de pruebas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from gcperros.core.contracts import MatchEvent


@dataclass(frozen=True, slots=True)
class LatencySample:
    """El recorrido temporal de un evento hasta el estado."""

    event_id: str
    event_time: datetime
    arrived_at: datetime
    applied_at: datetime

    @property
    def transport_s(self) -> float:
        """Lo que tardó en llegar: se lo debe a la red y al broker."""
        return (self.arrived_at - self.event_time).total_seconds()

    @property
    def wait_s(self) -> float:
        """Lo que esperó ya dentro: se lo debe a la marca de agua."""
        return (self.applied_at - self.arrived_at).total_seconds()

    @property
    def total_s(self) -> float:
        """De extremo a extremo, que es lo que el SLA acota."""
        return (self.applied_at - self.event_time).total_seconds()


def percentile(values: list[float], q: float) -> float:
    """Percentil por rango más cercano, sin interpolar.

    Devuelve siempre un valor que ocurrió de verdad, que es lo honesto para
    informar de un p95: no hay un evento «entre dos muestras».

    Raises:
        ValueError: Si no hay valores o ``q`` cae fuera de ``[0, 1]``.
    """
    if not values:
        raise ValueError("no hay valores de los que sacar un percentil")
    if not 0.0 <= q <= 1.0:
        raise ValueError("el percentil se pide entre 0 y 1")
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


@dataclass(frozen=True, slots=True)
class LatencyStats:
    """Resumen de la latencia de un flujo, con la parte que puso el motor."""

    count: int
    mean_s: float
    p50_s: float
    p95_s: float
    max_s: float
    mean_wait_s: float

    @classmethod
    def empty(cls) -> LatencyStats:
        """Lo que se informa cuando no se aplicó ningún evento."""
        return cls(count=0, mean_s=0.0, p50_s=0.0, p95_s=0.0, max_s=0.0, mean_wait_s=0.0)

    @classmethod
    def from_samples(cls, samples: tuple[LatencySample, ...]) -> LatencyStats:
        """Resume las muestras. Vacío si no hay ninguna."""
        if not samples:
            return cls.empty()
        totals = [sample.total_s for sample in samples]
        waits = [sample.wait_s for sample in samples]
        return cls(
            count=len(samples),
            mean_s=round(sum(totals) / len(totals), 4),
            p50_s=round(percentile(totals, 0.50), 4),
            p95_s=round(percentile(totals, 0.95), 4),
            max_s=round(max(totals), 4),
            mean_wait_s=round(sum(waits) / len(waits), 4),
        )


class LatencyRecorder:
    """Anota cuándo llegó cada evento y cuándo se aplicó.

    Guarda las llegadas sólo mientras el evento espera en el buffer: al
    aplicarse, la llegada se convierte en muestra y se olvida. Las muestras sí se
    conservan enteras, porque un p95 exacto las necesita todas; la unidad de
    proceso del proyecto es el partido, y un partido son unos miles.
    """

    __slots__ = ("_arrivals", "_samples")

    def __init__(self) -> None:
        """Crea un registro vacío."""
        self._arrivals: dict[str, datetime] = {}
        self._samples: list[LatencySample] = []

    def arrived(self, event: MatchEvent, at: datetime) -> None:
        """Anota que el evento entró al motor en el instante dado."""
        self._arrivals[event.event_id] = at

    def applied(self, event: MatchEvent, at: datetime) -> None:
        """Cierra la muestra del evento: se aplicó al estado en el instante dado.

        Raises:
            KeyError: Si el evento nunca se anotó como llegado. Sería un fallo
                del motor, no del flujo, y no debe pasar en silencio.
        """
        arrived_at = self._arrivals.pop(event.event_id)
        self._samples.append(
            LatencySample(
                event_id=event.event_id,
                event_time=event.event_time,
                arrived_at=arrived_at,
                applied_at=at,
            )
        )

    @property
    def samples(self) -> tuple[LatencySample, ...]:
        """Todas las muestras cerradas, en orden de aplicación."""
        return tuple(self._samples)

    def stats(self) -> LatencyStats:
        """Resumen de lo aplicado hasta ahora."""
        return LatencyStats.from_samples(self.samples)
