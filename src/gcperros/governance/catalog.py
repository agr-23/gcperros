"""Catálogo de datos: qué existe, dónde vive y quién responde (historia #24).

Cada dato tiene un responsable declarado: quien decide cuándo cambia, responde
cuando falla, recibe el escalado de la calidad (historia #26) y concede el acceso
(historia #27). Es dato, como el glosario, y por la misma razón: se comprueba.
``tests/test_catalog.py`` lo contrasta contra el Terraform, de modo que un topic
o una tabla nueva sin catalogar rompe la construcción.

Los responsables son **roles**, no personas: el rol sobrevive a que alguien deje
el equipo, y quién lo ocupa hoy se declara en un solo sitio.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from gcperros.firestore.publisher import LIVE_MATCHES_COLLECTION


class Role(StrEnum):
    """Los roles del equipo que pueden ser responsables de un dato."""

    GOVERNANCE = "governance"
    PIPELINES = "pipelines"
    ARCHITECTURE = "architecture"


@dataclass(frozen=True, slots=True)
class Owner:
    """Quién ocupa un rol."""

    role: Role
    title: str
    person: str


#: Quién ocupa cada rol hoy. Es el único sitio donde aparece una persona.
OWNERS: Mapping[Role, Owner] = {
    Role.GOVERNANCE: Owner(
        Role.GOVERNANCE, "Oficial de Gobernanza / Líder DataOps", "Alejandro Garcés"
    ),
    Role.PIPELINES: Owner(
        Role.PIPELINES, "Ingeniero de Pipelines / Big Data", "Jean Carlo Londoño"
    ),
    Role.ARCHITECTURE: Owner(Role.ARCHITECTURE, "Arquitecto de Datos / Cloud", "Tomás Londoño"),
}


class AssetKind(StrEnum):
    """Qué clase de dato es un activo."""

    TOPIC = "topic"
    TABLE = "table"
    DOCUMENT = "document"
    REPOSITORY = "repository"


@dataclass(frozen=True, slots=True)
class Asset:
    """Un dato del sistema.

    Attributes:
        name: Identificador físico, tal como lo nombra la infraestructura.
        kind: Qué clase de dato es.
        owner: Rol responsable.
        description: Qué contiene, en una frase.
        terms: Términos del glosario necesarios para interpretarlo.
    """

    name: str
    kind: AssetKind
    owner: Role
    description: str
    terms: tuple[str, ...] = ()


def _stream_assets(stream: str, contents: str) -> tuple[Asset, ...]:
    """El topic de un flujo, su dead letter y su tabla Raw: el Terraform crea los tres."""
    table = stream.replace("-", "_")
    return (
        Asset(stream, AssetKind.TOPIC, Role.PIPELINES, f"{contents}, tal como se publican."),
        Asset(
            f"{stream}-dead-letter",
            AssetKind.TOPIC,
            Role.ARCHITECTURE,
            "Mensajes válidos que el motor no logró procesar tras varios intentos.",
        ),
        Asset(
            f"gcperros_raw.{table}_raw",
            AssetKind.TABLE,
            Role.ARCHITECTURE,
            f"{contents}, crudos y sin interpretar: el archivo del que se recalcula todo.",
        ),
    )


def _analytics(table: str, description: str, terms: tuple[str, ...] = ()) -> Asset:
    return Asset(
        f"gcperros_analytics.{table}", AssetKind.TABLE, Role.ARCHITECTURE, description, terms
    )


#: Los datasets del sistema, en el orden en que los recorre un evento.
DATASETS: tuple[Asset, ...] = (
    *_stream_assets("match-events", "Las acciones del partido"),
    *_stream_assets("odds-updates", "Las cuotas de cada operador"),
    Asset(
        "invalid-events",
        AssetKind.REPOSITORY,
        Role.GOVERNANCE,
        "Mensajes que incumplieron el contrato, archivados crudos y con su causa.",
    ),
    Asset(
        LIVE_MATCHES_COLLECTION,
        AssetKind.DOCUMENT,
        Role.ARCHITECTURE,
        "Un documento vivo por partido con sus indicadores y su linaje.",
        ("possession", "xg", "lineage"),
    ),
    _analytics("dim_match", "Partidos: jornada, temporada, equipos y fecha."),
    _analytics("dim_market", "Mercados de cuotas y sus resultados posibles."),
    _analytics("dim_operator", "Operadores de apuestas."),
    _analytics("fact_match_events", "Un hecho por evento del partido.", ("xg",)),
    _analytics(
        "fact_market_signals",
        "Una fila por señal de discrepancia emitida.",
        ("discrepancy_signal", "implied_probability", "operator_margin"),
    ),
)

#: El catálogo completo.
CATALOG: tuple[Asset, ...] = DATASETS


def asset(name: str) -> Asset:
    """Busca un activo por su nombre.

    Raises:
        KeyError: Si no está catalogado.
    """
    for entry in CATALOG:
        if entry.name == name:
            return entry
    raise KeyError(f"{name!r} no está en el catálogo")
