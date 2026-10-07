"""Línea de comandos del banco de carga: dónde se satura el motor (#18).

Imprime la tabla de tasas y señala la primera que el motor no sostiene. Con
``--report`` deja el informe entero en JSON, que es lo que permite comparar
dos máquinas o dos versiones del motor sin leer tablas a ojo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gcperros.core.contracts import parse_match_event
from gcperros.engine.benchmark import (
    DEFAULT_RATES,
    DEFAULT_REPEATS,
    BenchmarkReport,
    run_benchmark,
)
from gcperros.generators.match import MatchConfig, simulate_match


def _rates(text: str) -> tuple[float, ...]:
    """Tasas separadas por comas, en eventos por segundo y en orden creciente."""
    try:
        rates = tuple(float(item) for item in text.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("las tasas deben ser números") from error
    if any(rate <= 0.0 for rate in rates):
        raise argparse.ArgumentTypeError("las tasas deben ser positivas")
    return tuple(sorted(rates))


def build_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos."""
    parser = argparse.ArgumentParser(
        prog="gcperros-benchmark",
        description="Mide el coste por evento y barre tasas de emisión hasta saturar el motor.",
    )
    parser.add_argument("--seed", type=int, help="Semilla con la que resimular el partido.")
    parser.add_argument("--match", type=Path, help="Fichero JSONL con el partido limpio.")
    parser.add_argument(
        "--rates",
        type=_rates,
        default=DEFAULT_RATES,
        help="Tasas de emisión en eventos por segundo, separadas por comas.",
    )
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--report", type=Path, help="Escribe el informe completo en JSON.")
    return parser


def _as_dict(report: BenchmarkReport) -> dict[str, object]:
    return {
        "match_id": report.match_id,
        "events": report.events,
        "mean_cost_s": report.mean_cost_s,
        "capacity_events_per_s": report.capacity_events_per_s,
        "saturation_rate": report.saturation_rate,
        "rates": [
            {
                "rate_events_per_s": r.rate_events_per_s,
                "utilization": r.utilization,
                "p50_s": r.p50_s,
                "p95_s": r.p95_s,
                "max_s": r.max_s,
                "max_backlog": r.max_backlog,
                "final_backlog": r.final_backlog,
                "saturated": r.saturated,
            }
            for r in report.results
        ],
    }


def _table(report: BenchmarkReport) -> str:
    rows = [f"{'tasa ev/s':>10} {'util.':>7} {'p50 ms':>9} {'p95 ms':>9} {'backlog':>8}  veredicto"]
    for r in report.results:
        rows.append(
            f"{r.rate_events_per_s:10.0f} {r.utilization:7.4f} {r.p50_s * 1e3:9.3f} "
            f"{r.p95_s * 1e3:9.3f} {r.max_backlog:8d}  {'satura' if r.saturated else 'sostiene'}"
        )
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if (args.seed is None) == (args.match is None):
        parser.error("indica --seed o --match, pero no ambos")
    if args.repeats < 1:
        parser.error("hace falta al menos una repetición")

    if args.seed is not None:
        events = simulate_match(args.seed, MatchConfig())
    else:
        lines = args.match.read_text(encoding="utf-8").splitlines()
        events = [parse_match_event(line) for line in lines if line.strip()]

    report = run_benchmark(events, rates=args.rates, repeats=args.repeats)

    sys.stdout.write(_table(report))
    if args.report is not None:
        with args.report.open("w", encoding="utf-8", newline="") as handle:
            json.dump(_as_dict(report), handle, ensure_ascii=False, sort_keys=True, indent=2)

    saturation = f"{report.saturation_rate:.0f}" if report.saturation_rate else "ninguna"
    print(
        f"coste={report.mean_cost_s * 1e6:.1f}us capacidad={report.capacity_events_per_s:.0f}ev/s "
        f"saturacion={saturation} eventos={report.events}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
