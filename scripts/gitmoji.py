"""Pone el gitmoji que corresponde al tipo del commit, y comprueba que esté (HU-N/A).

El proyecto usa Conventional Commits, así que el tipo del cambio ya viaja en el
asunto: ``feat``, ``fix``, ``docs``… Y el catálogo de gitmoji asigna un icono a
cada uno de esos tipos. Teniendo las dos cosas, **pedirle a nadie que escriba el
emoji a mano es pedirle que repita a mano algo que ya dijo**: el tipo determina
el icono sin ambigüedad.

Este script hace las dos mitades del trabajo, y vive en un solo fichero a
propósito, porque la tabla de equivalencias tiene que ser la misma para las dos:

- Como gancho ``prepare-commit-msg``, **añade** el emoji antes de que aparezca
  el editor. Nadie lo teclea.
- Con ``--check``, **verifica** que los asuntos que recibe por la entrada
  estándar lo lleven. Es lo que corre en integración continua, para quien no
  tenga los ganchos instalados.

Si el asunto no sigue Conventional Commits, no se toca: rechazarlo es trabajo de
``commitizen``, que además explica mejor el porqué.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

#: Icono de cada tipo, según el catálogo de gitmoji. Son los mismos tipos que
#: admite `CONTRIBUTING.md`, más los dos que `commitizen` genera solo.
GITMOJI: dict[str, str] = {
    "feat": "✨",
    "fix": "🐛",
    "docs": "📝",
    "style": "🎨",
    "refactor": "♻️",
    "perf": "⚡️",
    "test": "✅",
    "build": "📦️",
    "ci": "👷",
    "chore": "🔧",
    "revert": "⏪️",
    "bump": "🔖",
}

#: Un asunto de Conventional Commits, con el emoji opcional por delante. El
#: emoji se declara opcional para que los commits anteriores a esta convención
#: sigan validando: reescribir historia publicada por un icono sería peor que no
#: tener el icono.
SUBJECT = re.compile(
    r"^(?P<emoji>[\U0001F300-\U0001FAFF☀-➿]️?\s)?"
    r"(?P<type>[a-z]+)"
    r"(?P<scope>\([^()]+\))?"
    r"(?P<breaking>!)?"
    r": "
)


def emoji_for(subject: str) -> str | None:
    """Devuelve el icono que le toca a un asunto, o ``None`` si no le toca ninguno.

    Args:
        subject: Primera línea del mensaje de commit.

    Returns:
        El icono, o ``None`` si el asunto ya lo trae o no sigue la convención.
    """
    match = SUBJECT.match(subject)
    if match is None or match.group("emoji"):
        return None
    return GITMOJI.get(match.group("type"))


def decorate(subject: str) -> str:
    """Antepone el icono al asunto si le corresponde y aún no lo tiene."""
    icon = emoji_for(subject)
    return f"{icon} {subject}" if icon else subject


def _first_real_line(lines: list[str]) -> int | None:
    """Posición de la primera línea con contenido que no sea un comentario."""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return index
    return None


def prepare(path: Path) -> int:
    """Reescribe el fichero del mensaje añadiendo el icono que corresponda.

    Args:
        path: Fichero que git pasa al gancho ``prepare-commit-msg``.

    Returns:
        Siempre ``0``: este gancho decora, no juzga. Un asunto malformado lo
        rechaza ``commitizen`` después, con un mensaje mejor que el nuestro.
    """
    # `newline=""` para no convertir los saltos: el proyecto promete ficheros
    # idénticos byte a byte en cualquier sistema operativo.
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()

    index = _first_real_line(lines)
    if index is None:
        return 0

    decorated = decorate(lines[index])
    if decorated == lines[index]:
        return 0

    lines[index] = decorated
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("\n".join(lines) + "\n")
    return 0


def check(subjects: list[str]) -> int:
    """Comprueba que cada asunto lleve el icono de su tipo.

    Args:
        subjects: Asuntos de commit, uno por elemento.

    Returns:
        ``0`` si todos cumplen, ``1`` si alguno no.
    """
    missing = [(subject, icon) for subject in subjects if (icon := emoji_for(subject))]

    for subject, icon in missing:
        print(f"falta {icon}  ->  {subject}", file=sys.stderr)

    if missing:
        print(
            f"\n{len(missing)} asunto(s) sin su gitmoji. Instala los ganchos con "
            "`pre-commit install --install-hooks` y se pondrán solos.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada.

    Sin argumentos actúa como gancho sobre el fichero indicado; con ``--check``
    lee asuntos de la entrada estándar y los verifica.
    """
    args = list(sys.argv[1:] if argv is None else argv)

    if "--check" in args:
        return check([line for line in sys.stdin.read().splitlines() if line.strip()])

    if not args:
        print("uso: gitmoji.py <fichero-del-mensaje> | gitmoji.py --check", file=sys.stderr)
        return 2

    return prepare(Path(args[0]))


if __name__ == "__main__":
    raise SystemExit(main())
