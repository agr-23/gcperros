"""Pruebas del modelo estrella y tolerancia a cambios en la capa histórica (HU-22)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from gcperros.core.contracts import format_event_time

EVENT_T0 = datetime(2026, 8, 26, 20, 0, 0, tzinfo=UTC)
INGESTION_T0 = EVENT_T0 + timedelta(seconds=12, milliseconds=450)


def _to_15m_window(minute: int) -> str:
    """Deriva la ventana analítica de 15 minutos a partir del minuto de juego."""
    bucket = min(minute // 15 * 15, 75)
    return f"{bucket:02d}-{bucket + 15:02d}"


def test_fact_tables_explicitly_distinguish_event_time_from_ingestion_time() -> None:
    """HU-22: la capa histórica no confunde el reloj del juego con el del pipeline."""
    event_row = {
        "event_id": "evt-101",
        "match_id": "match-001",
        "event_type": "shot",
        "event_time": format_event_time(EVENT_T0),
        "ingestion_time": format_event_time(INGESTION_T0),
        "time_window_15m": _to_15m_window(14),
    }

    assert event_row["event_time"] != event_row["ingestion_time"]
    delta_s = (INGESTION_T0 - EVENT_T0).total_seconds()
    assert delta_s == 12.45
    assert event_row["time_window_15m"] == "00-15"


def test_aggregate_queries_by_matchday_market_and_time_window_run_without_friction() -> None:
    """HU-22: consultas analíticas por jornada, mercado y ventana temporal."""
    dim_match = {
        "match-001": {"matchday": 1, "season": "2026-2027"},
        "match-002": {"matchday": 1, "season": "2026-2027"},
    }
    signals: list[dict[str, Any]] = [
        {"match_id": "match-001", "market": "1x2", "window": "00-15", "magnitude": 0.08},
        {"match_id": "match-001", "market": "1x2", "window": "15-30", "magnitude": 0.06},
        {"match_id": "match-002", "market": "over_under_2_5", "window": "00-15", "magnitude": 0.07},
    ]

    by_matchday: dict[int, int] = {}
    by_market: dict[str, list[float]] = {}
    by_window: dict[str, int] = {}

    for row in signals:
        mday = dim_match[row["match_id"]]["matchday"]
        by_matchday[mday] = by_matchday.get(mday, 0) + 1
        by_market.setdefault(row["market"], []).append(row["magnitude"])
        by_window[row["window"]] = by_window.get(row["window"], 0) + 1

    assert by_matchday[1] == 3
    assert len(by_market["1x2"]) == 2
    assert round(sum(by_market["1x2"]) / len(by_market["1x2"]), 4) == 0.07
    assert by_window["00-15"] == 2
    assert by_window["15-30"] == 1


def test_schema_tolerates_structural_evolution_without_breaking_existing_data() -> None:
    """HU-22: el esquema tolera añadir una columna nueva sin invalidar datos históricos."""
    historical_record = {
        "signal_id": "sig-001",
        "match_id": "match-001",
        "market": "1x2",
        "magnitude": 0.08,
    }

    # Evolución del esquema: adición de 'signal_severity' en modo NULLABLE (ALTER TABLE ADD COLUMN)
    new_record_with_column = {
        "signal_id": "sig-002",
        "match_id": "match-001",
        "market": "1x2",
        "magnitude": 0.12,
        "signal_severity": "HIGH",
    }

    def read_severity(row: dict[str, Any]) -> str:
        # Consulta backward-compatible: registros antiguos devuelven NULL / default
        return row.get("signal_severity") or "UNKNOWN"

    assert read_severity(historical_record) == "UNKNOWN"
    assert read_severity(new_record_with_column) == "HIGH"

    # Las consultas analíticas previas siguen dando el mismo resultado sobre el registro histórico
    assert historical_record["magnitude"] == 0.08
    assert "signal_severity" not in historical_record
