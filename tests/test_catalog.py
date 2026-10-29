"""El catálogo de datos (historia #24), contrastado contra el Terraform."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from gcperros.governance.catalog import CATALOG, OWNERS, Asset, AssetKind, asset
from gcperros.governance.glossary import GLOSSARY

TERRAFORM = Path(__file__).resolve().parent.parent / "infra" / "terraform"


def _terraform(name: str) -> str:
    return (TERRAFORM / name).read_text(encoding="utf-8")


def _streams() -> set[str]:
    """Flujos declarados en ``locals.tf``: cada uno trae su ``contract_version``."""
    return set(re.findall(r'"([a-z-]+)" = \{\s*contract_version', _terraform("locals.tf")))


def _raw_dataset() -> str:
    variables = _terraform("variables.tf")
    block = variables[variables.index('variable "raw_dataset_id"') :]
    found = re.search(r'default\s*=\s*"(\w+)"', block)
    assert found is not None
    return found.group(1)


def _analytics_tables() -> set[str]:
    return set(re.findall(r'table_id\s*=\s*"(\w+)"', _terraform("analytics.tf")))


###############################################################################
# Contra el Terraform
###############################################################################


def test_the_terraform_declares_what_the_tests_expect() -> None:
    """Si el formato del Terraform cambia, que fallen estas y no pasen las demás."""
    assert _streams() == {"match-events", "odds-updates"}
    assert len(_analytics_tables()) >= 5


def test_every_stream_and_analytics_table_is_catalogued_once() -> None:
    names = [entry.name for entry in CATALOG]
    dataset = _raw_dataset()

    assert len(names) == len(set(names))
    for stream in _streams():
        assert {stream, f"{stream}-dead-letter"} <= set(names)
        assert f"{dataset}.{stream.replace('-', '_')}_raw" in names
    for table in _analytics_tables():
        assert f"gcperros_analytics.{table}" in names


###############################################################################
# Responsables y vocabulario
###############################################################################


@pytest.mark.parametrize("entry", CATALOG, ids=lambda entry: entry.name)
def test_every_asset_has_an_owner_and_only_glossary_terms(entry: Asset) -> None:
    assert OWNERS[entry.owner].person
    assert set(entry.terms) <= {term.key for term in GLOSSARY}


def test_the_contract_breaker_and_the_process_breaker_have_different_owners() -> None:
    """Inválidos y dead letter no son lo mismo (sección 6), y no responde el mismo."""
    invalid = asset("invalid-events")
    dead_letter = asset("match-events-dead-letter")

    assert (invalid.kind, dead_letter.kind) == (AssetKind.REPOSITORY, AssetKind.TOPIC)
    assert invalid.owner != dead_letter.owner


def test_an_unknown_asset_is_refused() -> None:
    with pytest.raises(KeyError, match="no está en el catálogo"):
        asset("gcperros_raw.users")
