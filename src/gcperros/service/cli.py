"""Arranque del motor en Cloud Run: ``gcperros-engine-service``.

``PORT`` lo pone Cloud Run y ``GOOGLE_CLOUD_PROJECT`` el Terraform. En local,
``--memory`` cambia Firestore por un almacén en memoria.
"""

from __future__ import annotations

import argparse
import os

import uvicorn

from gcperros.firestore.client import FirestoreDocumentStore
from gcperros.firestore.store import DocumentStore, InMemoryDocumentStore
from gcperros.service.app import EngineService, create_service


def build_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos."""
    parser = argparse.ArgumentParser(
        prog="gcperros-engine-service",
        description="El motor detrás del endpoint push de Pub/Sub, con Firestore detrás.",
    )
    # En local sólo se escucha a sí mismo; el contenedor declara HOST para
    # aceptar lo que le llega de fuera (Dockerfile).
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--memory", action="store_true", help="Firestore en memoria, para local.")
    return parser


def _store(args: argparse.Namespace) -> DocumentStore:
    if args.memory:
        return InMemoryDocumentStore()
    if not args.project:
        raise SystemExit("hace falta --project o GOOGLE_CLOUD_PROJECT (o --memory en local)")
    return FirestoreDocumentStore(args.project)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada."""
    args = build_parser().parse_args(argv)
    app = create_service(EngineService(_store(args)))
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
