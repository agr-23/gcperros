"""Cada número del baloncesto, pulsable con su huella (#89, HU-15 y HU-18)."""

from __future__ import annotations

from datetime import UTC, datetime

from gcperros.core.contracts import MatchEvent
from gcperros.engine.basketball_state import BasketballLiveState, basketball_engine
from gcperros.engine.state import WHOLE_MATCH
from gcperros.firestore.document import LiveMatchDocument
from gcperros.generators.basketball import BasketballConfig, simulate_basketball
from gcperros.generators.perturbation import inject_disorder, inject_duplicates
from gcperros.governance.traceability import audit, explain

CONFIG = BasketballConfig(home_team="BOS", away_team="LAL")
NOW = datetime(2026, 11, 12, 22, 0, tzinfo=UTC)
WITHIN_LATENESS_S = 9.0


def _match(seed: int) -> list[MatchEvent]:
    return simulate_basketball(seed, CONFIG)


def _adverse(events: list[MatchEvent], seed: int, max_delay_s: float) -> list[MatchEvent]:
    duplicated, _ = inject_duplicates(events, seed)
    disordered, _ = inject_disorder(duplicated, seed, max_delay_s=max_delay_s)
    return disordered


def test_the_lineage_fingerprint_does_not_depend_on_delivery_order() -> None:
    """La huella del marcador es la misma llegue como llegue el partido."""
    events = _match(5)
    clean = basketball_engine()
    clean.process_all(events)
    adverse = basketball_engine()
    adverse.process_all(_adverse(events, 5, WITHIN_LATENESS_S))

    for team in ("BOS", "LAL"):
        for indicator in BasketballLiveState.team_indicators:
            assert adverse.state.lineage(indicator, team) == clean.state.lineage(indicator, team)
    assert adverse.state.lineage("event_count", WHOLE_MATCH).event_count == len(events)


def test_every_point_traces_back_to_the_baskets_that_scored_it() -> None:
    events = _match(7)
    engine = basketball_engine()
    result = engine.process_all(events)

    for team in ("BOS", "LAL"):
        scoring = [e for e in events if e.team == team and e.attrs.get("made") is True]
        record = engine.state.lineage("points", team)
        assert record.event_count == len(scoring)
        assert result.summary.points[team] > 0


def test_expected_points_carry_their_model_version() -> None:
    models = BasketballLiveState.models_by_indicator

    assert models["expected_points"] == {"expected_points": "ep-1.0.0"}
    assert "points" not in models, "contar canastas no usa ningún modelo"


def test_the_audit_explains_every_basketball_indicator() -> None:
    engine = basketball_engine()
    engine.process_all(_match(4))

    trail = audit(engine.state, produced_at=NOW)

    explained = {(e.indicator, e.scope) for e in trail.explanations}
    expected = {(i, t) for i in BasketballLiveState.team_indicators for t in ("BOS", "LAL")}
    assert expected | {("event_count", WHOLE_MATCH)} == explained


def test_an_explanation_says_which_contract_and_model_produced_the_number() -> None:
    engine = basketball_engine()
    result = engine.process_all(_match(4))

    points = explain(engine.state, "points", "BOS")
    expected = explain(engine.state, "expected_points", "BOS")

    assert points.value == result.summary.points["BOS"]
    assert points.model_versions == {}
    assert expected.model_versions == {"expected_points": "ep-1.0.0"}
    assert points.contract_version == "v1"


def test_the_live_document_carries_the_basketball_indicators() -> None:
    engine = basketball_engine()
    result = engine.process_all(_match(6))

    document = LiveMatchDocument.project_state("bkb-6", engine.state, NOW)

    assert document.teams == engine.state.teams
    assert document.event_count == result.summary.event_count
    for team in ("BOS", "LAL"):
        assert document.indicators[team]["points"] == result.summary.points[team]
        assert set(document.indicators[team]) == set(BasketballLiveState.team_indicators)
    assert "goals" not in document.indicators["BOS"]
