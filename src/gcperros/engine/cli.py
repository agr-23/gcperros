"""Línea de comandos del motor: señales de discrepancia (HU-19).

Recorre los dos flujos de un mismo partido y saca las señales por la salida
estándar, una por línea en JSON, con el resumen por la salida de error. Los
canales van separados a propósito: se puede encadenar la salida a otro proceso
sin que el resumen la ensucie.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gcperros.core.contracts import parse_match_event, parse_odds_update
from gcperros.engine.signals import (
    DEFAULT_THRESHOLD,
    DiscrepancySignal,
    detect_discrepancies,
)
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.odds import simulate_odds


def build_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos."""
    parser = argparse.ArgumentParser(
        prog="gcperros-signals",
        description=(
            "Contrasta el modelo propio contra las cuotas vigentes y emite una "
            "señal cuando se separan más del umbral declarado."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Semilla con la que resimular ambos flujos. Alternativa a --match/--odds.",
    )
    parser.add_argument("--match", type=Path, help="Fichero JSONL de eventos del partido.")
    parser.add_argument("--odds", type=Path, help="Fichero JSONL de actualizaciones de cuotas.")
    parser.add_argument("--match-id", default="match-0001", help="Identificador del partido.")
    parser.add_argument("--home", default="HOME", help="Identificador del equipo local.")
    parser.add_argument("--away", default="AWAY", help="Identificador del equipo visitante.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Separación mínima para emitir (por defecto {DEFAULT_THRESHOLD}).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Fichero de salida. Si se omite, escribe en la salida estándar.",
    )
    return parser


def _as_dict(signal: DiscrepancySignal) -> dict[str, object]:
    """Proyecta la señal a la estructura que se publica."""
    return {
        "detected_at": signal.detected_at.strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{signal.detected_at.microsecond // 1000:03d}Z",
        "match_id": signal.match_id,
        "minute": signal.minute,
        "operator": signal.operator,
        "market": signal.market,
        "outcome": signal.outcome,
        "model_probability": signal.model_probability,
        "market_probability": signal.market_probability,
        "divergence": signal.divergence,
    }


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.seed is None and not (args.match and args.odds):
        parser.error("indica --seed, o bien --match y --odds a la vez")

    if args.seed is not None:
        config = MatchConfig(match_id=args.match_id, home_team=args.home, away_team=args.away)
        events = simulate_match(args.seed, config)
        updates = simulate_odds(args.seed, events)
    else:
        events = [
            parse_match_event(line)
            for line in args.match.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        updates = [
            parse_odds_update(line)
            for line in args.odds.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    signals = detect_discrepancies(events, updates, threshold=args.threshold)
    lines = "".join(
        json.dumps(_as_dict(signal), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
        for signal in signals
    )

    if args.out is not None:
        with args.out.open("w", encoding="utf-8", newline="") as handle:
            handle.write(lines)
    else:
        sys.stdout.write(lines)

    widest = max((signal.magnitude for signal in signals), default=0.0)
    print(
        f"señales={len(signals)} umbral={args.threshold} "
        f"mayor_separacion={widest:.3f} evaluadas={len(updates)} cuotas",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
