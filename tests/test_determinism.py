"""Reproducibilidad bajo semilla fija: el núcleo de la HU-8.

Sin esta propiedad no hay forma honesta de comparar el resultado del streaming
contra la referencia batch, porque una diferencia podría venir de un fallo real
o simplemente de haber generado dos partidos distintos.
"""

from __future__ import annotations

from pathlib import Path

from gcperros.generators.cli import main
from gcperros.generators.match import MatchConfig, simulate_match


def _serialize(seed: int, config: MatchConfig | None = None) -> bytes:
    return b"".join(f"{e.to_json()}\n".encode() for e in simulate_match(seed, config))


def test_same_seed_produces_identical_bytes() -> None:
    assert _serialize(20260826) == _serialize(20260826)


def test_different_seeds_produce_different_matches() -> None:
    assert _serialize(1) != _serialize(2)


def test_determinism_holds_across_many_seeds() -> None:
    for seed in range(25):
        assert _serialize(seed) == _serialize(seed), f"semilla {seed} no es reproducible"


def test_event_ids_are_stable_and_unique() -> None:
    first = simulate_match(7)
    second = simulate_match(7)

    ids = [event.event_id for event in first]
    assert ids == [event.event_id for event in second]
    assert len(ids) == len(set(ids)), "los event_id deben ser únicos dentro del partido"


def test_match_id_participates_in_the_identifier() -> None:
    """Dos partidos distintos con la misma semilla no comparten `event_id`.

    Es lo que impide que la deduplicación del motor (HU-11) descarte por error
    eventos de un partido al procesar otro en paralelo.
    """
    left = simulate_match(3, MatchConfig(match_id="match-A"))
    right = simulate_match(3, MatchConfig(match_id="match-B"))

    assert {e.event_id for e in left}.isdisjoint({e.event_id for e in right})


def test_no_ambient_state_leaks_between_runs() -> None:
    """Intercalar otra simulación no altera el resultado.

    Si el módulo usara el generador global de `random`, esta prueba fallaría.
    """
    baseline = _serialize(11)
    simulate_match(999)
    assert _serialize(11) == baseline


def test_cli_output_is_byte_identical(tmp_path: Path) -> None:
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"

    for target in (first, second):
        assert main(["--seed", "42", "--out", str(target)]) == 0

    assert first.read_bytes() == second.read_bytes()
