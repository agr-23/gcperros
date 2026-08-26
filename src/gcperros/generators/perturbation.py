"""Inyector de perturbaciones sobre un flujo de eventos.

El pipeline se valida sometiéndolo a las condiciones adversas que encontrará en
producción, y para eso hay que provocarlas a voluntad. Este módulo fabrica esas
condiciones de forma **determinista**: con la misma semilla, el mismo flujo se
degrada exactamente igual, y así una diferencia en el resultado del motor apunta
a un cambio en el motor y no a otra perturbación distinta.

De momento sólo se inyecta duplicación, que es lo que la HU-11 necesita para
demostrar su promesa. El desorden temporal y el retardo variable llegan con la
HU-12, que es la historia que los resuelve.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from gcperros.core.contracts import MatchEvent

#: Proporción de eventos que el broker reentrega, por defecto. Pub/Sub duplica
#: bastante menos que esto en operación normal; se exagera a propósito para que
#: la prueba sea exigente.
DEFAULT_DUPLICATE_RATE = 0.05

#: Cuántas posiciones más adelante puede reaparecer una reentrega. Un duplicado
#: de Pub/Sub llega al vencer el plazo de confirmación, es decir poco después
#: del original, no en cualquier momento del partido.
DEFAULT_MAX_GAP = 20


@dataclass(frozen=True, slots=True)
class DuplicationReport:
    """Qué se inyectó, para poder contrastarlo con lo que el motor detectó."""

    original_count: int
    delivered_count: int
    injected: int


def inject_duplicates(
    events: list[MatchEvent],
    seed: int,
    rate: float = DEFAULT_DUPLICATE_RATE,
    max_gap: int = DEFAULT_MAX_GAP,
) -> tuple[list[MatchEvent], DuplicationReport]:
    """Reentrega algunos eventos, imitando la garantía *al menos una vez*.

    El duplicado es el **mismo objeto**, con el mismo ``event_id``: no es un
    evento parecido, es la misma entrega repetida. Esa es exactamente la
    situación que el deduplicador tiene que resolver.

    Args:
        events: Flujo original, en orden cronológico.
        seed: Semilla de la perturbación. Se mantiene separada de la del
            generador para poder variar la adversidad sin cambiar el partido.
        rate: Proporción de eventos que se reentregan.
        max_gap: Distancia máxima, en posiciones, a la que reaparece la copia.

    Returns:
        El flujo tal como lo entregaría el broker, y el informe de lo inyectado.

    Raises:
        ValueError: Si la proporción cae fuera de ``[0, 1]`` o el hueco no es
            positivo.
    """
    if not 0.0 <= rate <= 1.0:
        raise ValueError("la proporción de duplicados debe estar entre 0 y 1")
    if max_gap < 1:
        raise ValueError("el hueco máximo debe ser de al menos una posición")

    rng = random.Random(seed)
    # Se planifica primero y se inserta después: mutar la lista mientras se
    # recorre desplazaría las posiciones y haría el resultado dependiente del
    # orden de inserción.
    pending: dict[int, list[MatchEvent]] = {}
    injected = 0

    for index, event in enumerate(events):
        if rng.random() >= rate:
            continue
        target = min(index + rng.randint(1, max_gap), len(events))
        pending.setdefault(target, []).append(event)
        injected += 1

    delivered: list[MatchEvent] = []
    for index, event in enumerate(events):
        delivered.append(event)
        delivered.extend(pending.get(index + 1, ()))

    return delivered, DuplicationReport(
        original_count=len(events),
        delivered_count=len(delivered),
        injected=injected,
    )


#: Retardo medio de red por defecto, en segundos. Es el que decide cuánto se
#: adelantan unos eventos a otros: si todos sufrieran el mismo retardo el flujo
#: llegaría tarde pero en orden, y no habría nada que reordenar.
DEFAULT_MEAN_DELAY_S = 2.0

#: Tope del retardo. Acota la cola de la exponencial para que un solo evento no
#: se vaya a varios minutos y distorsione la medición.
DEFAULT_MAX_DELAY_S = 30.0


@dataclass(frozen=True, slots=True)
class DisorderReport:
    """Cuánto se desordenó el flujo respecto del orden cronológico."""

    displaced: int
    max_displacement: int
    max_delay_s: float

    @property
    def is_ordered(self) -> bool:
        """Indica si el flujo llegó en orden pese a la perturbación."""
        return self.displaced == 0


def inject_disorder(
    events: list[MatchEvent],
    seed: int,
    mean_delay_s: float = DEFAULT_MEAN_DELAY_S,
    max_delay_s: float = DEFAULT_MAX_DELAY_S,
) -> tuple[list[MatchEvent], DisorderReport]:
    """Reordena las entregas simulando latencia de red variable.

    Cada evento sufre un retardo propio, extraído de una exponencial: la mayoría
    llega enseguida y unos pocos se rezagan mucho. Esa cola larga es lo que
    genera adelantamientos, que es la condición que el motor debe resolver.

    El ``event_time`` **no** se toca. El evento sigue diciendo cuándo ocurrió;
    lo único que cambia es cuándo llega, que es exactamente lo que hace la red.

    Args:
        events: Flujo original, en orden cronológico.
        seed: Semilla de la perturbación, independiente de la del partido.
        mean_delay_s: Retardo medio de entrega.
        max_delay_s: Retardo máximo, para acotar la cola.

    Returns:
        El flujo en orden de llegada, y el informe del desorden provocado.

    Raises:
        ValueError: Si los retardos son negativos o el máximo es menor que la
            media, en cuyo caso la distribución no tendría sentido.
    """
    if mean_delay_s < 0 or max_delay_s < 0:
        raise ValueError("los retardos no pueden ser negativos")
    if max_delay_s < mean_delay_s:
        raise ValueError("el retardo máximo no puede ser menor que el medio")

    rng = random.Random(seed)
    arrivals: list[tuple[float, int, MatchEvent]] = []
    worst_delay = 0.0

    for index, event in enumerate(events):
        delay = min(rng.expovariate(1.0 / mean_delay_s), max_delay_s) if mean_delay_s else 0.0
        worst_delay = max(worst_delay, delay)
        arrival = event.event_time.timestamp() + delay
        # El índice original desempata: dos llegadas simultáneas conservan el
        # orden de emisión, y el resultado no depende del orden del montículo.
        arrivals.append((arrival, index, event))

    arrivals.sort(key=lambda item: (item[0], item[1]))

    displaced = 0
    max_displacement = 0
    for position, (_, original_index, _) in enumerate(arrivals):
        shift = abs(position - original_index)
        if shift:
            displaced += 1
            max_displacement = max(max_displacement, shift)

    return [event for _, _, event in arrivals], DisorderReport(
        displaced=displaced,
        max_displacement=max_displacement,
        max_delay_s=worst_delay,
    )
