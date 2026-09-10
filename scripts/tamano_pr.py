"""Límite de tamaño de un pull request.

Un pull request grande no se revisa: se hojea. Y un cambio hojeado entra con la
misma ceremonia que uno revisado, lo que convierte la revisión en un trámite.
Este script pone un tope y lo hace comprobable **antes** de subir nada, para que
el aviso llegue cuando reorganizar los commits todavía es barato.

Cuenta **todo**: código, pruebas y documentación. Es la opción estricta, y es
deliberada — excluir las pruebas del recuento facilitaría cumplir el límite
escribiendo menos de lo que hay que revisar igual.

Se ejecuta en dos sitios, desde este único fichero para que no puedan divergir:

- Como gancho ``pre-push``, en la máquina de quien empuja.
- Como trabajo de integración continua, para quien no tenga ganchos.

La válvula de escape es deliberada y visible: la etiqueta ``pr-grande`` en el
pull request, o ``GCPERROS_PR_GRANDE=1`` en local. Sin una salida declarada, la
primera entrega legítimamente grande acabaría con la regla desactivada entera;
con ella, la excepción queda registrada donde el equipo la ve.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

#: Deltas máximos: líneas añadidas más borradas, sobre la base de comparación.
DEFAULT_LIMIT = 250

#: Rama contra la que se mide, que es la que recibirá el pull request.
DEFAULT_BASE = "origin/main"

#: Variable que salta el límite en local. Su equivalente en el pull request es
#: la etiqueta `pr-grande`.
ESCAPE_ENV = "GCPERROS_PR_GRANDE"

#: Cuántos ficheros se listan al informar. Los suficientes para ver dónde está
#: el peso, sin convertir el aviso en un volcado.
TOP_FILES = 8


#: Ruta absoluta de git. Se resuelve una vez, en lugar de invocar "git" a secas:
#: una ruta parcial depende del PATH del momento, que no es lo mismo en el
#: gancho de un editor que en una terminal.
GIT = shutil.which("git") or "git"


def _run(*args: str) -> str:
    """Ejecuta un comando de git y devuelve su salida."""
    completed = subprocess.run([GIT, *args], capture_output=True, text=True, check=True)
    return completed.stdout


def measure(base: str, head: str = "HEAD") -> tuple[int, list[tuple[int, str]]]:
    """Mide el tamaño del cambio contra la base.

    Se compara con tres puntos (``base...head``), es decir contra el punto en
    que las dos ramas divergieron. Con dos puntos, un cambio ajeno recién
    fusionado en la base contaría como propio.

    Args:
        base: Referencia contra la que se mide.
        head: Punta que se mide.

    Returns:
        El total de deltas y la lista de ``(deltas, fichero)``, de mayor a
        menor.
    """
    total = 0
    files: list[tuple[int, str]] = []

    for line in _run("diff", "--numstat", f"{base}...{head}").splitlines():
        added, removed, name = line.split("\t", 2)
        if added == "-" or removed == "-":
            # Fichero binario: git no cuenta líneas y contarlo como cero es más
            # honesto que inventar una cifra.
            continue
        deltas = int(added) + int(removed)
        total += deltas
        files.append((deltas, name))

    files.sort(reverse=True)
    return total, files


def report(total: int, files: list[tuple[int, str]], limit: int, base: str) -> None:
    """Escribe el resultado en la salida de error."""
    veredicto = "supera el limite" if total > limit else "dentro del limite"
    print(
        f"tamaño del cambio contra {base}: {total} deltas ({veredicto} de {limit})", file=sys.stderr
    )

    if total <= limit:
        return

    print("\nlo que mas pesa:", file=sys.stderr)
    for deltas, name in files[:TOP_FILES]:
        print(f"  {deltas:>6}  {name}", file=sys.stderr)
    if len(files) > TOP_FILES:
        print(f"  {'...':>6}  y {len(files) - TOP_FILES} ficheros mas", file=sys.stderr)

    print(
        "\nUn pull request de este tamaño no se revisa, se hojea. Divídelo si puedes.\n"
        f"Si de verdad tiene que ir junto: etiqueta el pull request como `pr-grande`,\n"
        f"o exporta {ESCAPE_ENV}=1 para saltarlo en local.",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada.

    Returns:
        ``0`` si el cambio cabe en el límite o hay una excepción declarada,
        ``1`` si lo supera.
    """
    parser = argparse.ArgumentParser(
        prog="tamano_pr.py",
        description="Comprueba que el cambio no supere el limite de deltas del proyecto.",
    )
    parser.add_argument("--base", default=DEFAULT_BASE, help="Referencia contra la que medir.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Deltas maximos.")
    parser.add_argument(
        "--allow-large",
        action="store_true",
        help="Salta el limite. Lo usa la integracion continua cuando el pull "
        "request lleva la etiqueta `pr-grande`.",
    )
    args = parser.parse_args(argv)

    try:
        total, files = measure(args.base)
    except subprocess.CalledProcessError:
        # Sin la base no se puede medir. No es motivo para impedir un push: el
        # trabajo de integracion continua volvera a comprobarlo con la base
        # disponible.
        print(
            f"no se pudo comparar contra {args.base}; prueba `git fetch origin`. "
            "La integracion continua lo comprobara igualmente.",
            file=sys.stderr,
        )
        return 0

    report(total, files, args.limit, args.base)

    if total <= args.limit:
        return 0

    if args.allow_large or os.environ.get(ESCAPE_ENV):
        print("\nexcepcion declarada: se deja pasar.", file=sys.stderr)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
