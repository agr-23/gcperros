"""La página sabe de los dos deportes por sport.js, y de nada más (#92)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gcperros.demo.replay import BasketballReplay
from gcperros.demo.server import LiveSource, create_app
from gcperros.generators.basketball import BasketballConfig, simulate_basketball

EVENTS = simulate_basketball(65, BasketballConfig("demo-bkb-65", "BOS", "LAL"))
CLIENT = TestClient(create_app(LiveSource(BasketballReplay(EVENTS), clock=lambda: 0.0)))


def test_the_sport_config_loads_before_the_scripts_that_read_it() -> None:
    page = CLIENT.get("/").text

    assert page.index('src="sport.js"') < page.index('src="charts.js"') < page.index('src="app.js"')


def test_each_sport_declares_its_scoreboard_threshold_and_stats() -> None:
    config = CLIENT.get("/sport.js").text

    for needle in ('headline: "goals"', 'headline: "points"', "threshold: 0.05", "threshold: 0.10"):
        assert needle in config
    assert '"expected_points"' in config and '"total_xg"' in config


def test_no_script_assumes_football_any_more() -> None:
    """Resultados, umbral y estadísticas salen de la configuración del deporte."""
    market = CLIENT.get("/market.js").text
    charts = CLIENT.get("/charts.js").text

    assert "THRESHOLD = 0.05" not in market and "GCP.config.threshold" in market
    assert "const ROWS" not in charts and "GCP.config.stats" in charts
    assert "/api/sports" in CLIENT.get("/app.js").text
