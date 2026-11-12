"""Fútbol frente a baloncesto, medidos con la misma vara: ``gcperros-compare-sports`` (#91).

Es la tabla que pide la entrega final, reproducible desde una semilla: para cada
deporte, sobre los mismos partidos y los mismos escenarios del harness (#17),
cuántos eventos llegan por minuto, cuál es el margen de marca de agua más corto
que cumple el OE-2, cuánto se aplica a tiempo, cuánto se separa la posesión del
batch, cuánto espera cada evento y cuánto aguanta el motor.

Con ``--strict`` es una puerta: termina con 1 si algún escenario comprometido
falla en algún deporte con su margen declarado.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from gcperros.engine.benchmark import run_benchmark
from gcperros.engine.sport_harness import SPORTS, SportProfile, run_sport_harness

#: Márgenes del barrido, en segundos. Incluye los dos elegidos (10 y 15).
DEFAULT_MARGINS: tuple[float, ...] = (2.0, 5.0, 8.0, 10.0, 15.0, 20.0, 30.0)

#: El escenario con el que se lee la latencia: el mismo con que se eligió el margen.
LATENCY_SCENARIO = "desorden-medio"


@dataclass(frozen=True, slots=True)
class SportComparison:
    """Lo medido de un deporte, con su margen declarado."""

    sport: str
    matches: int
    events_per_minute: float
    declared_margin_s: float
    minimum_margin_s: float | None
    committed_passed: int
    committed_total: int
    timeliness: float
    possession_gap: float
    latency_p50_s: float
    latency_p95_s: float
    latency_max_s: float
    capacity_events_per_s: float | None

    @property
    def passed(self) -> bool:
        """Si cumple todos los escenarios comprometidos con su margen declarado."""
        return self.committed_passed == self.committed_total


def _passes_everywhere(sport: SportProfile, seeds: range, margin_s: float) -> bool:
    return all(
        result.passed
        for seed in seeds
        for result in run_sport_harness(
            sport, sport.simulate(seed), seed, allowed_lateness_s=margin_s
        )
    )


def compare(
    sport: SportProfile, seeds: range, margins: tuple[float, ...], capacity: bool = True
) -> SportComparison:
    """Mide un deporte sobre ``seeds`` partidos, a su margen y en el barrido."""
    matches = [(seed, sport.simulate(seed)) for seed in seeds]
    results = [
        result for seed, events in matches for result in run_sport_harness(sport, events, seed)
    ]
    latency = [r.run.latency for r in results if r.scenario.name == LATENCY_SCENARIO]
    minutes = [(e[-1].event_time - e[0].event_time).total_seconds() / 60 for _, e in matches]
    minimum = next((m for m in sorted(margins) if _passes_everywhere(sport, seeds, m)), None)
    events = matches[0][1]
    cost = run_benchmark(events, (1.0,), sport.engine).mean_cost_s if capacity else None
    return SportComparison(
        sport=sport.name,
        matches=len(matches),
        events_per_minute=round(sum(len(e) for _, e in matches) / sum(minutes), 2),
        declared_margin_s=sport.allowed_lateness_s,
        minimum_margin_s=minimum,
        committed_passed=sum(r.passed for r in results),
        committed_total=len(results),
        timeliness=round(min(r.run.timeliness for r in results), 4),
        possession_gap=max(r.divergence.possession_share for r in results),
        latency_p50_s=round(statistics.fmean(s.p50_s for s in latency), 1),
        latency_p95_s=round(statistics.fmean(s.p95_s for s in latency), 1),
        latency_max_s=round(max(s.max_s for s in latency), 1),
        capacity_events_per_s=round(1 / cost) if cost else None,
    )


def markdown(rows: list[SportComparison]) -> str:
    """La tabla lado a lado, lista para el documento de diseño."""

    def margin(value: float | None) -> str:
        return "—" if value is None else f"{value:g} s"

    lines: list[tuple[str, Callable[[SportComparison], str]]] = [
        ("Partidos medidos", lambda r: str(r.matches)),
        ("Eventos por minuto", lambda r: f"{r.events_per_minute:.1f}"),
        ("Margen mínimo que cumple el OE-2", lambda r: margin(r.minimum_margin_s)),
        ("Margen declarado", lambda r: margin(r.declared_margin_s)),
        ("Escenarios comprometidos", lambda r: f"{r.committed_passed}/{r.committed_total}"),
        ("Oportunidad (peor partido)", lambda r: f"{r.timeliness:.2%}"),
        ("Separación de posesión (máx.)", lambda r: f"{r.possession_gap:.4f}"),
        ("Latencia p50 / p95", lambda r: f"{r.latency_p50_s:g} / {r.latency_p95_s:g} s"),
        ("Latencia máxima", lambda r: f"{r.latency_max_s:g} s"),
        (
            "Capacidad del motor",
            lambda r: (
                "—" if r.capacity_events_per_s is None else f"{r.capacity_events_per_s:,} ev/s"
            ),
        ),
    ]
    head = "| | " + " | ".join(r.sport for r in rows) + " |"
    rule = "|---|" + "---|" * len(rows)
    body = [f"| {label} | " + " | ".join(cell(r) for r in rows) + " |" for label, cell in lines]
    return "\n".join([head, rule, *body]) + "\n"


def build_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos."""
    parser = argparse.ArgumentParser(
        prog="gcperros-compare-sports",
        description="Mide el motor con fútbol y con baloncesto, lado a lado.",
    )
    parser.add_argument("--matches", type=int, default=12, help="Partidos por deporte.")
    parser.add_argument(
        "--margins",
        default=",".join(f"{m:g}" for m in DEFAULT_MARGINS),
        help="Márgenes del barrido, separados por comas. Vacío para no barrer.",
    )
    parser.add_argument("--no-capacity", action="store_true", help="No mide la capacidad.")
    parser.add_argument("--report", type=Path, help="Escribe la comparación en JSON.")
    parser.add_argument("--strict", action="store_true", help="Falla si un deporte no cumple.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada."""
    args = build_parser().parse_args(argv)
    margins = tuple(float(m) for m in args.margins.split(",") if m.strip())
    rows = [
        compare(sport, range(args.matches), margins, capacity=not args.no_capacity)
        for sport in SPORTS.values()
    ]
    sys.stdout.write(markdown(rows))
    if args.report:
        payload = [asdict(row) | {"passed": row.passed} for row in rows]
        args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    failing = [row.sport for row in rows if not row.passed]
    if failing:
        print(f"no cumplen con su margen declarado: {', '.join(failing)}", file=sys.stderr)
    return 1 if args.strict and failing else 0


if __name__ == "__main__":
    raise SystemExit(main())
