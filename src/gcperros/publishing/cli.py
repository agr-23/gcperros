"""Línea de comandos que lleva los dos flujos al broker (HU-10).

Genera el partido y sus cuotas a partir de una semilla y los publica en
``match-events`` y ``odds-updates``. Con ``--dry-run`` recorre exactamente el
mismo camino sin salir del proceso, lo que sirve para comprobar el trabajo antes
de tener broker delante.
"""

from __future__ import annotations

import argparse
import logging
import sys

from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.odds import simulate_odds
from gcperros.publishing.publisher import (
    MATCH_EVENTS_TOPIC,
    ODDS_UPDATES_TOPIC,
    RetryPolicy,
    StreamPublisher,
)
from gcperros.publishing.transport import InMemoryTransport, Transport

logger = logging.getLogger("gcperros.publish")


def build_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos."""
    parser = argparse.ArgumentParser(
        prog="gcperros-publish",
        description="Publica el partido y sus cuotas en los topics de Pub/Sub.",
    )
    parser.add_argument("--seed", type=int, required=True, help="Semilla de los generadores.")
    parser.add_argument("--match-id", default="match-0001", help="Identificador del partido.")
    parser.add_argument("--home", default="HOME", help="Equipo local.")
    parser.add_argument("--away", default="AWAY", help="Equipo visitante.")
    parser.add_argument(
        "--project",
        help="Proyecto de GCP. Obligatorio salvo con --dry-run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Recorre todo el camino sin publicar: usa un transporte en memoria.",
    )
    parser.add_argument(
        "--create-topics",
        action="store_true",
        help="Crea los topics si no existen. Sólo para el emulador: en un "
        "proyecto real los crea Terraform.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=RetryPolicy().max_attempts,
        help="Intentos de publicación antes de darse por vencido.",
    )
    parser.add_argument(
        "--only",
        choices=["match", "odds", "both"],
        default="both",
        help="Qué flujo publicar.",
    )
    return parser


def _build_transport(args: argparse.Namespace) -> Transport:
    """Elige el transporte según los argumentos.

    Raises:
        SystemExit: Si falta el proyecto para una publicación real.
    """
    if args.dry_run:
        logger.info("modo de ensayo: nada saldrá del proceso")
        return InMemoryTransport()

    if not args.project:
        raise SystemExit("hace falta --project para publicar de verdad (o usa --dry-run)")

    from gcperros.publishing.pubsub import PubSubTransport, using_emulator

    destino = "el emulador local" if using_emulator() else "Google Cloud"
    logger.info("publicando en %s, proyecto %s", destino, args.project)

    transport = PubSubTransport(project_id=args.project)
    if args.create_topics:
        for topic in (MATCH_EVENTS_TOPIC, ODDS_UPDATES_TOPIC):
            transport.ensure_topic(topic)
            logger.info("topic listo: %s", topic)
    return transport


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada del publicador."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    )
    args = build_parser().parse_args(argv)

    config = MatchConfig(match_id=args.match_id, home_team=args.home, away_team=args.away)
    events = simulate_match(args.seed, config)
    updates = simulate_odds(args.seed, events)
    logger.info("generados %d eventos y %d cuotas", len(events), len(updates))

    transport = _build_transport(args)
    publisher = StreamPublisher(transport, policy=RetryPolicy(max_attempts=args.max_attempts))

    try:
        if args.only in {"match", "both"}:
            publisher.publish_match_events(events)
        if args.only in {"odds", "both"}:
            publisher.publish_odds_updates(updates)
    finally:
        publisher.close()

    stats = publisher.stats
    logger.info(
        "publicados %d mensajes (%s) con %d reintentos",
        stats.published,
        ", ".join(f"{topic}={count}" for topic, count in stats.by_topic.items()),
        stats.retries,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
