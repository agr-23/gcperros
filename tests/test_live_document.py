"""La forma exacta del documento de estado vivo (HU-15)."""

from __future__ import annotations

from datetime import UTC, datetime

from gcperros.core.stats import MatchSummary
from gcperros.firestore.document import LiveMatchDocument

FIXED_INSTANT = datetime(2026, 8, 27, 21, 0, 0, tzinfo=UTC)

SUMMARY = MatchSummary(
    event_count=214,
    goals={"RMA": 2, "BAR": 1},
    shots={"RMA": 9, "BAR": 6},
    total_xg={"RMA": 1.83, "BAR": 0.9421},
    passes={"RMA": 340, "BAR": 355},
    completed_passes={"RMA": 298, "BAR": 312},
    fouls={"RMA": 5, "BAR": 7},
    red_cards={"RMA": 0, "BAR": 1},
    possessions={"RMA": 41, "BAR": 39},
)


def test_the_document_nests_indicators_by_team() -> None:
    document = LiveMatchDocument.project("match-0001", ["RMA", "BAR"], SUMMARY, FIXED_INSTANT)

    assert document.indicators["RMA"] == {
        "goals": 2,
        "shots": 9,
        "total_xg": 1.83,
        "passes": 340,
        "completed_passes": 298,
        "fouls": 5,
        "red_cards": 0,
        "possessions": 41,
    }
    assert document.indicators["BAR"]["goals"] == 1


def test_the_team_order_is_preserved_and_not_alphabetized() -> None:
    """El orden es el de aparición en el flujo, no un criterio propio del documento."""
    document = LiveMatchDocument.project("match-0001", ["BAR", "RMA"], SUMMARY, FIXED_INSTANT)

    assert document.teams == ("BAR", "RMA")


def test_the_firestore_document_carries_the_match_envelope() -> None:
    document = LiveMatchDocument.project("match-0001", ["RMA", "BAR"], SUMMARY, FIXED_INSTANT)

    row = document.to_firestore_document()

    assert row["match_id"] == "match-0001"
    assert row["teams"] == ["RMA", "BAR"]
    assert row["event_count"] == 214
    assert row["updated_at"] == "2026-08-27T21:00:00.000Z"
    assert isinstance(row["indicators"], dict)


def test_updated_at_is_the_publication_time_not_an_event_time() -> None:
    """Dos proyecciones del mismo resumen en instantes distintos difieren sólo en eso."""
    later = datetime(2026, 8, 27, 21, 0, 5, tzinfo=UTC)

    first = LiveMatchDocument.project("match-0001", ["RMA", "BAR"], SUMMARY, FIXED_INSTANT)
    second = LiveMatchDocument.project("match-0001", ["RMA", "BAR"], SUMMARY, later)

    assert first.indicators == second.indicators
    assert first.updated_at != second.updated_at


def test_a_team_with_no_events_yet_still_gets_zeroed_indicators() -> None:
    empty_summary = MatchSummary(
        event_count=0,
        goals={"RMA": 0, "BAR": 0},
        shots={"RMA": 0, "BAR": 0},
        total_xg={"RMA": 0.0, "BAR": 0.0},
        passes={"RMA": 0, "BAR": 0},
        completed_passes={"RMA": 0, "BAR": 0},
        fouls={"RMA": 0, "BAR": 0},
        red_cards={"RMA": 0, "BAR": 0},
        possessions={"RMA": 0, "BAR": 0},
    )

    document = LiveMatchDocument.project("match-0002", ["RMA", "BAR"], empty_summary, FIXED_INSTANT)

    assert document.indicators["RMA"]["goals"] == 0
    assert document.event_count == 0
