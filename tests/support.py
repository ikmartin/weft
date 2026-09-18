"""Helpers the crawl tests share: the recorded service answers, a budget that does not really wait, and a corpus on disk.

No test touches the network. Service clients take a transport and recorded answers stand in; the one test that does ask the real services is marked `network` and skipped unless WEFT_NETWORK is set.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from weft.config import Settings
from weft.crawl.net import HostBudget

RESPONSES = Path(__file__).parent / "responses"
CRAWL = json.loads((RESPONSES / "crawl_responses.json").read_text(encoding="utf-8"))["responses"]
RESOLVE = json.loads((RESPONSES / "resolve_responses.json").read_text(encoding="utf-8"))


@dataclass
class Tick:
    """A clock that only moves when something waits, so a test can read the spacing off the timestamps."""

    now: float = 0.0
    waits: list[float] = field(default_factory=list)

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.waits.append(seconds)


def budget(spacing: dict[str, float] | None = None) -> HostBudget:
    """A host budget on a fake clock: the spacing is real, the waiting is not. Its clock is `budget.clock`."""
    tick = Tick()
    return HostBudget(spacing, clock=tick, sleep=tick.sleep)


def corpus(root: Path, **settings: object) -> Settings:
    """A corpus's directories under `root`, and the settings that describe it."""
    for d in ("works", "cache", "crawl"):
        (root / d).mkdir(parents=True, exist_ok=True)
    return Settings(root=root, **settings)  # type: ignore[arg-type]


def seed_file(root: Path, text: str, name: str = "seeds.bib") -> str:
    """Write a seed bibliography into a corpus; returns its name as `[seeds] bib` records it."""
    (root / name).write_text(text, encoding="utf-8")
    return name
