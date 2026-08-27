"""Auditoría de los indicadores (HU-18).

La promesa de la historia: que cualquier número que el sistema muestre se pueda
explicar a demanda —qué eventos lo formaron, qué modelo lo calculó, bajo qué
contrato llegaron— en vez de ser una caja negra que solo el equipo de desarrollo
sabe abrir.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from gcperros.core import odds, xg
from gcperros.core.contracts import MATCH_CONTRACT_VERSION, MatchEvent
from gcperros.core.lineage import EMPTY_DIGEST
from gcperros.core.stats import summarize_events
from gcperros.engine.pipeline import MatchEngine
from gcperros.engine.state import WHOLE_MATCH
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.perturbation import inject_disorder, inject_duplicates
from gcperros.governance.traceability import (
    MATCH_INDICATORS,
    MODEL_VERSIONS,
    MODELS_BY_INDICATOR,
    TEAM_INDICATORS,
    audit,
    explain,
)

CONFIG = MatchConfig(match_id="match-0018", home_team="RMA", away_team="BAR")
SEED = 20260826
PRODUCED_AT = datetime(2026, 8, 26, 21, 0, 0, 750000, tzinfo=UTC)


@pytest.fixture(scope="module")
def match() -> list[MatchEvent]:
    return simulate_match(SEED, CONFIG)


@pytest.fixture(scope="module")
def engine(match: list[MatchEvent]) -> MatchEngine:
    played = MatchEngine()
    played.process_all(match)
    return played


###############################################################################
# Explicar un número
###############################################################################


def test_an_indicator_reports_the_value_the_summary_shows(
    engine: MatchEngine, match: list[MatchEvent]
) -> None:
    """Si la explicación no coincidiera con el número mostrado, explicaría otra cosa."""
    explanation = explain(engine.state, "total_xg", "RMA")

    assert explanation.value == summarize_events(match).total_xg["RMA"]


def test_an_indicator_is_traced_to_the_events_that_formed_it(
    engine: MatchEngine, match: list[MatchEvent]
) -> None:
    shots = [event for event in match if event.event_type == "shot" and event.team == "RMA"]

    assert explain(engine.state, "total_xg", "RMA").lineage.event_count == len(shots)


def test_the_sample_points_at_events_that_really_exist(
    engine: MatchEngine, match: list[MatchEvent]
) -> None:
    """Sirve para comprobar a mano contra la capa Raw, así que tiene que resolver."""
    emitted = {event.event_id for event in match}

    assert set(explain(engine.state, "goals", "RMA").lineage.sample) <= emitted


def test_the_explanation_names_the_contract_the_events_arrived_under(
    engine: MatchEngine,
) -> None:
    assert explain(engine.state, "goals", "RMA").contract_version == MATCH_CONTRACT_VERSION


def test_an_indicator_worth_zero_is_still_explained(engine: MatchEngine) -> None:
    """Un número visible sin procedencia es justo lo que la historia persigue."""
    explanation = explain(engine.state, "red_cards", "RMA")

    assert explanation.value == 0.0
    assert explanation.lineage.event_count == 0
    assert explanation.lineage.digest == EMPTY_DIGEST


###############################################################################
# Las versiones de modelo
###############################################################################


def test_the_expected_goals_indicator_carries_the_model_that_computed_it(
    engine: MatchEngine,
) -> None:
    assert explain(engine.state, "total_xg", "RMA").model_versions == {"xg": xg.MODEL_VERSION}


def test_a_plain_count_declares_no_model(engine: MatchEngine) -> None:
    """Estampar una versión sobre un recuento sería una mentira cómoda."""
    assert explain(engine.state, "goals", "RMA").model_versions == {}


def test_only_indicators_with_a_model_behind_them_declare_one() -> None:
    assert set(MODELS_BY_INDICATOR) == {"total_xg"}


def test_the_project_models_are_versioned() -> None:
    assert MODEL_VERSIONS == {"xg": xg.MODEL_VERSION, "odds": odds.MODEL_VERSION}
    assert all(version.strip() for version in MODEL_VERSIONS.values())


###############################################################################
# La auditoría completa
###############################################################################


def test_every_indicator_of_the_summary_gets_explained(engine: MatchEngine) -> None:
    trail = audit(engine.state, produced_at=PRODUCED_AT)

    expected = len(MATCH_INDICATORS) + len(TEAM_INDICATORS) * 2
    assert len(trail.explanations) == expected


def test_the_audit_can_be_asked_for_one_indicator(engine: MatchEngine) -> None:
    trail = audit(engine.state, produced_at=PRODUCED_AT)

    assert trail.of("total_xg", "RMA").value == explain(engine.state, "total_xg", "RMA").value


def test_asking_for_something_that_was_not_audited_fails_loudly(engine: MatchEngine) -> None:
    with pytest.raises(KeyError):
        audit(engine.state, produced_at=PRODUCED_AT).of("corners", "RMA")


def test_the_match_wide_indicator_is_not_attributed_to_a_team(engine: MatchEngine) -> None:
    trail = audit(engine.state, produced_at=PRODUCED_AT)

    assert trail.of("event_count", WHOLE_MATCH).value == engine.state.summary().event_count


def test_the_audit_is_timestamped(engine: MatchEngine) -> None:
    assert audit(engine.state, produced_at=PRODUCED_AT).produced_at == PRODUCED_AT


def test_the_clock_defaults_to_now_when_nobody_pins_it(engine: MatchEngine) -> None:
    assert audit(engine.state).produced_at.tzinfo is not None


###############################################################################
# La propiedad que sostiene el diseño
###############################################################################


def test_the_lineage_survives_a_hostile_broker(match: list[MatchEvent]) -> None:
    """Duplicados y desorden no cambian ni un número ni su procedencia.

    Es lo que hace que la huella sirva para auditar: si dependiera del orden de
    llegada, dos derivaciones del mismo partido darían huellas distintas y no se
    podría comprobar nada contra el origen.
    """
    delivered, _ = inject_duplicates(match, seed=7)
    delivered, _ = inject_disorder(delivered, seed=7)

    clean = MatchEngine()
    clean.process_all(match)
    hostile = MatchEngine()
    hostile.process_all(delivered)

    assert audit(hostile.state).digests == audit(clean.state).digests


@pytest.mark.parametrize("perturbation_seed", [1, 13, 99])
def test_re_deriving_the_match_reproduces_its_digests(
    match: list[MatchEvent], perturbation_seed: int
) -> None:
    """La re-derivación verificable es lo que sustituye a guardar el linaje entero."""
    delivered, _ = inject_disorder(match, seed=perturbation_seed)

    first = MatchEngine()
    first.process_all(match)
    again = MatchEngine()
    again.process_all(delivered)

    assert (
        again.state.lineage("total_xg", "RMA").digest
        == first.state.lineage("total_xg", "RMA").digest
    )


def test_two_different_matches_do_not_share_a_digest() -> None:
    first = MatchEngine()
    first.process_all(simulate_match(1, CONFIG))
    second = MatchEngine()
    second.process_all(simulate_match(2, CONFIG))

    assert (
        first.state.lineage("total_xg", "RMA").digest
        != second.state.lineage("total_xg", "RMA").digest
    )


###############################################################################
# Serialización
###############################################################################


def test_the_audit_serialises_to_a_stable_line(engine: MatchEngine) -> None:
    first = audit(engine.state, produced_at=PRODUCED_AT).to_json()

    assert first == audit(engine.state, produced_at=PRODUCED_AT).to_json()


def test_the_serialised_audit_keeps_its_keys_sorted(engine: MatchEngine) -> None:
    payload = json.loads(audit(engine.state, produced_at=PRODUCED_AT).to_json())

    assert list(payload) == sorted(payload)
    assert payload["produced_at"] == "2026-08-26T21:00:00.750Z"


def test_the_serialised_explanation_answers_the_three_questions(engine: MatchEngine) -> None:
    payload = json.loads(explain(engine.state, "total_xg", "RMA").to_json())

    assert payload["lineage"]["event_count"] > 0
    assert payload["model_versions"] == {"xg": xg.MODEL_VERSION}
    assert payload["contract_version"] == MATCH_CONTRACT_VERSION


#: Semilla cuyo partido sí tiene expulsión. Una roja ocurre en uno de cada
#: cuatro encuentros, y el de referencia no trae ninguna.
SEED_WITH_RED_CARD = 10


def test_a_red_card_is_traced_like_any_other_indicator() -> None:
    """Es el evento que más mueve el mercado; su procedencia no puede faltar."""
    events = simulate_match(SEED_WITH_RED_CARD, CONFIG)
    sent_off = [event for event in events if event.event_type == "red_card"]
    assert sent_off, "la semilla dejó de producir expulsiones"

    played = MatchEngine()
    played.process_all(events)

    traced = sum(
        explain(played.state, "red_cards", team).lineage.event_count for team in ("RMA", "BAR")
    )
    assert traced == len(sent_off)
