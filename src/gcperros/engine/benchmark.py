"""Banco de carga: hasta qué tasa de emisión sostiene el motor (#18).

Responde a la pregunta del OE-3 con una medida en vez de una suposición:
a qué ritmo puede entrar un flujo antes de que el consumidor deje de dar
abasto y la cola crezca sin freno.

Se hace en dos pasos separados a propósito. Primero se **mide** cuánto cuesta
al motor consumir cada evento, en reloj de pared, con el motor de verdad.
Después se **simula** una cola con esos costes: el productor emite a una tasa
fija y el consumidor atiende de uno en uno. Así una tasa de 100.000 eventos por
segundo se caracteriza sin tener que generar 100.000 eventos por segundo, y
los costes son reales en vez de supuestos.

Sin broker desplegado, lo medido es el tramo en proceso: de la emisión a que el
motor consumió la entrega. La espera por la marca de agua es otro tramo, en
tiempo del flujo, y la mide ``engine.latency``; la red de Pub/Sub queda fuera
hasta que exista el proyecto de GCP.
"""

from __future__ import annotations

import statistics
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from gcperros.core.contracts import MatchEvent
from gcperros.engine.latency import percentile
from gcperros.engine.pipeline import MatchEngine

#: Tasas de emisión del barrido por defecto, en eventos por segundo. Un partido
#: emite del orden de 0,2; el barrido sube hasta donde una máquina corriente
#: se satura, para que la tabla enseñe el punto de corte y no sólo la holgura.
DEFAULT_RATES: tuple[float, ...] = (1.0, 100.0, 10_000.0, 50_000.0, 100_000.0, 200_000.0)

#: Veces que se mide el coste de cada evento. Se toma la mediana, que aguanta
#: bien un pico aislado del sistema operativo.
DEFAULT_REPEATS = 3


def measure_costs(
    events: list[MatchEvent],
    engine_factory: Callable[[], MatchEngine] = MatchEngine,
    repeats: int = DEFAULT_REPEATS,
) -> list[float]:
    """Coste en segundos de consumir cada evento, medido con el motor real.

    Raises:
        ValueError: Si no hay eventos o no se pide al menos una repetición.
    """
    if not events:
        raise ValueError("no hay eventos que medir")
    if repeats < 1:
        raise ValueError("hace falta al menos una repetición")

    runs: list[list[float]] = []
    for _ in range(repeats):
        engine = engine_factory()
        costs: list[float] = []
        for event in events:
            started = time.perf_counter()
            engine.process(event)
            costs.append(time.perf_counter() - started)
        engine.flush()
        runs.append(costs)

    return [statistics.median(sample) for sample in zip(*runs, strict=True)]


@dataclass(frozen=True, slots=True)
class RateResult:
    """Cómo se comportó la cola a una tasa de emisión."""

    rate_events_per_s: float
    utilization: float
    p50_s: float
    p95_s: float
    max_s: float
    max_backlog: int
    final_backlog: int

    @property
    def saturated(self) -> bool:
        """El consumidor no da abasto: la cola crece mientras dure la emisión."""
        return self.utilization >= 1.0


def simulate_queue(costs: list[float], rate_events_per_s: float) -> RateResult:
    """Emite a tasa fija y atiende de uno en uno con los costes medidos.

    El evento ``i`` se emite en ``i / tasa``; el consumidor lo empieza cuando
    llega o cuando termina el anterior, lo que ocurra más tarde. La latencia es
    de la emisión al final de su consumo, y el backlog es cuántos había
    emitidos y sin terminar en cada emisión.

    Raises:
        ValueError: Si no hay costes o la tasa no es positiva.
    """
    if not costs:
        raise ValueError("no hay costes con los que simular")
    if rate_events_per_s <= 0.0:
        raise ValueError("la tasa de emisión debe ser positiva")

    interval = 1.0 / rate_events_per_s
    unfinished: deque[float] = deque()
    latencies: list[float] = []
    finished_at = 0.0
    max_backlog = 0
    backlog = 0

    for index, cost in enumerate(costs):
        emitted_at = index * interval
        while unfinished and unfinished[0] <= emitted_at:
            unfinished.popleft()
        finished_at = max(emitted_at, finished_at) + cost
        unfinished.append(finished_at)
        latencies.append(finished_at - emitted_at)
        backlog = len(unfinished)
        max_backlog = max(max_backlog, backlog)

    return RateResult(
        rate_events_per_s=rate_events_per_s,
        utilization=round(rate_events_per_s * statistics.mean(costs), 4),
        p50_s=percentile(latencies, 0.50),
        p95_s=percentile(latencies, 0.95),
        max_s=max(latencies),
        max_backlog=max_backlog,
        final_backlog=backlog,
    )


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """El barrido completo, con el punto de saturación señalado."""

    match_id: str
    events: int
    mean_cost_s: float
    results: tuple[RateResult, ...]

    @property
    def capacity_events_per_s(self) -> float:
        """Tasa a la que la utilización llega a 1: el punto de saturación."""
        return 1.0 / self.mean_cost_s

    @property
    def saturation_rate(self) -> float | None:
        """Primera tasa del barrido que saturó, o ninguna si todas se sostuvieron."""
        return next((r.rate_events_per_s for r in self.results if r.saturated), None)


def run_benchmark(
    events: list[MatchEvent],
    rates: tuple[float, ...] = DEFAULT_RATES,
    engine_factory: Callable[[], MatchEngine] = MatchEngine,
    repeats: int = DEFAULT_REPEATS,
) -> BenchmarkReport:
    """Mide los costes una vez y barre las tasas con ellos.

    Los costes dependen de la máquina; la forma de la tabla, no: la utilización
    crece linealmente con la tasa y la cola se dispara al cruzar 1.
    """
    costs = measure_costs(events, engine_factory, repeats)
    return BenchmarkReport(
        match_id=events[0].match_id,
        events=len(events),
        mean_cost_s=statistics.mean(costs),
        results=tuple(simulate_queue(costs, rate) for rate in rates),
    )
