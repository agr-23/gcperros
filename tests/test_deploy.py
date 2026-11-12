"""Lo que hace falta para desplegar el motor se nombra igual en todas partes."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import uvicorn

from gcperros.service import cli

ROOT = Path(__file__).resolve().parent.parent
TERRAFORM = ROOT / "infra" / "terraform"


def test_the_image_runs_the_declared_service_with_its_extra() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert project["scripts"]["gcperros-engine-service"] == "gcperros.service.cli:main"
    assert {"fastapi", "uvicorn", "google-cloud-firestore"} <= {
        re.split(r"[<>=]", requirement)[0]
        for requirement in project["optional-dependencies"]["service"]
    }
    assert 'pip install --no-cache-dir ".[service]"' in dockerfile
    assert 'CMD ["gcperros-engine-service"]' in dockerfile
    assert "USER motor" in dockerfile


def test_cloud_run_runs_as_the_engine_and_feeds_the_push_subscriptions() -> None:
    service = (TERRAFORM / "cloud_run.tf").read_text(encoding="utf-8")
    locals_tf = (TERRAFORM / "locals.tf").read_text(encoding="utf-8")
    apis = (TERRAFORM / "apis.tf").read_text(encoding="utf-8")

    assert "service_account = google_service_account.engine.email" in service
    assert service.count("path = var.engine_health_path") == 2
    assert "google_cloud_run_v2_service.engine[*].uri" in locals_tf
    assert '"run.googleapis.com"' in apis and '"artifactregistry.googleapis.com"' in apis


def test_the_service_starts_in_memory_without_a_cloud_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: dict[str, object] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: started.update(kwargs, app=app))

    assert cli.main(["--memory", "--port", "9090"]) == 0
    assert started["port"] == 9090 and started["host"] == "127.0.0.1"


def test_without_a_project_it_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    with pytest.raises(SystemExit, match="GOOGLE_CLOUD_PROJECT"):
        cli.main(["--project", ""])
