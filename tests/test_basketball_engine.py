"""El motor de siempre, con el estado del baloncesto (#89).

El criterio de la issue: con duplicados y desorden, el estado de baloncesto en
vivo coincide con el plano batch, y el deduplicador y la marca de agua no
cambiaron ni una línea para conseguirlo.
"""

from __future__ import annotations

import pytest

from gcperros.core.basketball_stats import summarize_basketball
from gcperros.core.contracts import MatchEvent
from gcperros.engine.basketball_state import basketball_engine
from gcperros.generators.basketball import BasketballConfig, simulate_basketball
from gcperros.generators.perturbation import inject_disorder, inject_duplicates

CONFIG = BasketballConfig(home_team="BOS", away_team="LAL")

#: Retardo máximo por debajo del margen de la marca de agua (10 s): así ningún
#: evento llega tarde y la igualdad con el batch tiene que ser exacta.
WITHIN_LATENESS_S = 9.0


def _match(seed: int) -> list[MatchEvent]:
    return simulate_basketball(seed, CONFIG)


def _adverse(
    events: list[MatchEvent], seed: int, max_delay_s: float, mean_delay_s: float = 2.0
) -> list[MatchEvent]:
    duplicated, _ = inject_duplicates(events, seed)
    disordered, _ = inject_disorder(
        duplicated, seed, mean_delay_s=mean_delay_s, max_delay_s=max_delay_s
    )
    return disordered


@pytest.mark.parametrize("seed", range(8))
def test_a_clean_stream_matches_the_batch(seed: int) -> None:
    events = _match(seed)

    assert basketball_engine().process_all(events).summary == summarize_basketball(events)


@pytest.mark.parametrize("seed", range(8))
def test_duplicates_and_disorder_do_not_change_the_result(seed: int) -> None:
    events = _match(seed)
    delivered = _adverse(events, seed, WITHIN_LATENESS_S)

    result = basketball_engine().process_all(delivered)

    assert len(delivered) > len(events), "la perturbación tiene que repetir algo"
    assert delivered != sorted(delivered, key=lambda e: e.event_time)
    assert result.summary == summarize_basketball(events)
    assert result.dedup.duplicates == len(delivered) - len(events)
    assert result.watermark.dropped_late == 0


def test_heavy_disorder_is_accounted_for_not_hidden() -> None:
    """Exacto es contabilidad: lo que no se aplicó está contado como tardío."""
    events = _match(3)
    delivered = _adverse(events, 3, max_delay_s=120.0, mean_delay_s=30.0)

    result = basketball_engine().process_all(delivered)

    assert result.watermark.dropped_late > 0
    assert result.summary.event_count + result.watermark.dropped_late == len(events)


def test_possession_by_time_works_unchanged_for_basketball() -> None:
    result = basketball_engine().process_all(_match(2))

    shares = result.possession.running_share
    assert set(shares) == {"BOS", "LAL"}
    assert sum(shares.values()) == pytest.approx(1.0)
    assert result.possession_windows, "la marca de agua también cierra ventanas de baloncesto"
