"""La consulta del catálogo y el glosario por línea de comandos (historia #24)."""

from __future__ import annotations

import json

import pytest

from gcperros.governance import catalog_cli
from gcperros.governance.catalog import CATALOG, INDICATORS, AssetKind, asset
from gcperros.governance.glossary import GLOSSARY
from gcperros.governance.traceability import MATCH_INDICATORS, TEAM_INDICATORS


def test_every_indicator_the_engine_explains_is_catalogued() -> None:
    """Un indicador nuevo en la auditoría sin catalogar rompe la construcción."""
    catalogued = {entry.name for entry in INDICATORS}

    assert set(TEAM_INDICATORS) | set(MATCH_INDICATORS) <= catalogued


def test_the_signal_and_every_glossary_term_are_in_use() -> None:
    used = {term for entry in CATALOG for term in entry.terms}

    assert asset("discrepancy_signal").kind == AssetKind.SIGNAL
    assert {term.key for term in GLOSSARY} <= used


def test_the_listing_names_every_asset_with_its_person(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert catalog_cli.main([]) == 0

    out, err = capsys.readouterr()
    assert len(out.strip().splitlines()) == len(CATALOG)
    assert "invalid-events" in out and "Alejandro Garcés (governance)" in out
    assert f"activos={len(CATALOG)}" in err


def test_filters_answer_what_belongs_to_a_role(capsys: pytest.CaptureFixture[str]) -> None:
    catalog_cli.main(["--owner", "governance", "--kind", "report", "--json"])

    entries = json.loads(capsys.readouterr().out)
    assert entries
    assert {e["owner"]["role"] for e in entries} == {"governance"}
    assert {e["kind"] for e in entries} == {"report"}


def test_the_glossary_comes_out_whole(capsys: pytest.CaptureFixture[str]) -> None:
    catalog_cli.main(["--glossary", "--json"])
    terms = json.loads(capsys.readouterr().out)
    catalog_cli.main(["--glossary"])
    text = capsys.readouterr().out

    assert [t["key"] for t in terms] == [t.key for t in GLOSSARY]
    assert "Probabilidad implícita [implied_probability]" in text


def test_an_unknown_role_is_refused() -> None:
    with pytest.raises(SystemExit):
        catalog_cli.main(["--owner", "marketing"])
