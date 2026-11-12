"""El pulido de «En vivo» (#96): lo que la página promete enseñar, en su marcado."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gcperros.demo.replay import BasketballReplay
from gcperros.demo.server import LiveSource, create_app
from gcperros.generators.basketball import BasketballConfig, simulate_basketball

EVENTS = simulate_basketball(65, BasketballConfig("demo-bkb-65", "BOS", "LAL"))
CLIENT = TestClient(create_app(LiveSource(BasketballReplay(EVENTS), clock=lambda: 0.0)))


def test_the_match_state_is_said_in_words_not_only_with_the_clock() -> None:
    page = CLIENT.get("/").text
    app = CLIENT.get("/app.js").text

    assert 'id="state"' in page
    assert all(word in app for word in ('"Final"', '"Descanso"', '"En juego"'))


def test_each_panel_has_its_place_in_the_wide_layout() -> None:
    page = CLIENT.get("/").text
    css = CLIENT.get("/app.css").text

    panels = ("signals-panel", "possession-panel", "estimate-panel", "stats-panel", "h2h-panel")
    for panel in panels:
        assert f"panel {panel}" in page
        assert f".{panel} {{ grid-area:" in css
    assert "grid-template-areas" in css
    assert "BigQuery Analytics" in page
    # Sólo «En vivo»: las otras pantallas siguen en una columna.
    assert '<main class="wrap live">' in page and ".wrap.live {" in css


def test_a_score_change_is_noticed_and_the_winner_is_shown() -> None:
    app = CLIENT.get("/app.js").text
    css = CLIENT.get("/app.css").text

    assert 'classList.add("bump")' in app and "dataset.winner" in app
    assert '.board[data-winner="home"]' in css
    # Sin animaciones para quien las desactiva en su sistema.
    assert ".score .bump { animation: none; }" in css


def test_each_line_of_the_chart_names_its_team() -> None:
    assert "function drawEndLabels" in CLIENT.get("/charts.js").text


def test_between_quarters_the_clock_reads_zero() -> None:
    """Entre cuartos el reloj no se queda en el último evento del cuarto."""
    assert 'clock.phase === "descanso" ? 0' in CLIENT.get("/sport.js").text


def test_on_a_phone_nothing_pushes_the_page_sideways() -> None:
    """Medido a 390 px: la cabecera se parte, el reloj salta de línea y las tablas se desplazan."""
    css = CLIENT.get("/app.css").text

    assert ".wrap > * { min-width: 0; }" in css
    assert ".bar { flex-wrap: wrap;" in css
    assert ".chart svg { min-width: 0; }" in css


def test_the_trust_page_counts_every_sport_it_compares() -> None:
    assert "Tres deportes, la misma vara" in CLIENT.get("/confianza.html").text
    assert "Los ${report.length} deportes cumplen" in CLIENT.get("/confianza.js").text
