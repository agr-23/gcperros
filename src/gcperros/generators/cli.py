"""Interfaz de línea de comandos de los generadores sintéticos.

Cada generador emite su flujo como JSON Lines, un evento por línea. Ese formato
es el mismo que viajará por Pub/Sub (HU-10) y el que se persistirá sin
transformar en la capa Raw (HU-14), de modo que un fichero generado aquí sirve
tanto de fixture para las pruebas como de entrada del plano batch de referencia.

Los dos comandos comparten argumentos a propósito: con la misma semilla y la
misma identificación describen el mismo encuentro, uno desde el campo y otro
desde el mercado.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gcperros.generators.match import MatchConfig, simulate_match, summarize_match
from gcperros.generators.odds import simulate_odds, summarize_odds


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Añade los argumentos compartidos por los dos generadores."""
    parser.add_argument(
        "--seed",
        type=int,
        required=True,
        help="Semilla del generador. La misma semilla produce siempre el mismo resultado.",
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
        help="Escribe los agregados en la salida de error.",
    )


def _config_from(args: argparse.Namespace) -> MatchConfig:
    """Traduce los argumentos a la configuración del partido."""
    return MatchConfig(match_id=args.match_id, home_team=args.home, away_team=args.away)


def _write(lines: str, out: Path | None) -> None:
    """Vuelca las líneas al fichero indicado o a la salida estándar.

    El argumento ``newline=""`` evita que Windows convierta el salto de línea en
    retorno de carro más salto: el fichero tiene que salir idéntico byte a byte
    en cualquier sistema operativo, que es la promesa de la HU-8.
    """
    if out is None:
        sys.stdout.write(lines)
        return

    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(lines)


def build_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos del generador de partidos."""
    parser = argparse.ArgumentParser(
        prog="gcperros-generate-match",
        description="Genera un partido sintético determinista en formato JSON Lines.",
    )
    _add_common_arguments(parser)
    return parser


def build_odds_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos del generador de cuotas."""
    parser = argparse.ArgumentParser(
        prog="gcperros-generate-odds",
        description=(
            "Genera el flujo de cuotas del mismo partido, en formato JSON Lines. "
            "El partido se resimula internamente a partir de la semilla."
        ),
    )
    _add_common_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada del generador de partidos."""
    args = build_parser().parse_args(argv)

    events = simulate_match(args.seed, _config_from(args))
    _write("".join(event.to_json() + "\n" for event in events), args.out)

    if args.summary:
        summary = summarize_match(events)
        print(
            f"eventos={summary.event_count} "
            f"goles={summary.goals} "
            f"xG={summary.total_xg} "
            f"remates={summary.shots} "
            f"rojas={summary.red_cards} "
            f"posesiones={summary.possessions}",
            file=sys.stderr,
        )

    return 0


def odds_main(argv: list[str] | None = None) -> int:
    """Punto de entrada del generador de cuotas."""
    args = build_odds_parser().parse_args(argv)

    events = simulate_match(args.seed, _config_from(args))
    updates = simulate_odds(args.seed, events)
    _write("".join(update.to_json() + "\n" for update in updates), args.out)

    if args.summary:
        summary = summarize_odds(updates)
        print(
            f"actualizaciones={summary.update_count} "
            f"disparadores={summary.by_trigger} "
            f"operadores={summary.by_operator} "
            f"overround={summary.mean_overround}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
