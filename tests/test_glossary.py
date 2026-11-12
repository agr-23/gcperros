"""El glosario de negocio (historia #24).

Lo que se vigila no es la redacción, sino que el glosario no pueda desfasarse:
cada término apunta a un módulo que existe, y las cifras de las definiciones
salen de las constantes que usa el código.
"""

from __future__ import annotations

import importlib

import pytest

from gcperros.core import court, expected_points, xg
from gcperros.engine.basketball_market import BASKETBALL_THRESHOLD
from gcperros.engine.basketball_state import BASKETBALL_ALLOWED_LATENESS_S
from gcperros.engine.signals import DEFAULT_THRESHOLD
from gcperros.engine.sport_harness import SPORTS as ENGINE_SPORTS
from gcperros.engine.watermark import DEFAULT_ALLOWED_LATENESS_S
from gcperros.governance.glossary import GLOSSARY, SPORTS, Term, term

#: Los cinco términos que la historia nombra uno por uno.
REQUIRED = (
    "possession",
    "xg",
    "implied_probability",
    "operator_margin",
    "discrepancy_signal",
    # Los del baloncesto que nombra #97.
    "basketball_possession",
    "expected_points",
    "pace",
    "moneyline",
    "total_points",
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
    assert f"{BASKETBALL_THRESHOLD:g}" in term("discrepancy_signal").definition
    assert f"{BASKETBALL_ALLOWED_LATENESS_S:g} s" in term("watermark").definition
    assert expected_points.MODEL_VERSION in term("expected_points").definition
    assert f"{court.SHOT_CLOCK_S} s" in term("basketball_possession").definition


def test_the_glossary_knows_every_sport_the_engine_runs() -> None:
    """Un tercer deporte en el motor sin vocabulario rompe la construcción."""
    assert set(SPORTS) == set(ENGINE_SPORTS)
    for sport in SPORTS:
        assert any(entry.sports == (sport,) for entry in GLOSSARY)
    assert all(set(entry.sports) <= set(SPORTS) for entry in GLOSSARY)


def test_what_does_not_depend_on_the_sport_is_defined_once_for_all() -> None:
    for key in ("lineage", "watermark"):
        assert term(key).sports == SPORTS
    # El mercado es de los deportes con cuotas, no de todos.
    for key in ("operator_margin", "implied_probability", "discrepancy_signal"):
        assert "american_football" not in term(key).sports


def test_implied_probability_warns_against_the_shortcut() -> None:
    """El error que la HU-19 tuvo que evitar, dicho en la propia definición."""
    assert "No es 1 / cuota" in term("implied_probability").definition


def test_an_undefined_term_is_refused() -> None:
    with pytest.raises(KeyError, match="corners"):
        term("corners")
