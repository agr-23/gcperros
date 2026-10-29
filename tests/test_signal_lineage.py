"""De dónde sale cada señal de discrepancia (historia #25).

La señal es lo que el usuario recibe para decidir. Estas pruebas exigen que cada
una lleve la versión del modelo que la calculó y una huella que se pueda volver
a derivar, **sin el detector**, desde los flujos crudos.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from gcperros.core import odds
from gcperros.core.contracts import MatchEvent, OddsUpdate, parse_match_event, parse_odds_update
from gcperros.core.lineage import LineageAccumulator
from gcperros.engine import cli
from gcperros.engine.signals import DiscrepancySignal, detect_discrepancies
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.odds import simulate_odds
from gcperros.governance.traceability import MODELS_BY_INDICATOR

CONFIG = MatchConfig(match_id="match-0025", home_team="RMA", away_team="BAR")
SEED = 65

Streams = tuple[list[MatchEvent], list[OddsUpdate]]


@pytest.fixture(scope="module")
def streams() -> Streams:
    events = simulate_match(SEED, CONFIG)
    return events, simulate_odds(SEED, events)


@pytest.fixture(scope="module")
def signals(streams: Streams) -> list[DiscrepancySignal]:
    found = detect_discrepancies(*streams)
    assert found, "el partido de exhibición tiene que dar señales"
    return found


def _state_events(event: MatchEvent) -> bool:
    return event.event_type in {"goal", "red_card"} or event.attrs.get("reason") == "kickoff"


def _expected_digest(signal: DiscrepancySignal, streams: Streams, without: str = "") -> str:
    """La huella, derivada a mano: estado del partido hasta ese instante y la cuota."""
    events, updates = streams
    seen = [e for e in events if e.event_time <= signal.detected_at]
    priced = [
        u
        for u in updates
        if (u.operator, u.market) == (signal.operator, signal.market)
        and u.event_time <= signal.detected_at
    ]
    ids = {e.event_id for e in seen if _state_events(e)} | {seen[-1].event_id, priced[-1].event_id}
    fold = LineageAccumulator()
    for event_id in ids - {without}:
        fold.add(event_id)
    return fold.digest


def test_every_signal_names_the_model_that_computed_it(signals: list[DiscrepancySignal]) -> None:
    declared = MODELS_BY_INDICATOR["discrepancy_signal"]

    assert {s.model_version for s in signals} == {odds.MODEL_VERSION} == set(declared.values())


def test_the_lineage_is_rederived_from_the_raw_streams(
    signals: list[DiscrepancySignal], streams: Streams
) -> None:
    for signal in signals:
        assert signal.lineage.digest == _expected_digest(signal, streams), signal.describe()


def test_a_stale_price_signal_includes_the_goal_that_made_it_stale(
    signals: list[DiscrepancySignal], streams: Streams
) -> None:
    """El 57 % de las señales llega tras un gol: ese gol tiene que estar en su linaje."""
    goals = {e.event_time: e.event_id for e in streams[0] if e.event_type == "goal"}
    after_goal = [s for s in signals if s.detected_at in goals]

    assert after_goal
    for signal in after_goal:
        goal = goals[signal.detected_at]
        assert signal.lineage.digest == _expected_digest(signal, streams)
        assert signal.lineage.digest != _expected_digest(signal, streams, without=goal)


def test_the_same_streams_read_back_from_disk_give_the_same_lineage(
    signals: list[DiscrepancySignal], streams: Streams, tmp_path: Path
) -> None:
    events, updates = streams
    match_file, odds_file = tmp_path / "partido.jsonl", tmp_path / "cuotas.jsonl"
    match_file.write_text("".join(e.to_json() + "\n" for e in events), encoding="utf-8")
    odds_file.write_text("".join(u.to_json() + "\n" for u in updates), encoding="utf-8")

    reread = detect_discrepancies(
        [parse_match_event(line) for line in match_file.read_text(encoding="utf-8").splitlines()],
        [parse_odds_update(line) for line in odds_file.read_text(encoding="utf-8").splitlines()],
    )

    assert [s.lineage for s in reread] == [s.lineage for s in signals]


def test_the_published_signal_carries_its_provenance(tmp_path: Path) -> None:
    out = tmp_path / "senales.jsonl"
    assert cli.main(["--seed", str(SEED), "--out", str(out)]) == 0

    first = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert first["model_version"] == odds.MODEL_VERSION
    assert first["lineage"]["indicator"] == "discrepancy_signal"
    assert first["lineage"]["event_count"] > 0


def test_the_historical_table_keeps_the_provenance_the_signal_publishes() -> None:
    """Una señal guardada en BigQuery tiene que seguir siendo auditable (historia #25)."""
    terraform = Path(__file__).resolve().parent.parent / "infra" / "terraform" / "analytics.tf"
    text = terraform.read_text(encoding="utf-8")
    table = text[text.index('"fact_market_signals" {') :]
    columns = dict(
        re.findall(r'name = "(\w+)", type = "\w+", mode = "(\w+)"', table[: table.index("\n}")])
    )

    for column in ("model_version", "lineage_digest", "lineage_event_count"):
        # NULLABLE: es la única forma de añadir una columna a una tabla que ya existe.
        assert columns.get(column) == "NULLABLE", column
