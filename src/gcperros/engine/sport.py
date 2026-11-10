"""Lo único que el motor necesita saber de un deporte (#89).

La tesis del proyecto es que deduplicar, reordenar y aplicar no dependen del
fútbol. Este protocolo es esa tesis escrita como tipo: el motor
(``engine/pipeline.py``) recibe un estado que sabe aplicar un evento, resumirse
y explicar de dónde sale cada número, y no sabe nada más. El deduplicador, la
marca de agua y la posesión siguen siendo los mismos para todos los deportes.

Cada deporte declara también sus indicadores, el contrato de sus eventos y los
modelos que calculan algún número, para que la auditoría (HU-18) pueda
explicarlos sin conocerlos.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, TypeVar

from gcperros.core.contracts import MatchEvent
from gcperros.core.lineage import LineageRecord

#: El resumen que produce el estado: ``MatchSummary`` en fútbol,
#: ``BasketballSummary`` en baloncesto.
S_co = TypeVar("S_co", covariant=True)


class SportState(Protocol[S_co]):
    """Estado vivo de un partido de cualquier deporte."""

    @property
    def contract_version(self) -> str:
        """Versión del contrato bajo el que llegan los eventos."""

    @property
    def team_indicators(self) -> tuple[str, ...]:
        """Indicadores por equipo del resumen, en el orden en que se informan."""

    @property
    def models_by_indicator(self) -> Mapping[str, Mapping[str, str]]:
        """Qué modelo calcula cada indicador. Lo que no aparece es un recuento."""

    def apply(self, event: MatchEvent) -> None:
        """Incorpora un evento ya deduplicado y en orden."""

    def summary(self) -> S_co:
        """Proyecta el estado a la misma estructura que el plano batch."""

    def lineage(self, indicator: str, scope: str) -> LineageRecord:
        """Explica de dónde sale un indicador concreto."""

    def lineage_records(self) -> tuple[LineageRecord, ...]:
        """Linaje de todos los indicadores con al menos un evento detrás."""

    @property
    def event_count(self) -> int:
        """Cuántos eventos se han aplicado."""

    @property
    def teams(self) -> tuple[str, ...]:
        """Equipos conocidos, en el orden en que aparecieron."""
