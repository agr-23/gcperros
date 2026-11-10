"""gcperros-generate-odds --sport basketball (#90)."""

from __future__ import annotations

from pathlib import Path

from gcperros.generators.cli import odds_main


def test_the_cli_generates_basketball_odds(tmp_path: Path) -> None:
    out = tmp_path / "odds.jsonl"

    assert odds_main(["--sport", "basketball", "--seed", "7", "--out", str(out)]) == 0
    assert b'"market":"moneyline"' in out.read_bytes()
    assert b'"line":161.5' in out.read_bytes()
