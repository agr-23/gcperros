"""El glosario de negocio (historia #24).

Lo que se vigila no es la redacción, sino que el glosario no pueda desfasarse:
cada término apunta a un módulo que existe, y las cifras de las definiciones
salen de las constantes que usa el código.
"""

from __future__ import annotations

import importlib

import pytest

from gcperros.core import xg
from gcperros.engine.signals import DEFAULT_THRESHOLD
from gcperros.engine.watermark import DEFAULT_ALLOWED_LATENESS_S
from gcperros.governance.glossary import GLOSSARY, Term, term

#: Los cinco términos que la historia nombra uno por uno.
REQUIRED = (
    "possession",
    "xg",
    "implied_probability",
    "operator_margin",
    "discrepancy_signal",
)


@pytest.mark.parametrize("key", REQUIRED)
def test_every_term_the_story_names_is_defined(key: str) -> None:
    entry = term(key)

    assert entry.definition
    assert entry.unit


def test_each_term_is_defined_once() -> None:
    keys = [entry.key for entry in GLOSSARY]
    names = [entry.name for entry in GLOSSARY]

    assert len(keys) == len(set(keys))
    assert len(names) == len(set(names))


@pytest.mark.parametrize("entry", GLOSSARY, ids=lambda entry: entry.key)
def test_every_term_points_at_a_module_that_exists(entry: Term) -> None:
    assert importlib.import_module(entry.implemented_in).__name__ == entry.implemented_in


def test_the_figures_come_from_the_code_not_from_a_copy() -> None:
    """Si alguien cambia el umbral o el margen, la definición cambia con él."""
    assert f"{DEFAULT_THRESHOLD:g}" in term("discrepancy_signal").definition
    assert f"{DEFAULT_ALLOWED_LATENESS_S:g} s" in term("watermark").definition
    assert xg.MODEL_VERSION in term("xg").definition


def test_implied_probability_warns_against_the_shortcut() -> None:
    """El error que la HU-19 tuvo que evitar, dicho en la propia definición."""
    assert "No es 1 / cuota" in term("implied_probability").definition


def test_an_undefined_term_is_refused() -> None:
    with pytest.raises(KeyError, match="corners"):
        term("corners")
