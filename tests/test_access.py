"""La matriz de control de acceso (historia #27).

Las reglas pueden cambiar; lo que estas pruebas fijan son las garantías que
ninguna regla nueva puede romper.
"""

from __future__ import annotations

import json

import pytest

from gcperros.governance import catalog_cli
from gcperros.governance.access import MATRIX, Access, Principal, access
from gcperros.governance.catalog import CATALOG, AssetKind

ROW_LEVEL = {Access.READ, Access.MANAGE}
PERSONAL = [entry for entry in CATALOG if entry.personal]


def test_every_catalogued_asset_has_a_level_for_everyone() -> None:
    assert set(MATRIX) == {entry.name for entry in CATALOG}
    assert all(set(row) == set(Principal) for row in MATRIX.values())


def test_nobody_reads_personal_rows_and_holds_the_key() -> None:
    """La seudonimización sólo vale si la clave está separada de los datos (RGPD, art. 4.5)."""
    keys = [entry.name for entry in PERSONAL if entry.kind is AssetKind.KEY]
    rows = [entry.name for entry in PERSONAL if entry.kind is not AssetKind.KEY]

    assert keys and rows
    for principal in Principal:
        reads_rows = any(access(principal, name) in ROW_LEVEL for name in rows)
        holds_key = any(access(principal, name) is not Access.NONE for name in keys)
        assert not (reads_rows and holds_key), principal


def test_outside_its_owner_personal_data_is_only_seen_aggregated() -> None:
    for entry in PERSONAL:
        others = {p: level for p, level in MATRIX[entry.name].items() if p.value != entry.owner}
        assert set(others.values()) <= {Access.NONE, Access.AGGREGATE}, entry.name


def test_the_client_sees_what_is_shown_not_where_it_comes_from() -> None:
    assert access(Principal.CLIENT, "discrepancy_signal") is Access.READ
    assert access(Principal.CLIENT, "goals") is Access.READ
    for name in ("invalid-events", "gcperros_raw.match_events_raw", "user-activity"):
        assert access(Principal.CLIENT, name) is Access.NONE


def test_each_owner_manages_its_own_assets() -> None:
    for entry in CATALOG:
        assert MATRIX[entry.name][Principal(entry.owner.value)] is Access.MANAGE


def test_what_is_not_catalogued_is_not_granted() -> None:
    with pytest.raises(KeyError):
        access(Principal.GOVERNANCE, "user-emails")


def test_the_matrix_can_be_consulted(capsys: pytest.CaptureFixture[str]) -> None:
    catalog_cli.main(["--access"])
    text = capsys.readouterr().out
    catalog_cli.main(["--access", "--json"])
    rows = json.loads(capsys.readouterr().out)

    assert text.splitlines()[0].split() == ["activo", *(p.value for p in Principal)]
    assert rows["pseudonym-key"] == {"governance": "manage"} | dict.fromkeys(
        ("pipelines", "architecture", "client"), "none"
    )
