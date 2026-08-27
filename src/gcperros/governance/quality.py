"""Marco de reglas de calidad sobre lo ingerido (HU-17).

Convierte los contadores que las demás piezas ya producen en un veredicto con
umbral. Antes existían los números —cuántos mensajes se rechazaron, cuántos
duplicados se suprimieron, cuánto se aplicó dentro de plazo— pero nadie decía
qué valor es aceptable, así que no se podía afirmar que la calidad estuviera
bien ni mal: solo describirla.

La trampa que este módulo evita
-------------------------------
Medir completitud **solo sobre lo que entró** daría siempre el cien por cien, y
lo daría por construcción: lo incompleto lo rechazó la propia frontera (HU-16).
Es el mismo error que el proyecto ya evita con la posesión —un indicador que
sale bien porque se fijó de antemano no prueba nada—. Por eso las reglas se
evalúan sobre **todo lo entregado**, incluido lo que se apartó.

Vale igual para la unicidad: contar identificadores repetidos *después* de
deduplicar daría siempre uno. Lo que se mide es el flujo tal como lo entregó el
broker, que es donde la repetición ocurre.

Lo medido y lo elegido
----------------------
El proyecto exige que un umbral se sostenga en evidencia. Aquí dos de los tres
la tienen y el tercero no, y conviene decirlo en voz alta en vez de disimularlo.
El detalle está en `docs/decisiones-de-diseno.md`, sección 8.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from gcperros.core.contracts import JsonValue, format_event_time
from gcperros.engine.dedup import DedupStats
from gcperros.engine.watermark import WatermarkStats
from gcperros.governance.gate import GateStats
from gcperros.governance.quarantine import utc_now

#: Decimales con los que se publica una medición. Los mismos que usa el resto
#: del proyecto, para que un informe serializado sea estable entre ejecuciones.
QUALITY_DECIMALS = 4


class QualityDimension(StrEnum):
    """Dimensiones de calidad que el proyecto mide en este sprint.

    Son tres y no las seis del catálogo habitual —exactitud, consistencia y
    validez quedan fuera— porque son las que se pueden medir con lo que el
    pipeline ya observa. Una dimensión sin forma de medirla es una casilla en
    un informe, no una garantía.
    """

    #: Qué proporción de lo entregado cumplía el contrato (HU-16).
    COMPLETENESS = "completeness"

    #: Qué proporción de las entregas del broker no eran repeticiones (HU-11).
    UNIQUENESS = "uniqueness"

    #: Qué proporción se aplicó dentro de la marca de agua (HU-12).
    TIMELINESS = "timeliness"


@dataclass(frozen=True, slots=True)
class QualityRule:
    """Una regla: una dimensión, un umbral y el motivo del umbral.

    El motivo viaja con la regla y no en un comentario aparte porque un umbral
    sin justificación es indistinguible de un número inventado, y quien lea un
    informe fallido necesita saber contra qué se le está midiendo.
    """

    name: str
    dimension: QualityDimension
    minimum: float
    rationale: str


@dataclass(frozen=True, slots=True)
class QualityMeasurement:
    """Lo que una regla observó.

    Se guardan el numerador y el denominador, no solo la proporción: 9 de 10 y
    900 de 1.000 dan el mismo 0,9 y no merecen la misma confianza.
    """

    rule: QualityRule
    observed: int
    total: int

    @property
    def value(self) -> float:
        """Proporción observada.

        Un flujo vacío vale uno: no hay evidencia de fallo, y devolver cero
        haría que un arranque en frío pareciera una avería. Es la misma
        convención que ya usan ``GateStats.conformity`` y
        ``WatermarkStats.timeliness``.
        """
        return self.observed / self.total if self.total else 1.0

    @property
    def passed(self) -> bool:
        """Indica si la medición alcanza el umbral de su regla."""
        return self.value >= self.rule.minimum

    def to_dict(self) -> dict[str, JsonValue]:
        """Proyecta la medición a la estructura que se persiste."""
        return {
            "rule": self.rule.name,
            "dimension": self.rule.dimension.value,
            "value": round(self.value, QUALITY_DECIMALS),
            "minimum": self.rule.minimum,
            "observed": self.observed,
            "total": self.total,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Veredicto de calidad de una ingestión.

    Attributes:
        scope: Qué se midió: un partido, un flujo, una ejecución.
        measured_at: Cuándo. Sin marca temporal no hay serie, y sin serie la
            calidad vuelve a ser una auditoría suelta en vez de una señal
            continua, que es justo lo que la historia pide evitar.
        measurements: Una por regla evaluada.
        unmeasured: Dimensiones para las que no había datos. **No medido no es
            lo mismo que aprobado**, y por eso se nombran en lugar de omitirse.
        rejections_by_rule: Motivos por los que se rechazaron mensajes. No es
            una medición, es el diagnóstico: dice qué hay que arreglar cuando
            la completitud falla.
    """

    scope: str
    measured_at: datetime
    measurements: tuple[QualityMeasurement, ...]
    unmeasured: tuple[str, ...] = ()
    rejections_by_rule: dict[str, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Indica si todas las reglas evaluadas alcanzan su umbral."""
        return all(measurement.passed for measurement in self.measurements)

    @property
    def failures(self) -> tuple[QualityMeasurement, ...]:
        """Mediciones que no alcanzaron su umbral."""
        return tuple(m for m in self.measurements if not m.passed)

    def to_dict(self) -> dict[str, JsonValue]:
        """Proyecta el informe a la estructura que se persiste."""
        return {
            "scope": self.scope,
            "measured_at": format_event_time(self.measured_at),
            "passed": self.passed,
            "measurements": [measurement.to_dict() for measurement in self.measurements],
            "unmeasured": list(self.unmeasured),
            "rejections_by_rule": dict(self.rejections_by_rule),
        }

    def to_json(self) -> str:
        """Serializa el informe como una línea JSON estable."""
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )


@dataclass(frozen=True, slots=True)
class IngestionEvidence:
    """Contadores de una ingestión, agrupados para que las reglas los juzguen.

    Cada uno puede faltar: el flujo de cuotas no pasa por el motor, así que no
    tiene ni deduplicación ni marca de agua. Lo que falta se declara como no
    medido en vez de darse por bueno.
    """

    gate: GateStats | None = None
    dedup: DedupStats | None = None
    watermark: WatermarkStats | None = None

    def observations(self) -> dict[QualityDimension, tuple[int, int]]:
        """Traduce los contadores a pares ``(observado, total)`` por dimensión."""
        found: dict[QualityDimension, tuple[int, int]] = {}

        if self.gate is not None:
            # El total incluye lo rechazado: medir solo sobre lo admitido daría
            # el cien por cien por construcción.
            found[QualityDimension.COMPLETENESS] = (self.gate.admitted, self.gate.seen)

        if self.dedup is not None:
            # Y aquí, el flujo tal como lo entregó el broker: contar después de
            # deduplicar daría siempre uno.
            found[QualityDimension.UNIQUENESS] = (self.dedup.accepted, self.dedup.seen)

        if self.watermark is not None:
            found[QualityDimension.TIMELINESS] = (self.watermark.released, self.watermark.seen)

        return found


###############################################################################
# Las reglas del proyecto
###############################################################################

CONTRACT_CONFORMITY = QualityRule(
    name="contract_conformity",
    dimension=QualityDimension.COMPLETENESS,
    minimum=0.99,
    rationale=(
        "Umbral de política, no medido: con los generadores del propio proyecto "
        "no hay rechazos, así que no hay nada que observar todavía. Se "
        "recalibra cuando exista ingestión real (HU-14)."
    ),
)

DELIVERY_UNIQUENESS = QualityRule(
    name="delivery_uniqueness",
    dimension=QualityDimension.UNIQUENESS,
    minimum=0.90,
    rationale=(
        "Con el inyector de duplicados en su 5 % por defecto —ya exagerado "
        "frente a Pub/Sub— la unicidad se observa entre 0,942 y 0,955 sobre "
        "ocho partidos. El umbral deja margen y solo se dispara ante algo peor "
        "que la adversidad que el proyecto se autoimpone."
    ),
)

APPLICATION_TIMELINESS = QualityRule(
    name="application_timeliness",
    dimension=QualityDimension.TIMELINESS,
    minimum=0.95,
    rationale=(
        "Umbral declarado por el proyecto en el OE-2. Con el margen de 10 s se "
        "observa entre 0,9992 y 1,0000, que es el mismo resultado que sostiene "
        "la elección de ese margen."
    ),
)

#: Las reglas vigentes, en el orden en que se informan.
DEFAULT_RULES: tuple[QualityRule, ...] = (
    CONTRACT_CONFORMITY,
    DELIVERY_UNIQUENESS,
    APPLICATION_TIMELINESS,
)


def assess(
    scope: str,
    evidence: IngestionEvidence,
    rules: Sequence[QualityRule] = DEFAULT_RULES,
    measured_at: datetime | None = None,
) -> QualityReport:
    """Evalúa las reglas contra lo observado en una ingestión.

    Args:
        scope: Qué se está midiendo.
        evidence: Contadores de la ingestión.
        rules: Reglas a aplicar.
        measured_at: Instante de la medición. Se inyecta para que un informe
            sea reproducible en una prueba.

    Returns:
        El informe, con una medición por regla evaluable y el nombre de las
        dimensiones que se quedaron sin datos.
    """
    observations = evidence.observations()

    measurements = tuple(
        QualityMeasurement(rule, *observations[rule.dimension])
        for rule in rules
        if rule.dimension in observations
    )
    unmeasured = tuple(rule.dimension.value for rule in rules if rule.dimension not in observations)

    return QualityReport(
        scope=scope,
        measured_at=measured_at or utc_now(),
        measurements=measurements,
        unmeasured=unmeasured,
        rejections_by_rule=dict(evidence.gate.by_rule) if evidence.gate else {},
    )
