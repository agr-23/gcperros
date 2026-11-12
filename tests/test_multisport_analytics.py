"""La capa analítica para más de un deporte, contrastada contra el Terraform (#94).

Lo que se vigila es lo que la issue promete: que el modelo estrella distinga el
deporte y guarde los hechos del baloncesto **sin romper los del fútbol**. Romper
es cambiar o quitar una columna que ya existe, o añadir una obligatoria a una
tabla con datos: BigQuery sólo admite añadir columnas NULLABLE.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from gcperros.core import court
from gcperros.engine.sport_harness import SPORTS

ANALYTICS = Path(__file__).resolve().parent.parent / "infra" / "terraform" / "analytics.tf"

Columns = dict[str, tuple[str, str]]

#: Las columnas que ya existían antes del segundo deporte, con su tipo y su modo.
FOOTBALL_BASELINE: dict[str, Columns] = {
    "dim_match": {
        "match_id": ("STRING", "REQUIRED"),
        "matchday": ("INTEGER", "REQUIRED"),
        "season": ("STRING", "REQUIRED"),
        "home_team": ("STRING", "REQUIRED"),
        "away_team": ("STRING", "REQUIRED"),
        "match_date": ("DATE", "REQUIRED"),
    },
    "fact_match_events": {
        "event_id": ("STRING", "REQUIRED"),
        "match_id": ("STRING", "REQUIRED"),
        "team": ("STRING", "REQUIRED"),
        "event_type": ("STRING", "REQUIRED"),
        "event_time": ("TIMESTAMP", "REQUIRED"),
        "ingestion_time": ("TIMESTAMP", "REQUIRED"),
        "minute": ("INTEGER", "NULLABLE"),
        "second": ("INTEGER", "NULLABLE"),
        "period": ("INTEGER", "NULLABLE"),
        "time_window_15m": ("STRING", "NULLABLE"),
        "xg": ("FLOAT", "NULLABLE"),
        "x": ("FLOAT", "NULLABLE"),
        "y": ("FLOAT", "NULLABLE"),
    },
    "fact_market_signals": {
        "signal_id": ("STRING", "REQUIRED"),
        "match_id": ("STRING", "REQUIRED"),
        "operator": ("STRING", "REQUIRED"),
        "market": ("STRING", "REQUIRED"),
        "outcome": ("STRING", "REQUIRED"),
        "event_time": ("TIMESTAMP", "REQUIRED"),
        "ingestion_time": ("TIMESTAMP", "REQUIRED"),
        "minute": ("FLOAT", "NULLABLE"),
        "time_window_15m": ("STRING", "NULLABLE"),
        "model_probability": ("FLOAT", "REQUIRED"),
        "market_probability": ("FLOAT", "REQUIRED"),
        "divergence": ("FLOAT", "REQUIRED"),
        "magnitude": ("FLOAT", "REQUIRED"),
    },
}


def _tables() -> dict[str, Columns]:
    text = ANALYTICS.read_text(encoding="utf-8")
    tables: dict[str, Columns] = {}
    for block in text.split('resource "google_bigquery_table"')[1:]:
        found = re.search(r'table_id\s*=\s*"(\w+)"', block)
        assert found is not None
        columns = re.findall(r'name = "(\w+)", type = "(\w+)", mode = "(\w+)"', block)
        tables[found.group(1)] = {name: (kind, mode) for name, kind, mode in columns}
    return tables


@pytest.mark.parametrize("table", FOOTBALL_BASELINE)
def test_the_football_columns_are_untouched(table: str) -> None:
    columns = _tables()[table]

    for name, declared in FOOTBALL_BASELINE[table].items():
        assert columns.get(name) == declared, name


@pytest.mark.parametrize("table", FOOTBALL_BASELINE)
def test_every_column_added_to_an_existing_table_is_nullable(table: str) -> None:
    """Una columna obligatoria nueva invalidaría las filas que ya están."""
    added = set(_tables()[table]) - set(FOOTBALL_BASELINE[table])

    assert added
    assert {_tables()[table][name][1] for name in added} == {"NULLABLE"}


def test_the_match_and_the_facts_say_their_sport() -> None:
    tables = _tables()

    for table in ("dim_match", "fact_match_events", "fact_market_signals"):
        assert tables[table]["sport"] == ("STRING", "NULLABLE"), table
    assert tables["dim_sport"]["sport"] == ("STRING", "REQUIRED")


def test_the_sport_dimension_holds_what_the_sports_differ_in() -> None:
    """Flujos y reglamento: lo que una consulta necesita para comparar deportes."""
    assert set(_tables()["dim_sport"]) == {
        "sport",
        "sport_name",
        "events_stream",
        "odds_stream",
        "periods",
        "period_minutes",
    }
    text = ANALYTICS.read_text(encoding="utf-8")
    assert all(sport in text for sport in SPORTS)
    assert f"{court.REGULATION_PERIODS} cuartos" in text


def test_basketball_facts_have_their_own_columns_next_to_football_s() -> None:
    facts = _tables()["fact_match_events"]

    assert facts["points_value"] == ("INTEGER", "NULLABLE")
    assert facts["made"] == ("BOOLEAN", "NULLABLE")
    assert facts["expected_points"] == ("FLOAT", "NULLABLE")
    assert facts["xg"] == ("FLOAT", "NULLABLE")
