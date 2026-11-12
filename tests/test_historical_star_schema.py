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
    dim_match: dict[str, int] = {
        "match-001": 1,
        "match-002": 1,
    }
    signals: list[tuple[str, str, str, float]] = [
        ("match-001", "1x2", "00-15", 0.08),
        ("match-001", "1x2", "15-30", 0.06),
        ("match-002", "over_under_2_5", "00-15", 0.07),
    ]

    by_matchday: dict[int, int] = {}
    by_market: dict[str, list[float]] = {}
    by_window: dict[str, int] = {}

    for match_id, market, window, magnitude in signals:
        mday = dim_match[match_id]
        by_matchday[mday] = by_matchday.get(mday, 0) + 1
        by_market.setdefault(market, []).append(magnitude)
        by_window[window] = by_window.get(window, 0) + 1

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


def test_schema_tolerates_second_sport_facts_without_breaking_football() -> None:
    """HU-22 / #94: el modelo estrella tolera el segundo deporte en fact_match_events."""
    football_event: dict[str, Any] = {
        "event_id": "evt-fb-001",
        "match_id": "match-fb-01",
        "team": "ATM",
        "event_type": "shot",
        "minute": 23,
        "xg": 0.32,
        # Registros históricos no tenían 'sport' ni columnas de baloncesto
    }

    basketball_shot: dict[str, Any] = {
        "event_id": "evt-bb-101",
        "match_id": "match-bb-01",
        "team": "LAL",
        "event_type": "shot",
        "minute": 4,
        "second": 12,
        "period": 1,
        "sport": "basketball",
        "points_value": 3,
        "made": True,
        "expected_points": 1.14,
        "xg": None,
    }

    basketball_possession: dict[str, Any] = {
        "event_id": "evt-bb-102",
        "match_id": "match-bb-01",
        "team": "BOS",
        "event_type": "possession_change",
        "minute": 4,
        "second": 14,
        "period": 1,
        "sport": "basketball",
        "points_value": None,
        "made": None,
        "expected_points": None,
    }

    events: list[dict[str, Any]] = [football_event, basketball_shot, basketball_possession]

    # 1. Consulta histórica de fútbol asume 'football' si 'sport' es nulo/ausente
    def get_sport(row: dict[str, Any]) -> str:
        return str(row.get("sport") or "football")

    football_events = [e for e in events if get_sport(e) == "football"]
    assert len(football_events) == 1
    assert football_events[0]["xg"] == 0.32
    assert "points_value" not in football_events[0]

    # 2. Hechos de baloncesto conviven en la misma tabla sin colisión
    basketball_events = [e for e in events if get_sport(e) == "basketball"]
    assert len(basketball_events) == 2

    # 3. Consulta de tiros y puntos esperados en baloncesto
    shots = [e for e in basketball_events if e["event_type"] == "shot"]
    assert len(shots) == 1
    assert shots[0]["points_value"] == 3
    assert shots[0]["made"] is True
    assert shots[0]["expected_points"] == 1.14

    # 4. Hechos de posesión en baloncesto
    possessions = [e for e in basketball_events if e["event_type"] == "possession_change"]
    assert len(possessions) == 1
    assert possessions[0]["team"] == "BOS"


def test_multisport_aggregate_queries_by_sport_and_matchday_run_without_friction() -> None:
    """HU-22 / #94: consultas analíticas agregadas por deporte y jornada sin reprocesos."""
    dim_match: dict[str, dict[str, Any]] = {
        "match-fb-01": {"matchday": 1, "sport": None},  # Antiguo fútbol (NULLABLE sport)
        "match-fb-02": {"matchday": 1, "sport": "football"},
        "match-bb-01": {"matchday": 1, "sport": "basketball"},
    }

    events: list[dict[str, Any]] = [
        {"match_id": "match-fb-01", "event_type": "shot", "xg": 0.45},
        {"match_id": "match-fb-02", "event_type": "shot", "xg": 0.35},
        {"match_id": "match-bb-01", "event_type": "shot", "points_value": 3, "made": True},
        {"match_id": "match-bb-01", "event_type": "shot", "points_value": 2, "made": False},
        {"match_id": "match-bb-01", "event_type": "possession_change"},
    ]

    event_counts: dict[str, int] = {"football": 0, "basketball": 0}
    football_xg: float = 0.0
    basketball_points: int = 0
    basketball_possessions: int = 0

    for evt in events:
        match_id: str = str(evt["match_id"])
        sport: str = str(dim_match[match_id].get("sport") or "football")
        event_counts[sport] += 1
        if sport == "football":
            football_xg += float(evt.get("xg", 0.0))
        elif sport == "basketball":
            if evt["event_type"] == "shot" and evt.get("made"):
                basketball_points += int(evt.get("points_value", 0))
            elif evt["event_type"] == "possession_change":
                basketball_possessions += 1

    assert event_counts["football"] == 2
    assert round(football_xg, 2) == 0.80
    assert event_counts["basketball"] == 3
    assert basketball_points == 3
    assert basketball_possessions == 1
