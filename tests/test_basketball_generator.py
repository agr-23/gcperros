"""El generador de baloncesto: determinista y fiel al reglamento (#88)."""

from __future__ import annotations

from collections import Counter
from itertools import pairwise

from gcperros.core import court
from gcperros.core.contracts import MatchEvent
from gcperros.core.schema import BASKETBALL_EVENT_SCHEMA
from gcperros.generators.basketball import BasketballConfig, simulate_basketball
from gcperros.governance.validation import validate_message

SEEDS = range(30)


def _serialize(seed: int, config: BasketballConfig | None = None) -> bytes:
    return b"".join(f"{e.to_json()}\n".encode() for e in simulate_basketball(seed, config))


def _clock(event: MatchEvent) -> float:
    clock = event.attrs["clock_s"]
    assert isinstance(clock, int | float)
    return float(clock)


def _matches() -> list[list[MatchEvent]]:
    return [simulate_basketball(seed) for seed in SEEDS]


def test_same_seed_produces_identical_bytes() -> None:
    for seed in range(10):
        assert _serialize(seed) == _serialize(seed), f"semilla {seed} no es reproducible"


def test_different_seeds_produce_different_matches() -> None:
    assert _serialize(1) != _serialize(2)


def test_no_ambient_state_leaks_between_runs() -> None:
    baseline = _serialize(11)
    simulate_basketball(999)
    assert _serialize(11) == baseline


def test_event_ids_are_unique_and_depend_on_the_match() -> None:
    left = simulate_basketball(3, BasketballConfig(match_id="bkb-A"))
    right = simulate_basketball(3, BasketballConfig(match_id="bkb-B"))

    ids = [e.event_id for e in left]
    assert len(ids) == len(set(ids))
    assert set(ids).isdisjoint(e.event_id for e in right)


def test_every_event_honours_the_contract() -> None:
    for events in _matches():
        for event in events:
            result = validate_message(event.to_json(), BASKETBALL_EVENT_SCHEMA)
            assert result.is_valid, result.violations


def test_wall_clock_moves_forward_and_game_clock_counts_down() -> None:
    for events in _matches():
        for before, after in pairwise(events):
            assert after.event_time >= before.event_time
            if after.attrs["period"] == before.attrs["period"]:
                assert _clock(after) <= _clock(before)


def test_possession_alternates_within_a_period() -> None:
    for events in _matches():
        changes = [e for e in events if e.event_type == "possession_change"]
        for before, after in pairwise(changes):
            if after.attrs["period"] == before.attrs["period"]:
                assert after.team != before.team
                assert after.attrs["from_team"] == before.team


def test_there_is_always_a_winner_after_four_quarters() -> None:
    for events in _matches():
        points: Counter[str] = Counter()
        for event in events:
            if event.attrs.get("made") is True:
                value = event.attrs.get("points_value", 1)
                points[event.team] += value if isinstance(value, int) else 1
        last_period = events[-1].attrs["period"]
        assert isinstance(last_period, int)
        assert last_period >= court.REGULATION_PERIODS
        assert len(set(points.values())) == len(points) == 2


def test_timeouts_respect_the_fiba_allowance() -> None:
    """Dos en la primera parte, tres en la segunda y uno por prórroga."""
    for events in _matches():
        used: Counter[tuple[str, str]] = Counter()
        for event in events:
            if event.event_type != "timeout":
                continue
            period = event.attrs["period"]
            assert isinstance(period, int)
            if period <= 2:
                block = "first_half"
            elif period <= court.REGULATION_PERIODS:
                block = "second_half"
            else:
                block = f"overtime-{period}"
            used[event.team, block] += 1
        allowance = {"first_half": 2, "second_half": 3}
        for (_, block), count in used.items():
            assert count <= allowance.get(block, 1)


def test_the_shot_clock_is_enforced() -> None:
    kinds = Counter(
        e.attrs["kind"] for events in _matches() for e in events if e.event_type == "turnover"
    )
    assert kinds["shot_clock_violation"] > 0
