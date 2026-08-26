"""Deduplicación por ``event_id`` (HU-11).

Pub/Sub entrega al menos una vez: si el consumidor tarda en confirmar, el broker
vuelve a entregar. Sin esta pieza, esa característica se convertiría en un gol
contado dos veces o en una posesión inflada.

Se coloca antes de aplicar nada al estado. Si el evento se aplicase primero y se
comprobase después, el estado ya estaría corrupto cuando se detectara el
duplicado.

La memoria está acotada, así que la garantía es condicional: un duplicado se
detecta siempre que entre el original y la repetición lleguen menos de
``capacity`` eventos distintos. Por qué no un filtro de Bloom, y por qué la
capacidad por defecto basta para la unidad de proceso del proyecto:
ver `docs/decisiones-de-diseno.md`, sección 3.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Identificadores recordados por defecto. Un partido emite del orden de 1.300
#: eventos, así que caben varios encuentros completos.
DEFAULT_CAPACITY = 100_000


@dataclass(frozen=True, slots=True)
class DedupStats:
    """Recuento de lo que ha pasado por el deduplicador.

    Alimenta la dimensión de *unicidad* del marco de calidad (HU-17): el número
    de duplicados suprimidos es una métrica de gobernanza, no un detalle de
    implementación, y por eso se expone en lugar de quedarse en un contador
    interno.
    """

    accepted: int
    duplicates: int
    forgotten: int

    @property
    def seen(self) -> int:
        """Total de eventos ofrecidos al deduplicador."""
        return self.accepted + self.duplicates

    @property
    def duplicate_rate(self) -> float:
        """Proporción de entregas que resultaron ser repeticiones."""
        return self.duplicates / self.seen if self.seen else 0.0


class Deduplicator:
    """Recuerda los identificadores recientes para rechazar repeticiones."""

    __slots__ = ("_accepted", "_capacity", "_duplicates", "_forgotten", "_seen")

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        """Crea un deduplicador que recuerda ``capacity`` identificadores.

        Args:
            capacity: Cuántos identificadores se retienen antes de empezar a
                olvidar los más antiguos.

        Raises:
            ValueError: Si la capacidad no es positiva. Una capacidad de cero
                aceptaría todos los duplicados en silencio, que es justo el
                fallo que este componente existe para evitar.
        """
        if capacity < 1:
            raise ValueError("la capacidad del deduplicador debe ser al menos 1")

        self._capacity = capacity
        # Un dict conserva el orden de inserción, así que sirve de cola FIFO
        # con descarte en tiempo constante: el primer elemento es el más viejo.
        self._seen: dict[str, None] = {}
        self._accepted = 0
        self._duplicates = 0
        self._forgotten = 0

    @property
    def capacity(self) -> int:
        """Cuántos identificadores retiene."""
        return self._capacity

    @property
    def remembered(self) -> int:
        """Cuántos identificadores tiene ahora mismo en memoria."""
        return len(self._seen)

    @property
    def stats(self) -> DedupStats:
        """Instantánea de los contadores."""
        return DedupStats(
            accepted=self._accepted,
            duplicates=self._duplicates,
            forgotten=self._forgotten,
        )

    def accept(self, event_id: str) -> bool:
        """Decide si un evento debe procesarse.

        Args:
            event_id: Identificador del evento entregado por el broker.

        Returns:
            ``True`` si es la primera vez que se ve y debe aplicarse al estado;
            ``False`` si es una repetición y hay que descartarlo.
        """
        if event_id in self._seen:
            self._duplicates += 1
            return False

        self._seen[event_id] = None
        self._accepted += 1

        if len(self._seen) > self._capacity:
            # `next(iter(...))` devuelve la clave más antigua: el dict mantiene
            # el orden de inserción.
            oldest = next(iter(self._seen))
            del self._seen[oldest]
            self._forgotten += 1

        return True
