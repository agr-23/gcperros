"""El motor bajo entrega duplicada (HU-11).

La promesa de la historia, literal: que la garantía *al menos una vez* del
broker no se convierta en un gol contado dos veces ni en una posesión inflada.
"""

from __future__ import annotations

import pytest

from gcperros.core.contracts import MatchEvent
from gcperros.core.stats import summarize_events, teams_in_order
from gcperros.engine.pipeline import MatchEngine, Outcome
from gcperros.engine.state import LiveMatchState
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.perturbation import inject_disorder, inject_duplicates

CONFIG = MatchConfig(match_id="match-0011", home_team="RMA", away_team="BAR")
SEED = 20260826


@pytest.fixture(scope="module")
def clean() -> list[MatchEvent]:
    return simulate_match(SEED, CONFIG)


def _repeat_every(events: list[MatchEvent], event_type: str) -> list[MatchEvent]:
    """Reentrega cada evento del tipo indicado, justo detrás del original."""
    delivered: list[MatchEvent] = []
    for event in events:
        delivered.append(event)
        if event.event_type == event_type:
            delivered.append(event)
    return delivered


###############################################################################
# La promesa de la historia
###############################################################################


def test_a_duplicated_goal_is_not_counted_twice(clean: list[MatchEvent]) -> None:
    reference = summarize_events(clean)
    assert sum(reference.goals.values()) > 0, "la semilla debe producir goles"

    delivered = _repeat_every(clean, "goal")

    # Sin deduplicar, el marcador se dispara: la prueba no es vacía.
    assert summarize_events(delivered).goals != reference.goals

    assert MatchEngine().process_all(delivered).summary.goals == reference.goals


def test_a_duplicated_possession_change_does_not_inflate_possession(
    clean: list[MatchEvent],
) -> None:
    reference = summarize_events(clean)
    delivered = _repeat_every(clean, "possession_change")

    assert summarize_events(delivered).possessions != reference.possessions
    assert MatchEngine().process_all(delivered).summary.possessions == reference.possessions


def test_a_duplicated_shot_does_not_inflate_expected_goals(clean: list[MatchEvent]) -> None:
    """El xG acumulado es una suma: duplicar un remate lo contamina dos veces."""
    reference = summarize_events(clean)
    delivered = _repeat_every(clean, "shot")

    assert summarize_events(delivered).total_xg != reference.total_xg
    assert MatchEngine().process_all(delivered).summary.total_xg == reference.total_xg


def test_every_event_type_survives_being_duplicated(clean: list[MatchEvent]) -> None:
    reference = summarize_events(clean)

    for event_type in ("pass", "shot", "goal", "foul", "possession_change"):
        result = MatchEngine().process_all(_repeat_every(clean, event_type))
        assert result.summary == reference, f"falla al duplicar {event_type}"


###############################################################################
# Perturbación aleatoria contra la referencia batch (semilla del OE-2)
###############################################################################


@pytest.mark.parametrize("perturbation_seed", [1, 7, 99, 2026])
@pytest.mark.parametrize("rate", [0.02, 0.1, 0.4])
def test_engine_matches_the_batch_reference(
    clean: list[MatchEvent], perturbation_seed: int, rate: float
) -> None:
    delivered, report = inject_duplicates(clean, seed=perturbation_seed, rate=rate)
    result = MatchEngine().process_all(delivered)

    assert result.summary == summarize_events(clean)
    assert result.dedup.duplicates == report.injected
    assert result.dedup.accepted == report.original_count


def test_a_stream_delivered_twice_in_full_changes_nothing(clean: list[MatchEvent]) -> None:
    """Caso extremo: el broker reentrega el partido entero."""
    engine = MatchEngine()
    engine.process_all(clean)
    engine.process_all(clean)

    assert engine.result().summary == summarize_events(clean)
    assert engine.dedup_stats.duplicates == len(clean)


def test_process_reports_what_it_did_with_the_event(clean: list[MatchEvent]) -> None:
    engine = MatchEngine()
    first = clean[0]

    assert engine.process(first) is Outcome.ACCEPTED
    assert engine.process(first) is Outcome.DUPLICATE


def test_deduplication_happens_before_the_state(clean: list[MatchEvent]) -> None:
    """El contador de eventos del estado sólo ve lo que sobrevivió al filtro."""
    delivered, report = inject_duplicates(clean, seed=5, rate=0.3)
    engine = MatchEngine()
    engine.process_all(delivered)

    assert engine.state.summary().event_count == report.original_count
    assert engine.state.summary().event_count < len(delivered)


###############################################################################
# Equivalencia entre el plano en streaming y el plano batch
###############################################################################


@pytest.mark.parametrize("seed", [0, 3, 11, 42])
def test_incremental_and_batch_agree_on_a_clean_stream(seed: int) -> None:
    events = simulate_match(seed, CONFIG)

    state = LiveMatchState()
    for event in events:
        state.apply(event)

    assert state.summary() == summarize_events(events)


