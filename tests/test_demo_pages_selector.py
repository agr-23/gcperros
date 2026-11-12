"""El selector de deporte también fuera de «En vivo», con los partidos del servidor (#148)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gcperros.demo.replay import MatchReplay
from gcperros.demo.server import LiveSource, create_app
from gcperros.generators.match import MatchConfig, simulate_match

CLIENT = TestClient(
    create_app(LiveSource(MatchReplay(simulate_match(65, MatchConfig(match_id="m")))))
)


@pytest.mark.parametrize("page", ["confianza.html", "bajo-el-capo.html"])
def test_the_secondary_pages_carry_the_selector_without_hardcoded_matches(page: str) -> None:
    html = CLIENT.get(f"/{page}").text

    assert 'id="sports"' in html
    assert html.index('src="sport.js"') < html.index('src="pages.js"')
    assert "?partido=" not in html  # los enlaces los pinta pages.js con /api/sports


def test_the_selector_script_reads_the_matches_from_the_server() -> None:
    script = CLIENT.get("/pages.js")

    assert script.status_code == 200
    assert 'fetch("/api/sports")' in script.text
