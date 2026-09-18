"""The checked-in CLI reference equals what the command tree generates."""

from __future__ import annotations

import runpy
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_the_reference_matches_the_command_tree() -> None:
    mod = runpy.run_path(str(REPO / "scripts" / "gen_cli_reference.py"), run_name="not_main")
    generated = mod["generate"]()
    assert (REPO / "docs" / "cli-reference.md").read_text(encoding="utf-8") == generated, (
        "run scripts/gen_cli_reference.py"
    )
    for command in ("weft crawl plan", "weft extract", "weft link", "weft mcp", "weft serve"):
        assert f"`{command}`" in generated