def test_an_empty_stream_yields_an_empty_state() -> None:
    result = MatchEngine().process_all([])

    assert result.summary.event_count == 0
    assert result.summary.goals == {}
    assert result.dedup.seen == 0


###############################################################################
# Orden de equipos — reproducibilidad de la serialización
###############################################################################


def test_teams_keep_their_order_of_appearance(clean: list[MatchEvent]) -> None:
    """El orden no puede depender del `hash` de la cadena.

    Un conjunto se recorre en un orden que cambia con ``PYTHONHASHSEED``, así que
    las claves del resumen saldrían distintas en cada proceso y su serialización
    dejaría de ser idéntica byte a byte.
    """
    assert teams_in_order(clean) == [CONFIG.home_team, CONFIG.away_team]

    keys = list(summarize_events(clean).goals)
    assert keys == [CONFIG.home_team, CONFIG.away_team]


def test_state_learns_the_teams_from_the_stream(clean: list[MatchEvent]) -> None:
    state = LiveMatchState()
    for event in clean:
        state.apply(event)

    assert list(state.summary().goals) == [CONFIG.home_team, CONFIG.away_team]


###############################################################################
# Desorden de red (HU-12)
###############################################################################


def test_disorder_alone_does_not_corrupt_the_state(clean: list[MatchEvent]) -> None:
    """Con margen suficiente, un flujo desordenado da el mismo resultado."""
    delivered, report = inject_disorder(clean, seed=7)
    assert not report.is_ordered, "la perturbación tiene que desordenar algo"

    result = MatchEngine(allowed_lateness_s=30.0).process_all(delivered)
    assert result.summary == summarize_events(clean)
    assert result.watermark.dropped_late == 0


def test_disorder_and_duplication_together(clean: list[MatchEvent]) -> None:
    """Las dos perturbaciones a la vez, que es lo que hace un broker real."""
    duplicated, duplication = inject_duplicates(clean, seed=3, rate=0.15)
    delivered, _ = inject_disorder(duplicated, seed=11)

    result = MatchEngine(allowed_lateness_s=30.0).process_all(delivered)

    assert result.summary == summarize_events(clean)
    assert result.dedup.duplicates == duplication.injected


def test_a_late_event_is_recorded_not_silently_lost(clean: list[MatchEvent]) -> None:
    """La distinción que pide la historia: descartado por tardío, no perdido."""
    delivered, _ = inject_disorder(clean, seed=7)

    engine = MatchEngine(allowed_lateness_s=0.0)
    outcomes = [engine.process(event) for event in delivered]
    engine.flush()

    late = [outcome for outcome in outcomes if outcome is Outcome.DROPPED_LATE]
    assert late, "con margen cero tiene que haber rezagados"

    stats = engine.watermark_stats
    assert stats.dropped_late == len(late)
    assert stats.seen == len(delivered)
    # Todo evento entregado acabó contado en una de las dos cuentas: ninguno se
    # evaporó sin dejar rastro.
    assert stats.released + stats.dropped_late == len(delivered)


def test_lateness_is_quantified_for_the_audit(clean: list[MatchEvent]) -> None:
    delivered, _ = inject_disorder(clean, seed=7)
    engine = MatchEngine(allowed_lateness_s=0.0)
    engine.process_all(delivered)

    stats = engine.watermark_stats
    assert stats.max_lateness_s > 0.0
    assert 0.0 < stats.mean_lateness_s <= stats.max_lateness_s


def test_a_wider_margin_sacrifices_less_information(clean: list[MatchEvent]) -> None:
    """La perilla que gradúa latencia contra completitud, comprobada."""
    delivered, _ = inject_disorder(clean, seed=7)

    timeliness = [
        MatchEngine(allowed_lateness_s=margin).process_all(delivered).watermark.timeliness
        for margin in (0.0, 1.0, 5.0, 20.0)
    ]

    assert timeliness == sorted(timeliness)
    assert timeliness[-1] == 1.0


def test_the_default_margin_meets_the_declared_thresholds() -> None:
    """El proyecto declara <1 % en posesión, <0,05 en xG y >=95 % de oportunidad."""
    config = MatchConfig(match_id="match-0012", home_team="RMA", away_team="BAR")

    for seed in range(6):
        events = simulate_match(seed, config)
        reference = summarize_events(events)
        delivered, _ = inject_disorder(events, seed=7)

        result = MatchEngine().process_all(delivered)

        assert result.watermark.timeliness >= 0.95

        possessions = sum(reference.possessions.values())
        divergence = abs(possessions - sum(result.summary.possessions.values())) / possessions
        assert divergence < 0.01

        for team, value in reference.total_xg.items():
            assert abs(value - result.summary.total_xg.get(team, 0.0)) < 0.05


def test_pending_events_are_not_counted_until_released(clean: list[MatchEvent]) -> None:
    engine = MatchEngine(allowed_lateness_s=30.0)
    for event in clean[:20]:
        engine.process(event)

    assert engine.pending > 0
    assert engine.result().summary.event_count < 20

    engine.flush()
    assert engine.pending == 0
    assert engine.result().summary.event_count == 20
