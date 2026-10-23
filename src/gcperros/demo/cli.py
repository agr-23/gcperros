"""Línea de comandos de la demostración: ``gcperros-demo`` (#30).

Simula el partido de la semilla y lo sirve en vivo en ``http://127.0.0.1:8000``.
No necesita red ni cuenta de GCP: la misma semilla da la misma demo en clase
que en casa.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from gcperros.demo.replay import MatchReplay
from gcperros.demo.server import DEFAULT_SPEED, LiveSource, create_app
from gcperros.generators.match import MatchConfig, simulate_match


def build_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos."""
    parser = argparse.ArgumentParser(
        prog="gcperros-demo",
        description="Sirve un partido simulado en vivo para enseñarlo a un cliente.",
    )
    parser.add_argument("--seed", type=int, default=20260826, help="Semilla del partido.")
    parser.add_argument("--home", default="RMA", help="Equipo local.")
    parser.add_argument("--away", default="BAR", help="Equipo visitante.")
    parser.add_argument(
        "--speed",
        type=float,
        default=DEFAULT_SPEED,
        help="Minutos de partido por minuto real.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.speed <= 0.0:
        parser.error("la velocidad debe ser positiva")

    config = MatchConfig(match_id=f"demo-{args.seed}", home_team=args.home, away_team=args.away)
    source = LiveSource(MatchReplay(simulate_match(args.seed, config)), speed=args.speed)
    print(
        f"partido={source.match_id} velocidad=x{args.speed:g} "
        f"estado=http://{args.host}:{args.port}/api/matches/{source.match_id}/state",
        file=sys.stderr,
    )
    uvicorn.run(create_app(source), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
