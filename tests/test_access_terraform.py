"""La matriz de acceso, aplicada de verdad en IAM (historia #27).

Lee los permisos que declara ``infra/terraform/privacy.tf`` y exige que digan lo
mismo que ``governance/access.py``. Una matriz que el Terraform contradice es un
documento, no un control.
"""

from __future__ import annotations

import re
from pathlib import Path

from gcperros.governance.access import MATRIX, Access, Principal

TERRAFORM = Path(__file__).resolve().parent.parent / "infra" / "terraform"

#: Qué activo del catálogo protege cada recurso del Terraform.
TARGETS = {
    "google_pubsub_topic.user_activity": "user-activity",
    "google_secret_manager_secret.pseudonym_key": "pseudonym-key",
}

#: Roles con los que se pueden leer los mensajes del topic.
ROW_READING = {"roles/pubsub.admin", "roles/pubsub.editor", "roles/pubsub.subscriber"}


def _grants() -> set[tuple[str, str, str]]:
    """Triples ``(activo, rol, miembro)`` de cada permiso sobre datos personales."""
    text = (TERRAFORM / "privacy.tf").read_text(encoding="utf-8")
    blocks = re.findall(r'resource "google_\w+_iam_member" "\w+" \{(.*?)\n\}', text, re.DOTALL)
    found = set()
    for block in blocks:
        target = next(name for ref, name in TARGETS.items() if ref in block)
        role = re.search(r'role\s*=\s*"([^"]+)"', block)
        loop = re.search(r"for_each\s*=\s*toset\(var\.(\w+)_members\)", block)
        account = re.search(r"google_service_account\.(\w+)\.email", block)
        assert role is not None and (loop or account), block
        member = loop.group(1) if loop else f"sa:{account.group(1) if account else ''}"
        found.add((target, role.group(1), member))
    return found


def test_the_personal_assets_exist_in_the_infrastructure() -> None:
    text = (TERRAFORM / "privacy.tf").read_text(encoding="utf-8")

    assert 'name    = "${local.prefix}user-activity"' in text
    assert 'secret_id = "${local.prefix}pseudonym-key"' in text
    assert len(_grants()) == len(re.findall(r'"google_\w+_iam_member"', text))


def test_a_team_role_is_granted_exactly_what_the_matrix_says() -> None:
    """Administrar en la matriz es administrar en IAM; menos que eso, ningún permiso."""
    granted = {(asset, member): role for asset, role, member in _grants()}

    for asset in TARGETS.values():
        for principal in Principal:
            role = granted.get((asset, principal.value))
            if MATRIX[asset][principal] is Access.MANAGE:
                assert role is not None and role.endswith(".admin"), (asset, principal)
            else:
                assert role is None, (asset, principal)


def test_nobody_reads_the_sessions_and_holds_the_key_in_iam_either() -> None:
    """La separación del RGPD, art. 4.5, comprobada sobre las identidades reales."""
    grants = _grants()
    readers = {m for asset, role, m in grants if asset == "user-activity" and role in ROW_READING}
    key_holders = {m for asset, _role, m in grants if asset == "pseudonym-key"}

    assert readers and key_holders
    assert not readers & key_holders


def test_the_key_value_never_goes_through_terraform() -> None:
    """Una versión del secreto en Terraform dejaría la clave escrita en el estado."""
    for file in TERRAFORM.glob("*.tf"):
        text = file.read_text(encoding="utf-8")
        assert 'resource "google_secret_manager_secret_version"' not in text, file.name
