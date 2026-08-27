"""Auditoría de los indicadores: qué los produjo y qué los calculó (HU-18).

Responde, para cualquier número que el sistema muestre, a tres preguntas que
hasta ahora solo podía contestar quien escribió el código:

1. **¿Qué eventos lo formaron?** El linaje, plegado en una huella verificable
   (`core/lineage.py`).
2. **¿Qué modelo lo calculó?** La versión del modelo, cuando hay modelo detrás.
3. **¿Bajo qué contrato llegaron esos eventos?** La versión del contrato de
   datos, sin la cual el linaje no se puede reinterpretar más adelante.

Sobre los modelos: **solo se estampa una versión donde de verdad hay un modelo.**
Contar goles no usa ninguno; ponerle `xg-1.0.0` a un recuento sería una mentira
cómoda que haría el informe más uniforme y menos cierto. Hoy el único indicador
del motor con modelo detrás es ``total_xg``.

Lo que esto todavía no traza
----------------------------
Señales. El proyecto no tiene ninguna: la de discrepancia entre mercados es la
HU-19 y no está construida. Lo que se traza son los indicadores, que es lo que
existe y lo que cualquier señal futura va a consumir. Cuando la señal aparezca,
declarar su linaje es añadir una entrada a ``MODELS_BY_INDICATOR`` y plegar los
identificadores que la produjeron: el mecanismo ya está.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from gcperros.core import odds, xg
from gcperros.core.contracts import MATCH_CONTRACT_VERSION, JsonValue, format_event_time
from gcperros.core.lineage import LineageRecord
from gcperros.core.stats import MatchSummary
from gcperros.engine.state import WHOLE_MATCH, LiveMatchState
from gcperros.governance.quarantine import utc_now

#: Indicadores por equipo que produce el motor, en el orden en que se informan.
#: Son los campos de ``MatchSummary`` que se desglosan por equipo.
TEAM_INDICATORS: tuple[str, ...] = (
    "goals",
    "shots",
    "total_xg",
    "passes",
    "completed_passes",
    "fouls",
    "red_cards",
    "possessions",
)

#: Indicadores del partido entero.
MATCH_INDICATORS: tuple[str, ...] = ("event_count",)

#: Qué modelo calcula cada indicador. Lo que no aparece aquí es un recuento o
#: una suma directa, sin modelo que versionar.
MODELS_BY_INDICATOR: Mapping[str, Mapping[str, str]] = {
    "total_xg": {"xg": xg.MODEL_VERSION},
}

#: Modelos del proyecto, para poder declararlos en bloque cuando haga falta
#: (por ejemplo, al trazar una señal de mercado en la HU-19).
MODEL_VERSIONS: Mapping[str, str] = {
    "xg": xg.MODEL_VERSION,
    "odds": odds.MODEL_VERSION,
}


@dataclass(frozen=True, slots=True)
class Explanation:
    """Por qué un indicador vale lo que vale."""

    indicator: str
    scope: str
    value: float
    contract_version: str
    model_versions: Mapping[str, str]
    lineage: LineageRecord

    def to_dict(self) -> dict[str, JsonValue]:
        """Proyecta la explicación a la estructura que se persiste."""
        return {
            "indicator": self.indicator,
            "scope": self.scope,
            "value": self.value,
            "contract_version": self.contract_version,
            "model_versions": dict(self.model_versions),
            "lineage": self.lineage.to_dict(),
        }

    def to_json(self) -> str:
        """Serializa la explicación como una línea JSON estable."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class AuditTrail:
    """Todos los indicadores de un partido, cada uno con su procedencia."""

    scope: str
    produced_at: datetime
    explanations: tuple[Explanation, ...]

    def of(self, indicator: str, scope: str) -> Explanation:
        """Recupera la explicación de un indicador concreto.

        Raises:
            KeyError: Si el indicador no forma parte de la auditoría.
        """
        for explanation in self.explanations:
            if explanation.indicator == indicator and explanation.scope == scope:
                return explanation
        raise KeyError(f"la auditoría no incluye {indicator!r} para {scope!r}")

    @property
    def digests(self) -> dict[tuple[str, str], str]:
        """Huella de cada indicador, para comparar dos derivaciones."""
        return {(e.indicator, e.scope): e.lineage.digest for e in self.explanations}

    def to_dict(self) -> dict[str, JsonValue]:
        """Proyecta la auditoría a la estructura que se persiste."""
        return {
            "scope": self.scope,
            "produced_at": format_event_time(self.produced_at),
            "explanations": [explanation.to_dict() for explanation in self.explanations],
        }

    def to_json(self) -> str:
        """Serializa la auditoría como una línea JSON estable."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _value(summary: MatchSummary, indicator: str, scope: str) -> float:
    """Lee del resumen el número que se está explicando.

    Comprueba que el alcance corresponda al indicador. Sin esa comprobación,
    pedir un indicador de equipo con el alcance del partido devolvía el recuento
    de eventos etiquetado con otro nombre: un número acompañado de una
    explicación falsa, que es exactamente lo que esta historia existe para
    evitar.

    Raises:
        KeyError: Si el indicador no se mide en ese alcance.
        AttributeError: Si el indicador no existe.
    """
    if indicator in MATCH_INDICATORS:
        if scope != WHOLE_MATCH:
            raise KeyError(f"{indicator!r} es del partido entero, no de {scope!r}")
        total: int = getattr(summary, indicator)
        return float(total)

    if scope == WHOLE_MATCH:
        raise KeyError(f"{indicator!r} es de un equipo, no del partido entero")

    counters: Mapping[str, float] = getattr(summary, indicator)
    return float(counters[scope])


def explain(state: LiveMatchState, indicator: str, scope: str) -> Explanation:
    """Explica un indicador del estado vivo.

    Args:
        state: Estado del que sale el número.
        indicator: Nombre del indicador, tal como lo nombra ``MatchSummary``.
        scope: Equipo, o ``WHOLE_MATCH`` para los del partido entero.

    Returns:
        El valor, su procedencia y las versiones bajo las que se calculó.
    """
    return Explanation(
        indicator=indicator,
        scope=scope,
        value=_value(state.summary(), indicator, scope),
        contract_version=MATCH_CONTRACT_VERSION,
        model_versions=MODELS_BY_INDICATOR.get(indicator, {}),
        lineage=state.lineage(indicator, scope),
    )


def audit(
    state: LiveMatchState, scope: str = "match", produced_at: datetime | None = None
) -> AuditTrail:
    """Explica todos los indicadores del partido.

    Recorre los indicadores declarados y no los linajes acumulados, de modo que
    un indicador que vale cero también quede explicado: cero tarjetas rojas es
    una respuesta legítima y su linaje es el conjunto vacío. Omitirlo dejaría un
    número visible sin procedencia, que es justo lo que esta historia persigue.

    Args:
        state: Estado del que salen los números.
        scope: Cómo se llama lo auditado.
        produced_at: Instante de la auditoría. Se inyecta para que un informe
            sea reproducible en una prueba.

    Returns:
        La auditoría completa.
    """
    summary = state.summary()
    explanations = [explain(state, indicator, WHOLE_MATCH) for indicator in MATCH_INDICATORS]
    explanations.extend(
        explain(state, indicator, team) for indicator in TEAM_INDICATORS for team in summary.goals
    )

    return AuditTrail(
        scope=scope,
        produced_at=produced_at or utc_now(),
        explanations=tuple(explanations),
    )
