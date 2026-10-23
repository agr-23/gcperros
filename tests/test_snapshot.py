"""La instantánea del estado vivo con la forma del documento de Firestore (#30)."""

from __future__ import annotations

import pytest

from gcperros.core.contracts import MatchEvent
from gcperros.core.stats import summarize_events
from gcperros.demo.replay import MatchReplay
from gcperros.demo.snapshot import take_snapshot
from gcperros.generators.match import MatchConfig, simulate_match

CONFIG = MatchConfig(match_id="match-0030", home_team="RMA", away_team="BAR")


@pytest.fixture(scope="module")
def match() -> list[MatchEvent]:
    return simulate_match(20260826, CONFIG)


def test_the_firestore_document_travels_intact(match: list[MatchEvent]) -> None:
    replay = MatchReplay(match)
    replay.advance_to(10 * 60)
    snapshot = take_snapshot(replay)
    payload = snapshot.to_json()
    document = snapshot.document.to_firestore_document()

    extra = {"clock", "possession", "pending"}
    assert {k: v for k, v in payload.items() if k not in extra} == document
    assert set(payload) - set(document) == extra
    assert payload["teams"] == ["RMA", "BAR"]
    assert payload["updated_at"] == "2026-08-26T19:10:00.000Z"
    assert payload["clock"] == {"elapsed_s": 600.0, "period": 1, "minute": 10, "phase": "parte-1"}


def test_possession_is_a_share_of_the_time_played(match: list[MatchEvent]) -> None:
    replay = MatchReplay(match)
    replay.advance_to(30 * 60)
    snapshot = take_snapshot(replay)

    assert sum(snapshot.running_share.values()) == pytest.approx(1.0, abs=1e-3)
    assert set(snapshot.window_share) <= {"RMA", "BAR"}


def test_what_the_watermark_holds_is_in_sight(match: list[MatchEvent]) -> None:
    replay = MatchReplay(match)
    delivered = replay.advance_to(10 * 60)
    snapshot = take_snapshot(replay)

    assert snapshot.pending > 0
    assert snapshot.document.event_count + snapshot.pending == delivered


def test_before_kickoff_the_document_is_empty(match: list[MatchEvent]) -> None:
    snapshot = take_snapshot(MatchReplay(match))

    assert snapshot.document.indicators == {}
    assert (snapshot.running_share, snapshot.window_share, snapshot.pending) == ({}, {}, 0)


def test_at_the_final_whistle_the_score_is_the_batch_score(match: list[MatchEvent]) -> None:
    replay = MatchReplay(match)
    replay.advance_to(10 * 3600)
    snapshot = take_snapshot(replay)

    goals = {team: values["goals"] for team, values in snapshot.document.indicators.items()}
    assert goals == summarize_events(match).goals
    assert snapshot.to_json()["pending"] == 0
