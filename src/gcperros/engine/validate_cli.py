"""Línea de comandos del harness: valida el streaming contra el batch (#17).

Con ``--strict`` termina con código 1 si algún escenario comprometido supera
los umbrales, que es lo que la convierte en una puerta de integración continua:
un cambio que degrade la corrección del motor rompe la construcción en vez de
descubrirse en una auditoría al final del semestre.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gcperros.core.contracts import parse_match_event
from gcperros.engine.harness import (
    DEFAULT_SCENARIOS,
    STRESS_SCENARIOS,
    HarnessReport,
    run_harness,
)
from gcperros.engine.watermark import DEFAULT_ALLOWED_LATENESS_S
from gcperros.generators.match import MatchConfig, simulate_match

FAMILIES = {
    "default": DEFAULT_SCENARIOS,
    "stress": STRESS_SCENARIOS,
    "all": DEFAULT_SCENARIOS + STRESS_SCENARIOS,
}


def build_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos."""
    parser = argparse.ArgumentParser(
        prog="gcperros-validate-streaming",
        description="Somete el motor a perturbaciones y compara contra la referencia batch.",
    )
    parser.add_argument("--seed", type=int, help="Semilla con la que resimular el partido.")
    parser.add_argument("--match", type=Path, help="Fichero JSONL con el partido limpio.")
    parser.add_argument(
        "--perturbation-seed", type=int, default=7, help="Semilla de la adversidad."
    )
    parser.add_argument("--scenarios", choices=sorted(FAMILIES), default="default")
    parser.add_argument("--allowed-lateness", type=float, default=DEFAULT_ALLOWED_LATENESS_S)
    parser.add_argument("--report", type=Path, help="Escribe el informe completo en JSON.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Termina con código 1 si algún escenario supera los umbrales.",
    )
    return parser


def _as_dict(report: HarnessReport) -> dict[str, object]:
    return {
        "match_id": report.match_id,
        "allowed_lateness_s": report.allowed_lateness_s,
        "passed": report.passed,
        "scenarios": [
            {
                "name": r.scenario.name,
                "delivered": r.delivered,
                "duplicates_removed": r.duplicates_removed,
                "dropped_late": r.dropped_late,
                "timeliness": r.timeliness,
                "possession_share": r.divergence.possession_share,
                "total_xg": r.divergence.total_xg,
                "goals": r.divergence.goals,
                "events": r.divergence.events,
                "passed": r.passed,
                "breaches": [b.indicator for b in r.divergence.breaches()],
            }
            for r in report.results
        ],
    }


def _table(report: HarnessReport) -> str:
    rows = [f"{'escenario':16} {'tardios':>8} {'oportun.':>9} {'d.pos':>7} {'d.xG':>7}  veredicto"]
    for r in report.results:
        verdict = (
            "pasa"
            if r.passed
            else "FALLA " + ",".join(b.indicator for b in r.divergence.breaches())
        )
        rows.append(
            f"{r.scenario.name:16} {r.dropped_late:8} {r.timeliness:9.4f} "
            f"{r.divergence.possession_share:7.4f} {r.divergence.total_xg:7.4f}  {verdict}"
        )
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if (args.seed is None) == (args.match is None):
        parser.error("indica --seed o --match, pero no ambos")

    if args.seed is not None:
        events = simulate_match(args.seed, MatchConfig())
    else:
        lines = args.match.read_text(encoding="utf-8").splitlines()
        events = [parse_match_event(line) for line in lines if line.strip()]

    report = run_harness(
        events,
        seed=args.perturbation_seed,
        scenarios=FAMILIES[args.scenarios],
        allowed_lateness_s=args.allowed_lateness,
    )

    sys.stdout.write(_table(report))
    if args.report is not None:
        with args.report.open("w", encoding="utf-8", newline="") as handle:
            json.dump(_as_dict(report), handle, ensure_ascii=False, sort_keys=True, indent=2)

    print(
        f"validacion={'PASA' if report.passed else 'FALLA'} escenarios={len(report.results)} "
        f"fallidos={len(report.failures)} margen={report.allowed_lateness_s}s",
        file=sys.stderr,
    )
    return 1 if args.strict and not report.passed else 0


if __name__ == "__main__":
    raise SystemExit(main())
