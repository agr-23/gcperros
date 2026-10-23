"""Los informes que lee la pantalla «Por qué confiar» (#33)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gcperros.demo import cli
from gcperros.demo.replay import MatchReplay
from gcperros.demo.server import LiveSource, create_app
from gcperros.generators.match import MatchConfig, simulate_match

EVENTS = simulate_match(65, MatchConfig(match_id="match-0033"))


def _client(reports_dir: Path | None) -> TestClient:
    return TestClient(create_app(LiveSource(MatchReplay(EVENTS)), reports_dir=reports_dir))


def test_a_report_is_served_as_its_cli_wrote_it(tmp_path: Path) -> None:
    written = {"passed": True, "scenarios": [{"name": "limpio", "passed": True}]}
    (tmp_path / "validacion.json").write_text(json.dumps(written), encoding="utf-8")
    client = _client(tmp_path)

    assert client.get("/api/reports").json() == {
        "validacion": True,
        "carga": False,
        "calidad": False,
    }
    assert client.get("/api/reports/validacion").json() == written
    assert client.get("/api/reports/carga").status_code == 404


def test_without_a_folder_every_report_is_missing() -> None:
    client = _client(None)

    assert set(client.get("/api/reports").json().values()) == {False}
    assert client.get("/api/reports/calidad").status_code == 404


def test_only_listed_names_are_ever_read(tmp_path: Path) -> None:
    """El nombre de la URL nunca se convierte en ruta: nada fuera de la lista."""
    (tmp_path / "secreto.json").write_text("{}", encoding="utf-8")
    inner = tmp_path / "informes"
    inner.mkdir()
    client = _client(inner)

    assert client.get("/api/reports/secreto").status_code == 404
    assert client.get("/api/reports/..%2Fsecreto").status_code == 404


def test_the_cli_passes_the_folder_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "carga.json").write_text('{"saturation_rate": 100000}', encoding="utf-8")
    served: list[FastAPI] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **_: served.append(app))

    assert cli.main(["--reports", str(tmp_path)]) == 0
    assert TestClient(served[0]).get("/api/reports/carga").json() == {"saturation_rate": 100000}


def test_the_trust_page_is_linked_from_the_live_page() -> None:
    client = _client(None)
    page = client.get("/confianza.html")

    assert page.status_code == 200
    assert "<title>GCPerros · Por qué confiar</title>" in page.text
    assert 'href="confianza.html"' in client.get("/").text
    script = client.get("/confianza.js").text
    assert "/api/reports" in script and "innerHTML" not in script
