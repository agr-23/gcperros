"""Marco de reglas de calidad (HU-17).

Dos de estas pruebas son el corazón de la historia: las que impiden que una
dimensión se mida sobre el sitio equivocado y salga bien por construcción.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from gcperros.engine.dedup import DedupStats
from gcperros.engine.pipeline import MatchEngine
from gcperros.engine.watermark import WatermarkStats
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.perturbation import inject_disorder, inject_duplicates
from gcperros.governance.gate import GateStats, match_event_gate
from gcperros.governance.quality import (
    APPLICATION_TIMELINESS,
    CONTRACT_CONFORMITY,
    DEFAULT_RULES,
    DELIVERY_UNIQUENESS,
    IngestionEvidence,
    QualityDimension,
    QualityMeasurement,
    QualityReport,
    QualityRule,
    assess,
)
from gcperros.governance.quarantine import InMemoryInvalidStore

MEASURED_AT = datetime(2026, 8, 26, 20, 0, 0, 500000, tzinfo=UTC)
CONFIG = MatchConfig(match_id="match-0017", home_team="RMA", away_team="BAR")


def _gate(admitted: int, rejected: int, by_rule: dict[str, int] | None = None) -> GateStats:
    return GateStats(admitted=admitted, rejected=rejected, by_rule=by_rule or {})


def _dedup(accepted: int, duplicates: int) -> DedupStats:
    return DedupStats(accepted=accepted, duplicates=duplicates, forgotten=0)


def _watermark(released: int, dropped: int) -> WatermarkStats:
    return WatermarkStats(
        released=released,
        dropped_late=dropped,
        max_lateness_s=0.0,
        total_lateness_s=0.0,
        max_buffered=0,
    )


###############################################################################
# Lo que esta historia existe para evitar
###############################################################################


def test_completeness_counts_what_was_rejected_too() -> None:
    """Medir solo sobre lo admitido daría el cien por cien por construcción.

    Lo incompleto lo rechaza la propia frontera (HU-16), así que una regla que
    mirase solo lo que entró estaría midiendo su propio filtro.
    """
    report = assess("x", IngestionEvidence(gate=_gate(admitted=90, rejected=10)))

    (completeness,) = [
        m for m in report.measurements if m.rule.dimension is QualityDimension.COMPLETENESS
    ]
    assert completeness.total == 100
    assert completeness.value == 0.9
    assert not completeness.passed


def test_uniqueness_measures_the_delivered_stream_not_the_deduplicated_one() -> None:
    """Contar identificadores después de deduplicar daría siempre uno."""
    report = assess("x", IngestionEvidence(dedup=_dedup(accepted=90, duplicates=10)))

    (uniqueness,) = report.measurements
    assert uniqueness.total == 100
    assert uniqueness.value == 0.9


###############################################################################
# La medición
###############################################################################


def test_a_measurement_keeps_its_numerator_and_denominator() -> None:
    """9 de 10 y 900 de 1.000 dan el mismo 0,9 y no merecen la misma confianza."""
    small = QualityMeasurement(CONTRACT_CONFORMITY, observed=9, total=10)
    large = QualityMeasurement(CONTRACT_CONFORMITY, observed=900, total=1000)

    assert small.value == large.value
    assert (small.total, large.total) == (10, 1000)


def test_an_empty_stream_does_not_look_like_a_breakdown() -> None:
    assert QualityMeasurement(CONTRACT_CONFORMITY, observed=0, total=0).value == 1.0


def test_a_measurement_exactly_at_the_threshold_passes() -> None:
    rule = QualityRule("r", QualityDimension.COMPLETENESS, 0.95, "prueba")

    assert QualityMeasurement(rule, observed=95, total=100).passed


def test_a_measurement_below_the_threshold_fails() -> None:
    rule = QualityRule("r", QualityDimension.COMPLETENESS, 0.95, "prueba")

    assert not QualityMeasurement(rule, observed=94, total=100).passed


###############################################################################
# El informe
###############################################################################


def test_the_report_evaluates_every_rule_it_has_data_for() -> None:
    evidence = IngestionEvidence(
        gate=_gate(100, 0), dedup=_dedup(100, 0), watermark=_watermark(100, 0)
    )

    report = assess("partido", evidence, measured_at=MEASURED_AT)

    assert len(report.measurements) == len(DEFAULT_RULES)
    assert report.passed
    assert report.failures == ()
    assert report.unmeasured == ()


def test_a_dimension_without_data_is_named_not_assumed_good() -> None:
    """No medido no es lo mismo que aprobado."""
    report = assess("cuotas", IngestionEvidence(gate=_gate(100, 0)))

    assert report.unmeasured == ("uniqueness", "timeliness")
    assert [m.rule.dimension for m in report.measurements] == [QualityDimension.COMPLETENESS]


def test_an_empty_evidence_measures_nothing_and_claims_nothing() -> None:
    report = assess("nada", IngestionEvidence())

    assert report.measurements == ()
    assert len(report.unmeasured) == len(DEFAULT_RULES)


def test_one_failing_rule_sinks_the_whole_report() -> None:
    evidence = IngestionEvidence(
        gate=_gate(50, 50), dedup=_dedup(100, 0), watermark=_watermark(100, 0)
    )

    report = assess("partido", evidence)

    assert not report.passed
    assert [m.rule.name for m in report.failures] == ["contract_conformity"]


def test_the_report_carries_the_diagnosis_not_just_the_verdict() -> None:
    """Saber que la completitud falló no dice qué arreglar; los motivos sí."""
    evidence = IngestionEvidence(gate=_gate(8, 2, {"missing_field": 2}))

    assert assess("x", evidence).rejections_by_rule == {"missing_field": 2}


def test_the_report_is_timestamped_so_it_can_form_a_series() -> None:
    """Sin serie, la calidad vuelve a ser una auditoría suelta."""
    assert assess("x", IngestionEvidence(), measured_at=MEASURED_AT).measured_at == MEASURED_AT


def test_the_clock_defaults_to_now_when_nobody_pins_it() -> None:
    assert assess("x", IngestionEvidence()).measured_at.tzinfo is not None


###############################################################################
# Serialización
###############################################################################


def test_the_report_serialises_to_a_stable_line() -> None:
    evidence = IngestionEvidence(gate=_gate(99, 1, {"wrong_type": 1}))
    report = assess("partido", evidence, measured_at=MEASURED_AT)

    assert report.to_json() == assess("partido", evidence, measured_at=MEASURED_AT).to_json()


def test_the_serialised_report_keeps_its_keys_sorted() -> None:
    payload = json.loads(assess("x", IngestionEvidence(), measured_at=MEASURED_AT).to_json())

    assert list(payload) == sorted(payload)


def test_the_serialised_report_says_what_it_measured_and_against_what() -> None:
    evidence = IngestionEvidence(gate=_gate(90, 10))
    payload = json.loads(assess("partido", evidence, measured_at=MEASURED_AT).to_json())

    assert payload["scope"] == "partido"
    assert payload["measured_at"] == "2026-08-26T20:00:00.500Z"
    assert payload["passed"] is False

    (measurement,) = payload["measurements"]
    assert measurement["dimension"] == "completeness"
    assert measurement["value"] == 0.9
    assert measurement["minimum"] == 0.99
    assert measurement["observed"] == 90
    assert measurement["total"] == 100


###############################################################################
# Las reglas del proyecto
###############################################################################


def test_every_rule_explains_its_threshold() -> None:
    """Un umbral sin justificación es indistinguible de un número inventado."""
    for rule in DEFAULT_RULES:
        assert rule.rationale.strip()
        assert 0.0 < rule.minimum <= 1.0


def test_the_three_rules_cover_the_three_dimensions() -> None:
    assert {rule.dimension for rule in DEFAULT_RULES} == set(QualityDimension)


def test_the_timeliness_threshold_is_the_one_the_project_declares() -> None:
    """El OE-2 declara 0,95, y es el mismo que sostiene el margen de la HU-12."""
    assert APPLICATION_TIMELINESS.minimum == 0.95


def test_the_uniqueness_threshold_sits_below_the_measured_floor() -> None:
    """El umbral queda por debajo del peor caso observado, a propósito.

    Con el inyector en su 5 % por defecto, ocho partidos dieron entre 0,942 y
    0,955. El umbral acota lo anormal, no la adversidad que el propio proyecto
    se impone.
    """
    assert DELIVERY_UNIQUENESS.minimum < 0.942


###############################################################################
# Sobre una ingestión de verdad
###############################################################################


def test_a_clean_match_passes_every_rule() -> None:
    events = simulate_match(20260826, CONFIG)
    gate = match_event_gate(InMemoryInvalidStore())
    engine = MatchEngine()
    for event in events:
        admitted = gate.admit(event.to_json())
        assert admitted is not None
        engine.process(admitted)
    engine.flush()

    report = assess(
        "match-events",
        IngestionEvidence(gate.stats, engine.dedup_stats, engine.watermark_stats),
        measured_at=MEASURED_AT,
    )

    assert report.passed
    assert all(m.value == 1.0 for m in report.measurements)


@pytest.mark.statistical
def test_the_projects_own_adversity_still_clears_the_thresholds() -> None:
    """Los umbrales acotan lo anormal, no la adversidad que el proyecto se impone.

    Si esta prueba falla, o bien alguien endureció un umbral sin evidencia, o
    bien el inyector de perturbaciones dejó de representar a un broker real.
    """
    for seed in range(8):
        events = simulate_match(seed, CONFIG)
        delivered, _ = inject_duplicates(events, seed=seed)
        delivered, _ = inject_disorder(delivered, seed=seed)

        gate = match_event_gate(InMemoryInvalidStore())
        engine = MatchEngine()
        for event in delivered:
            admitted = gate.admit(event.to_json())
            assert admitted is not None
            engine.process(admitted)
        engine.flush()

        report = assess(
            f"semilla-{seed}",
            IngestionEvidence(gate.stats, engine.dedup_stats, engine.watermark_stats),
        )
        assert report.passed, f"semilla {seed}: {[m.to_dict() for m in report.failures]}"


def test_garbage_in_the_stream_shows_up_as_lost_completeness() -> None:
    events = simulate_match(20260826, CONFIG)
    delivered = [event.to_json() for event in events[:100]] + ["{basura", "[1,2]"]

    gate = match_event_gate(InMemoryInvalidStore())
    gate.admit_all(delivered)

    report: QualityReport = assess("match-events", IngestionEvidence(gate=gate.stats))
    (completeness,) = report.measurements

    assert completeness.total == 102
    assert completeness.observed == 100
    assert set(report.rejections_by_rule) == {"malformed_json", "not_an_object"}
