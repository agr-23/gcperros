"""Conformidad del flujo emitido con el contrato de datos de la HU-1."""

from __future__ import annotations

import json
from typing import Any

import pytest

from gcperros.core.contracts import CONTRACT_VERSION
from gcperros.generators.match import MatchConfig, simulate_match

CONFIG = MatchConfig(match_id="match-0007", home_team="RMA", away_team="BAR")
REQUIRED_FIELDS = {
    "event_id",
    "event_time",
    "match_id",
    "team",
    "event_type",
    "contract_version",
    "attrs",
}


@pytest.fixture(scope="module")
def events() -> list[dict[str, Any]]:
    return [json.loads(event.to_json()) for event in simulate_match(2026, CONFIG)]


def test_every_event_carries_the_required_fields(events: list[dict[str, Any]]) -> None:
    for event in events:
        assert set(event) == REQUIRED_FIELDS


def test_contract_version_is_stamped(events: list[dict[str, Any]]) -> None:
    assert {event["contract_version"] for event in events} == {CONTRACT_VERSION}


def test_only_declared_event_types_are_emitted(events: list[dict[str, Any]]) -> None:
    assert {event["event_type"] for event in events} <= {
        "pass",
        "shot",
        "goal",
        "foul",
        "possession_change",
    }


def test_events_belong_to_one_of_the_two_teams(events: list[dict[str, Any]]) -> None:
    assert {event["team"] for event in events} == {CONFIG.home_team, CONFIG.away_team}


def test_event_time_is_chronologically_non_decreasing(events: list[dict[str, Any]]) -> None:
    stamps = [str(event["event_time"]) for event in events]
    assert stamps == sorted(stamps), "el generador debe emitir en orden cronológico"


def test_event_time_is_iso8601_utc(events: list[dict[str, Any]]) -> None:
    for event in events:
        stamp = str(event["event_time"])
        assert stamp.endswith("Z")
        assert len(stamp) == len("2026-08-26T19:00:00.000Z")


def test_goal_is_emitted_alongside_the_shot_that_produced_it(
    events: list[dict[str, Any]],
) -> None:
    """El gol es un evento redundante, decisión deliberada del contrato."""
    scoring_shots = [
        event for event in events if event["event_type"] == "shot" and event["attrs"]["is_goal"]
    ]
    goals = [event for event in events if event["event_type"] == "goal"]

    assert len(goals) == len(scoring_shots)

    for shot, goal in zip(scoring_shots, goals, strict=True):
        assert shot["team"] == goal["team"]
        assert shot["attrs"]["xg"] == goal["attrs"]["xg"]


def test_shots_carry_a_valid_xg(events: list[dict[str, Any]]) -> None:
    for event in events:
        if event["event_type"] == "shot":
            xg = event["attrs"]["xg"]
            assert isinstance(xg, float)
            assert 0.0 <= xg <= 1.0


def test_coordinates_stay_inside_the_pitch(events: list[dict[str, Any]]) -> None:
    for event in events:
        attrs = event["attrs"]
        for key, value in attrs.items():
            if key.endswith("_x") or key == "x":
                assert 0.0 <= float(value) <= 105.0
            elif key.endswith("_y") or key == "y":
                assert 0.0 <= float(value) <= 68.0


def test_every_event_declares_its_period(events: list[dict[str, Any]]) -> None:
    assert {e["attrs"]["period"] for e in events} == {1, 2}
