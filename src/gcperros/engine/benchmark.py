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

Este módulo trae el segundo paso, que es aritmética y se prueba sola; la
medición con el motor real llega en la pieza siguiente.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass

from gcperros.engine.latency import percentile


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
