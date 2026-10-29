"""Línea de comandos del catálogo y del glosario: ``gcperros-catalog`` (historia #24).

Responde a «¿de quién es esto?» y a «¿qué significa esto?» sin abrir el código:

```bash
gcperros-catalog                       # todos los activos con su responsable
gcperros-catalog --owner governance    # lo que le toca a un rol
gcperros-catalog --glossary            # el glosario de negocio
gcperros-catalog --access              # quién puede ver qué (historia #27)
gcperros-catalog --json                # lo mismo, para otra herramienta
```
"""

from __future__ import annotations

import argparse
import json
import sys

from gcperros.core.contracts import JsonValue
from gcperros.governance.access import MATRIX, Principal
from gcperros.governance.catalog import CATALOG, OWNERS, Asset, AssetKind, Role
from gcperros.governance.glossary import GLOSSARY, Term


def build_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos."""
    parser = argparse.ArgumentParser(
        prog="gcperros-catalog",
        description="Consulta el catálogo de datos con sus responsables, o el glosario.",
    )
    parser.add_argument("--glossary", action="store_true", help="Muestra el glosario.")
    parser.add_argument("--access", action="store_true", help="Muestra la matriz de acceso.")
    parser.add_argument("--owner", choices=[role.value for role in Role], help="Filtra por rol.")
    parser.add_argument(
        "--kind", choices=[kind.value for kind in AssetKind], help="Filtra por clase."
    )
    parser.add_argument("--json", action="store_true", help="Salida en JSON.")
    return parser


def _asset_dict(entry: Asset) -> dict[str, JsonValue]:
    owner = OWNERS[entry.owner]
    return {
        "name": entry.name,
        "kind": entry.kind.value,
        "owner": {"role": owner.role.value, "title": owner.title, "person": owner.person},
        "description": entry.description,
        "terms": list(entry.terms),
    }


def _term_dict(entry: Term) -> dict[str, JsonValue]:
    return {
        "key": entry.key,
        "name": entry.name,
        "definition": entry.definition,
        "unit": entry.unit,
        "implemented_in": entry.implemented_in,
    }


def _asset_line(entry: Asset) -> str:
    owner = OWNERS[entry.owner]
    return f"{entry.name:<36} {entry.kind.value:<10} {owner.person} ({owner.role.value})"


def _term_lines(entry: Term) -> str:
    return (
        f"{entry.name} [{entry.key}]\n  {entry.definition}\n"
        f"  unidad: {entry.unit}\n  en: {entry.implemented_in}\n"
    )


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada."""
    args = build_parser().parse_args(argv)

    if args.access:
        if args.json:
            rows = {
                name: {p.value: a.value for p, a in row.items()} for name, row in MATRIX.items()
            }
            output = json.dumps(rows, indent=2)
        else:
            header = f"{'activo':<36} " + " ".join(f"{p.value:<12}" for p in Principal)
            lines = [
                f"{n:<36} " + " ".join(f"{a.value:<12}" for a in r.values())
                for n, r in MATRIX.items()
            ]
            output = "\n".join(line.rstrip() for line in [header, *lines])
        sys.stdout.write(output + "\n")
        return 0

    if args.glossary:
        if args.json:
            output = json.dumps([_term_dict(t) for t in GLOSSARY], ensure_ascii=False, indent=2)
        else:
            output = "\n".join(_term_lines(t) for t in GLOSSARY)
        sys.stdout.write(output + "\n")
        return 0

    selected = [
        entry
        for entry in CATALOG
        if (args.owner is None or entry.owner == args.owner)
        and (args.kind is None or entry.kind == args.kind)
    ]
    if args.json:
        output = json.dumps([_asset_dict(e) for e in selected], ensure_ascii=False, indent=2)
    else:
        output = "\n".join(_asset_line(e) for e in selected)
    sys.stdout.write(output + "\n")
    print(f"activos={len(selected)} de {len(CATALOG)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
