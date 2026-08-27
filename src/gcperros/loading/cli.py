"""Línea de comandos del cargador de la capa Raw (HU-14).

Consume las suscripciones ``<flujo>-raw`` y persiste cada mensaje sin
transformar en su tabla Raw de BigQuery. Con ``--dry-run`` recorre exactamente
el mismo camino leyendo de un fichero JSONL en vez de una suscripción real, y
escribiendo en memoria en vez de en BigQuery: sirve para comprobar el
cargador antes de tener infraestructura desplegada, igual que
``gcperros-publish --dry-run`` en el lado de publicación.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from gcperros.loading.raw_loader import DEFAULT_MAX_MESSAGES, RawLoader
from gcperros.loading.sink import InMemoryRawSink, RawSink
from gcperros.loading.subscriber import InMemorySubscriber, PulledMessage, PullSubscriber

logger = logging.getLogger("gcperros.load_raw")

#: Nombre corto -> nombre del topic/flujo, tal como lo declara el contrato.
STREAM_TOPICS: dict[str, str] = {
    "match": "match-events",
    "odds": "odds-updates",
}

#: Nombre corto -> tabla Raw que le corresponde. Coincide con
#: `infra/terraform/bigquery.tf`.
STREAM_TABLES: dict[str, str] = {
    "match": "match_events_raw",
    "odds": "odds_updates_raw",
}

_DRY_RUN_NAMESPACE = "gcperros-load-raw-dry-run"


def build_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos."""
    parser = argparse.ArgumentParser(
        prog="gcperros-load-raw",
        description="Persiste sin transformar los mensajes de un flujo en su tabla Raw de "
        "BigQuery.",
    )
    parser.add_argument(
        "--stream",
        choices=["match", "odds", "both"],
        default="both",
        help="Qué flujo cargar. 'both' no es compatible con --loop: cada "
        "flujo tiene su propia suscripción y necesita su propio proceso "
        "de larga duración.",
    )
    parser.add_argument("--project", help="Proyecto de GCP. Obligatorio salvo con --dry-run.")
    parser.add_argument(
        "--subscription-prefix",
        default="",
        help="Prefijo de las suscripciones, igual al 'resource_prefix' de Terraform.",
    )
    parser.add_argument(
        "--dataset",
        default="gcperros_raw",
        help="Dataset de BigQuery donde viven las tablas Raw.",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=DEFAULT_MAX_MESSAGES,
        help="Mensajes por lote de extracción.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="No termina al agotar lo disponible: sigue sondeando indefinidamente.",
    )
    parser.add_argument(
        "--idle-backoff",
        type=float,
        default=5.0,
        help="Segundos de espera entre sondeos vacíos en modo --loop.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Recorre todo el camino sin GCP: lee de --in y persiste en memoria.",
    )
    parser.add_argument(
        "--in",
        dest="input_path",
        type=Path,
        help="Fichero JSONL de entrada para --dry-run (una línea por mensaje, "
        "el mismo formato que producen los generadores).",
    )
    return parser


def _subscription_name(prefix: str, stream_key: str) -> str:
    return f"{prefix}{STREAM_TOPICS[stream_key]}-raw"


def _read_dry_run_messages(path: Path) -> Iterator[PulledMessage]:
    """Envuelve cada línea de un fichero JSONL como si viniera del broker.

    No interpreta el contenido de la línea —sería trabajo del motor, no del
    cargador—; sólo le inventa el sobre que un mensaje real trae puesto:
    identificador, instante de publicación y atributos vacíos. El
    identificador se deriva del contenido y la posición, no de ``uuid4``, por
    la misma razón de reproducibilidad que rige el resto del proyecto: la
    misma entrada produce siempre el mismo ensayo.
    """
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle):
            content = raw_line.rstrip("\n")
            if not content:
                continue
            digest = hashlib.sha256(f"{path}:{line_number}:{content}".encode()).hexdigest()[:16]
            yield PulledMessage(
                ack_id=f"dry-run-ack-{line_number}",
                message_id=f"{_DRY_RUN_NAMESPACE}-{digest}",
                publish_time=datetime.now(UTC),
                data=content.encode("utf-8"),
                attributes={},
            )


def _build_loader(args: argparse.Namespace, stream_key: str) -> RawLoader:
    """Ensambla el cargador de un flujo según los argumentos."""
    stream = STREAM_TOPICS[stream_key]
    subscriber: PullSubscriber
    sink: RawSink

    if args.dry_run:
        if not args.input_path:
            raise SystemExit("--dry-run necesita --in con el fichero JSONL de entrada")
        logger.info("modo de ensayo: leyendo de %s, nada saldrá del proceso", args.input_path)
        subscriber = InMemorySubscriber(_read_dry_run_messages(args.input_path))
        sink = InMemoryRawSink()
    else:
        if not args.project:
            raise SystemExit("hace falta --project para cargar de verdad (o usa --dry-run)")

        from gcperros.loading.bigquery import BigQueryRawSink
        from gcperros.loading.pubsub import PubSubPullSubscriber, using_emulator

        subscription = _subscription_name(args.subscription_prefix, stream_key)
        destino = "el emulador local" if using_emulator() else "Google Cloud"
        logger.info(
            "cargando %s desde %s, proyecto %s, suscripción %s",
            stream,
            destino,
            args.project,
            subscription,
        )
        subscriber = PubSubPullSubscriber(args.project, subscription)
        sink = BigQueryRawSink(args.project, args.dataset, STREAM_TABLES[stream_key])

    return RawLoader(subscriber, sink, stream)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada del cargador."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    )
    args = build_parser().parse_args(argv)

    if args.dry_run and args.stream == "both":
        raise SystemExit(
            "--dry-run necesita --stream match u odds: un fichero de entrada por flujo"
        )
    if args.loop and args.stream == "both":
        raise SystemExit(
            "--loop necesita --stream match u odds: cada flujo corre en su propio proceso"
        )

    stream_keys = ["match", "odds"] if args.stream == "both" else [args.stream]

    for stream_key in stream_keys:
        loader = _build_loader(args, stream_key)
        try:
            if args.loop:
                loader.run_forever(
                    max_messages=args.max_messages,
                    idle_backoff_s=args.idle_backoff,
                )
            else:
                loader.drain(max_messages=args.max_messages)
        finally:
            loader.close()

        stats = loader.stats
        logger.info(
            "flujo %s: %d extraídos, %d persistidos, %d sin confirmar",
            STREAM_TOPICS[stream_key],
            stats.pulled,
            stats.loaded,
            stats.failed,
        )
        if stats.failed:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
