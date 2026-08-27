"""Líneas de comandos de la capa de gobernanza (HU-16, HU-17).

``gcperros-validate`` es la frontera de contrato, y se comporta como un filtro:
lee un flujo JSON Lines, deja pasar lo conforme por la salida estándar y archiva
lo demás en el repositorio de inválidos, con el resumen por la salida de error.

```bash
gcperros-generate-match --seed 20260826 --out partido.jsonl
gcperros-validate --stream match --in partido.jsonl --invalid invalidos.jsonl
```

El mensaje conforme se reemite **tal como llegó**, sin volver a serializarlo. La
frontera decide qué pasa, no cómo se ve: reescribir de salida un mensaje que se
acaba de dar por bueno introduciría una diferencia que nadie pidió y que
rompería cualquier comparación byte a byte aguas abajo.

``gcperros-quality`` recorre la ingestión completa —frontera y motor— y emite el
informe de calidad de esa pasada. Es lo que convierte la calidad en una señal
continua en lugar de una auditoría al final: se mide en el mismo acto de
ingerir, no en un ejercicio aparte que alguien tiene que acordarse de ejecutar.

``gcperros-trace`` explica de dónde sale un número: qué eventos lo formaron, qué
modelo lo calculó y bajo qué contrato llegaron. Sin argumentos extra audita
todos los indicadores del partido; con ``--indicator`` responde por uno solo,
que es el «auditable a demanda» que pide la HU-18.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gcperros.core.contracts import MatchEvent, OddsUpdate
from gcperros.engine.pipeline import MatchEngine
from gcperros.governance.gate import (
    IngestionGate,
    match_event_gate,
    odds_update_gate,
)
from gcperros.governance.quality import IngestionEvidence, QualityReport, assess
from gcperros.governance.quarantine import (
    InMemoryInvalidStore,
    InvalidEventStore,
    JsonlInvalidStore,
)
from gcperros.governance.traceability import audit, explain

#: Nombre corto de cada flujo en la línea de comandos.
STREAMS = ("match", "odds")

#: Identificador del flujo, tal como lo nombra el contrato.
STREAM_NAMES = {"match": "match-events", "odds": "odds-updates"}


###############################################################################
# Argumentos compartidos
###############################################################################


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Añade los argumentos que comparten los dos comandos."""
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
        "--invalid",
        type=Path,
        help=(
            "Repositorio de eventos inválidos. Si se omite, los rechazos se "
            "cuentan pero no se persisten."
        ),
    )


def _read_lines(source: Path | None) -> list[str]:
    """Lee el flujo de entrada, descartando las líneas en blanco."""
    text = source.read_text(encoding="utf-8") if source is not None else sys.stdin.read()
    return [line for line in text.splitlines() if line.strip()]


def _build_store(invalid: Path | None) -> InvalidEventStore:
    """Elige dónde se archivan los rechazos."""
    return InMemoryInvalidStore() if invalid is None else JsonlInvalidStore(invalid)


def _write(payload: str, out: Path | None) -> None:
    """Vuelca texto al fichero indicado o a la salida estándar.

    ``newline=""`` evita que Windows convierta el salto en retorno de carro más
    salto: la salida tiene que ser idéntica byte a byte en cualquier sistema.
    """
    if out is None:
        sys.stdout.write(payload)
        return
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(payload)


###############################################################################
# gcperros-validate
###############################################################################


def build_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos de la frontera."""
    parser = argparse.ArgumentParser(
        prog="gcperros-validate",
        description=(
            "Valida un flujo contra su contrato de datos. Lo conforme sale por la "
            "salida estándar; lo que incumple se archiva con su causa."
        ),
    )
    _add_common_arguments(parser)
    parser.add_argument(
        "--out",
        type=Path,
        help="Dónde escribir los mensajes conformes. Por defecto, la salida estándar.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Termina con código 1 si algún mensaje fue rechazado.",
    )
    return parser


def _build_gate(
    stream: str, store: InvalidEventStore
) -> IngestionGate[MatchEvent] | IngestionGate[OddsUpdate]:
    """Elige la frontera del flujo indicado."""
    return match_event_gate(store) if stream == "match" else odds_update_gate(store)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la frontera.

    Returns:
        ``0`` si todo fue bien, ``1`` si hubo rechazos y se pidió ``--strict``.
    """
    args = build_parser().parse_args(argv)

    gate = _build_gate(args.stream, _build_store(args.invalid))
    conforming: list[str] = []
    try:
        for line in _read_lines(args.source):
            if gate.admit(line) is not None:
                conforming.append(line)
    finally:
        gate.close()

    _write("".join(line + "\n" for line in conforming), args.out)

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


###############################################################################
# gcperros-quality
###############################################################################


