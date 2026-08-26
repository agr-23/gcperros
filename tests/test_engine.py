"""El motor bajo entrega duplicada (HU-11).

La promesa de la historia, literal: que la garantía *al menos una vez* del
broker no se convierta en un gol contado dos veces ni en una posesión inflada.
"""

from __future__ import annotations

import pytest

from gcperros.core.contracts import MatchEvent
from gcperros.core.stats import summarize_events, teams_in_order
from gcperros.engine.pipeline import MatchEngine
from gcperros.engine.state import LiveMatchState
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.perturbation import inject_duplicates

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


def test_process_reports_whether_the_event_was_applied(clean: list[MatchEvent]) -> None:
    engine = MatchEngine()
    first = clean[0]

    assert engine.process(first) is True
    assert engine.process(first) is False


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
