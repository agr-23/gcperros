"""Línea de comandos de la frontera de ingestión (HU-16).

Se comporta como un filtro: lee un flujo JSON Lines, **deja pasar lo conforme
por la salida estándar** y archiva lo demás en el repositorio de inválidos, con
el resumen por la salida de error. Así la frontera se puede intercalar delante
de cualquier consumidor sin que este se entere:

```bash
gcperros-generate-match --seed 20260826 --out partido.jsonl
gcperros-validate --stream match --in partido.jsonl --invalid invalidos.jsonl
```

El mensaje conforme se reemite **tal como llegó**, sin volver a serializarlo. La
frontera decide qué pasa, no cómo se ve: reescribir de salida un mensaje que se
acaba de dar por bueno introduciría una diferencia que nadie pidió y que
rompería cualquier comparación byte a byte aguas abajo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gcperros.core.contracts import MatchEvent, OddsUpdate
from gcperros.governance.gate import (
    IngestionGate,
    match_event_gate,
    odds_update_gate,
)
from gcperros.governance.quarantine import (
    InMemoryInvalidStore,
    InvalidEventStore,
    JsonlInvalidStore,
)

#: Nombre corto de cada flujo en la línea de comandos, y la frontera que le
#: corresponde.
STREAMS = ("match", "odds")


def build_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos."""
    parser = argparse.ArgumentParser(
        prog="gcperros-validate",
        description=(
            "Valida un flujo contra su contrato de datos. Lo conforme sale por la "
            "salida estándar; lo que incumple se archiva con su causa."
        ),
    )
    parser.add_argument(
        "--stream",
        choices=STREAMS,
        required=True,
        help="Flujo al que pertenecen los mensajes.",
    )
    parser.add_argument(
        "--in",
        dest="source",
        type=Path,
        help="Fichero de entrada. Si se omite, lee de la entrada estándar.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Dónde escribir los mensajes conformes. Por defecto, la salida estándar.",
    )
    parser.add_argument(
        "--invalid",
        type=Path,
        help=(
            "Repositorio de eventos inválidos. Si se omite, los rechazos se "
            "cuentan pero no se persisten."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Termina con código 1 si algún mensaje fue rechazado.",
    )
    return parser


def _read_lines(source: Path | None) -> list[str]:
    """Lee el flujo de entrada, descartando las líneas en blanco."""
    text = source.read_text(encoding="utf-8") if source is not None else sys.stdin.read()
    return [line for line in text.splitlines() if line.strip()]


def _build_store(invalid: Path | None) -> InvalidEventStore:
    """Elige dónde se archivan los rechazos."""
    return InMemoryInvalidStore() if invalid is None else JsonlInvalidStore(invalid)


def _build_gate(
    stream: str, store: InvalidEventStore
) -> IngestionGate[MatchEvent] | IngestionGate[OddsUpdate]:
    """Elige la frontera del flujo indicado."""
    return match_event_gate(store) if stream == "match" else odds_update_gate(store)


def _write(lines: list[str], out: Path | None) -> None:
    """Vuelca los mensajes conformes, con salto de línea normalizado."""
    payload = "".join(line + "\n" for line in lines)
    if out is None:
        sys.stdout.write(payload)
        return
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(payload)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la frontera.

    Returns:
        ``0`` si todo fue bien, ``1`` si hubo rechazos y se pidió ``--strict``.
    """
    args = build_parser().parse_args(argv)

    store = _build_store(args.invalid)
    gate = _build_gate(args.stream, store)

    conforming: list[str] = []
    try:
        for line in _read_lines(args.source):
            if gate.admit(line) is not None:
                conforming.append(line)
    finally:
        gate.close()

    _write(conforming, args.out)

    stats = gate.stats
    causes = ", ".join(f"{rule}={count}" for rule, count in sorted(stats.by_rule.items()))
    print(
        f"flujo={args.stream} "
        f"vistos={stats.seen} "
        f"conformes={stats.admitted} "
        f"rechazados={stats.rejected} "
        f"conformidad={stats.conformity:.4f}" + (f" motivos=({causes})" if causes else ""),
        file=sys.stderr,
    )

    return 1 if args.strict and stats.rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