def build_quality_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos del informe de calidad."""
    parser = argparse.ArgumentParser(
        prog="gcperros-quality",
        description=(
            "Ingiere un flujo por la frontera y el motor, y emite el informe de "
            "calidad de esa pasada."
        ),
    )
    _add_common_arguments(parser)
    parser.add_argument(
        "--report",
        type=Path,
        help="Dónde escribir el informe JSON. Por defecto, la salida estándar.",
    )
    parser.add_argument(
        "--scope",
        help="Qué se está midiendo. Por defecto, el nombre del flujo.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Termina con código 1 si alguna regla no alcanza su umbral.",
    )
    return parser


def _match_evidence(lines: list[str], store: InvalidEventStore) -> IngestionEvidence:
    """Ingiere el flujo de partido por la frontera y el motor.

    El motor solo ve lo que la frontera admitió, que es el orden que fija la
    HU-16. Sus contadores son los que aportan unicidad y oportunidad.
    """
    gate = match_event_gate(store)
    engine = MatchEngine()
    try:
        for line in lines:
            event = gate.admit(line)
            if event is not None:
                engine.process(event)
        engine.flush()
    finally:
        gate.close()

    return IngestionEvidence(
        gate=gate.stats,
        dedup=engine.dedup_stats,
        watermark=engine.watermark_stats,
    )


def _odds_evidence(lines: list[str], store: InvalidEventStore) -> IngestionEvidence:
    """Ingiere el flujo de cuotas, que no pasa por el motor.

    Sin motor no hay deduplicación ni marca de agua, así que dos de las tres
    dimensiones se quedan sin medir. El informe lo dice en lugar de darlas por
    buenas.
    """
    gate = odds_update_gate(store)
    try:
        gate.admit_all(lines)
    finally:
        gate.close()
    return IngestionEvidence(gate=gate.stats)


def _describe(report: QualityReport) -> str:
    """Redacta el informe para que se lea de un vistazo."""
    veredicto = "PASA" if report.passed else "FALLA"
    lines = [f"calidad={veredicto} alcance={report.scope}"]
    lines.extend(
        f"  {'ok ' if m.passed else 'NO '} {m.rule.dimension.value:<12} "
        f"{m.value:.4f} (minimo {m.rule.minimum}) sobre {m.total} mensajes"
        for m in report.measurements
    )
    if report.unmeasured:
        lines.append(f"  -- sin datos: {', '.join(report.unmeasured)}")
    if report.rejections_by_rule:
        causes = ", ".join(f"{r}={c}" for r, c in sorted(report.rejections_by_rule.items()))
        lines.append(f"  -- rechazos: {causes}")
    return "\n".join(lines)


def quality_main(argv: list[str] | None = None) -> int:
    """Punto de entrada del informe de calidad.

    Returns:
        ``0`` si todo fue bien, ``1`` si alguna regla falló y se pidió
        ``--strict``.
    """
    args = build_quality_parser().parse_args(argv)

    lines = _read_lines(args.source)
    store = _build_store(args.invalid)
    evidence = (
        _match_evidence(lines, store) if args.stream == "match" else _odds_evidence(lines, store)
    )

    report = assess(args.scope or STREAM_NAMES[args.stream], evidence)
    _write(report.to_json() + "\n", args.report)
    print(_describe(report), file=sys.stderr)

    return 1 if args.strict and not report.passed else 0


###############################################################################
# gcperros-trace
###############################################################################


def build_trace_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos de la auditoría de indicadores."""
    parser = argparse.ArgumentParser(
        prog="gcperros-trace",
        description=(
            "Explica de dónde sale un indicador: qué eventos lo formaron, qué "
            "modelo lo calculó y bajo qué versión del contrato."
        ),
    )
    parser.add_argument(
        "--in",
        dest="source",
        type=Path,
        help="Fichero de entrada. Si se omite, lee de la entrada estándar.",
    )
    parser.add_argument(
        "--invalid",
        type=Path,
        help="Repositorio de eventos inválidos.",
    )
    parser.add_argument(
        "--indicator",
        help="Indicador a explicar. Si se omite, audita todos.",
    )
    parser.add_argument(
        "--scope",
        help="Equipo del indicador. Obligatorio junto a --indicator.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Dónde escribir el informe JSON. Por defecto, la salida estándar.",
    )
    return parser


def _ingest(lines: list[str], store: InvalidEventStore) -> MatchEngine:
    """Lleva el flujo de partido por la frontera y el motor."""
    gate = match_event_gate(store)
    engine = MatchEngine()
    try:
        for line in lines:
            event = gate.admit(line)
            if event is not None:
                engine.process(event)
        engine.flush()
    finally:
        gate.close()
    return engine


def trace_main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la auditoría de indicadores.

    Returns:
        ``0`` si se pudo explicar lo pedido.

    Raises:
        SystemExit: Si se pide un indicador sin decir de qué equipo, o uno que
            el motor no produce.
    """
    args = build_trace_parser().parse_args(argv)

    if args.indicator and not args.scope:
        raise SystemExit("--indicator necesita --scope: un indicador es de un equipo")

    engine = _ingest(_read_lines(args.source), _build_store(args.invalid))

    if args.indicator:
        try:
            payload = explain(engine.state, args.indicator, args.scope).to_json()
        except (AttributeError, KeyError) as error:
            raise SystemExit(f"no hay indicador {args.indicator!r} para {args.scope!r}") from error
        print(f"explicado {args.indicator} de {args.scope}", file=sys.stderr)
    else:
        trail = audit(engine.state)
        payload = trail.to_json()
        print(f"auditados {len(trail.explanations)} indicadores", file=sys.stderr)

    _write(payload + "\n", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
