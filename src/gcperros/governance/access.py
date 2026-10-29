"""Matriz de control de acceso: quién puede ver qué activo (historia #27).

Se deriva del catálogo con cuatro reglas, en este orden, en vez de escribirse a
mano casilla por casilla: una tabla de noventa casillas no se revisa, y cuatro
reglas sí.

1. El responsable de un activo lo **administra**.
2. Nadie más ve la **clave** de seudonimización: es lo único que reidentifica.
3. Un dato **personal** sólo se ve **agregado** fuera de su responsable.
4. El **cliente** que mira el panel ve indicadores, señales e informes, y nada
   más; el equipo ve el resto de datos sintéticos.

``tests/test_access.py`` comprueba lo que de verdad importa por encima de las
reglas: nadie puede leer filas de datos personales y a la vez tener la clave.
"""

from __future__ import annotations

from enum import StrEnum

from gcperros.governance.catalog import CATALOG, Asset, AssetKind, Role, asset


class Principal(StrEnum):
    """Quién pide acceso: cada rol del equipo y el cliente del panel."""

    GOVERNANCE = Role.GOVERNANCE.value
    PIPELINES = Role.PIPELINES.value
    ARCHITECTURE = Role.ARCHITECTURE.value
    CLIENT = "client"


class Access(StrEnum):
    """Nivel de acceso, de menos a más."""

    NONE = "none"
    AGGREGATE = "aggregate"
    READ = "read"
    MANAGE = "manage"


#: Lo que el cliente del panel puede ver: lo que se le enseña, no de dónde sale.
CLIENT_VISIBLE = frozenset({AssetKind.INDICATOR, AssetKind.SIGNAL, AssetKind.REPORT})


def _level(principal: Principal, entry: Asset) -> Access:
    if principal.value == entry.owner.value:
        return Access.MANAGE
    if entry.kind is AssetKind.KEY:
        return Access.NONE
    if principal is Principal.CLIENT:
        return Access.READ if entry.kind in CLIENT_VISIBLE and not entry.personal else Access.NONE
    return Access.AGGREGATE if entry.personal else Access.READ


def access(principal: Principal, name: str) -> Access:
    """Qué puede hacer ``principal`` con el activo ``name``.

    Raises:
        KeyError: Si el activo no está catalogado: lo que no está catalogado no
            tiene acceso definido, y por tanto no se concede.
    """
    return _level(principal, asset(name))


#: La matriz completa, materializada para consultarla o exportarla.
MATRIX: dict[str, dict[Principal, Access]] = {
    entry.name: {principal: _level(principal, entry) for principal in Principal}
    for entry in CATALOG
}
