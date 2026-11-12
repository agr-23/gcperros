"""«Bajo el capó» cuenta el segundo deporte y cuadra con el Terraform (#96)."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from gcperros.demo.replay import MatchReplay
from gcperros.demo.server import LiveSource, create_app
from gcperros.generators.match import MatchConfig, simulate_match

TERRAFORM = Path(__file__).resolve().parent.parent / "infra" / "terraform"
PAGE = (
    TestClient(create_app(LiveSource(MatchReplay(simulate_match(65, MatchConfig(match_id="m"))))))
    .get("/bajo-el-capo.html")
    .text
)


def test_the_page_says_what_the_second_sport_shares_and_what_it_brings() -> None:
    assert "Un segundo deporte: qué se comparte y qué cambia" in PAGE
    for shared in ("Deduplicación", "Marca de agua", "Linaje", "Calidad"):
        assert shared in PAGE
    for own in ("basketball-events", "ganador sin empate", "0,10", "24 s"):
        assert own in PAGE


def test_the_service_account_count_matches_the_terraform() -> None:
    declared = sum(
        len(re.findall(r'resource "google_service_account"', path.read_text(encoding="utf-8")))
        for path in TERRAFORM.glob("*.tf")
    )

    assert f"{declared} cuentas de servicio" in PAGE
