"""Interfaz de línea de comandos del generador de partidos.

Emite el partido como JSON Lines, un evento por línea. Ese formato es el mismo
que viajará por Pub/Sub (HU-10) y el que se persistirá sin transformar en la
capa Raw (HU-14), de modo que un fichero generado aquí sirve tanto de fixture
para las pruebas como de entrada del plano batch de referencia.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gcperros.generators.match import (
    MatchConfig,
    simulate_match,
    summarize_match,
)


def build_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos."""
    parser = argparse.ArgumentParser(
        prog="gcperros-generate-match",
        description="Genera un partido sintético determinista en formato JSON Lines.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        required=True,
        help="Semilla del generador. La misma semilla produce siempre el mismo partido.",
    )
    parser.add_argument("--match-id", default="match-0001", help="Identificador del partido.")
    parser.add_argument("--home", default="HOME", help="Identificador del equipo local.")
    parser.add_argument("--away", default="AWAY", help="Identificador del equipo visitante.")
    parser.add_argument(
        "--out",
        type=Path,
        help="Fichero de salida. Si se omite, escribe en la salida estándar.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Escribe los agregados del partido en la salida de error.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada del ejecutable."""
    args = build_parser().parse_args(argv)

    config = MatchConfig(
        match_id=args.match_id,
        home_team=args.home,
        away_team=args.away,
    )
    events = simulate_match(args.seed, config)
    lines = "".join(f"{event.to_json()}\n" for event in events)

    if args.out is not None:
        # newline="" evita que Windows traduzca \n a \r\n: el fichero debe ser
        # idéntico byte a byte en cualquier sistema operativo.
        with args.out.open("w", encoding="utf-8", newline="") as handle:
            handle.write(lines)
    else:
        sys.stdout.write(lines)

    if args.summary:
        summary = summarize_match(events)
        print(
            f"eventos={summary.event_count} "
            f"goles={summary.goals} "
            f"xG={summary.total_xg} "
            f"remates={summary.shots} "
            f"posesiones={summary.possessions}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
