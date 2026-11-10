"""Las cuotas del baloncesto: deterministas y reaccionando a rachas y tiempos muertos (#90)."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from functools import cache

import pytest

from gcperros.core.contracts import MatchEvent, OddsUpdate
from gcperros.core.schema import BASKETBALL_ODDS_SCHEMA
from gcperros.generators.basketball import BasketballConfig, simulate_basketball
from gcperros.generators.basketball_odds import BASKETBALL_OPERATORS, simulate_basketball_odds
from gcperros.generators.odds import REACTION_JITTER_S
from gcperros.governance.validation import validate_message

TEAMS = ("BOS", "LAL")
CONFIG = BasketballConfig(home_team="BOS", away_team="LAL")


@cache
def _match(seed: int) -> tuple[MatchEvent, ...]:
    return tuple(simulate_basketball(seed, CONFIG))


def _odds(seed: int) -> list[OddsUpdate]:
    return simulate_basketball_odds(seed, list(_match(seed)), TEAMS)


def test_same_seed_same_bytes() -> None:
    first = "".join(u.to_json() + "\n" for u in _odds(3))
    assert first == "".join(u.to_json() + "\n" for u in _odds(3))
    assert first != "".join(u.to_json() + "\n" for u in _odds(4))


@pytest.mark.parametrize("seed", range(5))
def test_every_quote_honours_the_contract_and_time_moves_forward(seed: int) -> None:
    updates = _odds(seed)

    for update in updates:
        result = validate_message(update.to_json(), BASKETBALL_ODDS_SCHEMA)
        assert result.is_valid, result.violations
    assert [u.event_time for u in updates] == sorted(u.event_time for u in updates)


def test_every_operator_opens_both_markets_and_only_the_total_has_a_line() -> None:
    opened = {(u.operator, u.market) for u in _odds(1) if u.trigger == "open"}

    assert opened == {
        (op.name, m) for op in BASKETBALL_OPERATORS for m in ("moneyline", "total_points")
    }
    assert all((u.line is None) == (u.market == "moneyline") for u in _odds(1))


def test_runs_and_timeouts_set_off_the_bursts() -> None:
    triggers = Counter(u.trigger for seed in range(5) for u in _odds(seed))

    assert triggers["run"] > 0
    assert triggers["timeout"] > 0
    assert {"goal", "red_card"}.isdisjoint(triggers)


def test_each_house_reacts_after_its_own_delay() -> None:
    """La reacción llega tras el retraso de la casa: es la ventana del precio rancio."""
    events = list(_match(2))
    timeouts = [e.event_time for e in events if e.event_type == "timeout"]
    for operator in BASKETBALL_OPERATORS:
        reactions = [
            u.event_time for u in _odds(2) if u.operator == operator.name and u.trigger == "timeout"
        ]
        assert len(reactions) == 2 * len(timeouts)  # los dos mercados
        lo = timedelta(seconds=operator.reaction_delay_s + REACTION_JITTER_S[0])
        hi = timedelta(seconds=operator.reaction_delay_s + REACTION_JITTER_S[1])
        assert all(any(lo <= r - t <= hi for t in timeouts) for r in reactions)


def test_the_houses_disagree_because_they_value_the_home_team_differently() -> None:
    first_prices = {u.operator: u.odds["home"] for u in _odds(0) if u.market == "moneyline"}

    assert len(set(first_prices.values())) == len(BASKETBALL_OPERATORS)
