"""A corpus's settings, read from `weft.toml` at its root.

Filtering is configured, never inferred: `subjects` and `categories` are the author's, and a crawl deeper than the seeds refuses to guess them (see `weft survey`). The cap counts downloads on disk.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG = "weft.toml"

TEMPLATE = """# A weft corpus. Filtering is yours to state; weft surveys and infers nothing.

[seeds]
works = []                  # global identifiers, e.g. "arxiv:1709.09864"
bib = []                    # BibTeX files, relative to this file, whose entries are seeds

[crawl]
depth = 2                   # the seeds are depth 1; a work at `depth` is included and not expanded
subjects = []               # MSC families, e.g. ["14N", "14D"]; required when depth > 1
categories = []             # arXiv categories, e.g. ["math.AG"]; used where a work has no MSC code
cap = 200                   # downloads on disk, counted across every command

[sources]
contact = ""                # an address sent to Crossref's polite pool; nothing identifying is sent when empty

[store]
dsn = "sqlite:index.sqlite" # the index; a Postgres dsn when the corpus outgrows a file

[licence]
share = false               # a corpus is private by default: statements and proofs are verbatim
"""


class ConfigError(Exception):
    """A corpus that cannot be read, or settings that contradict each other."""


@dataclass(frozen=True)
class Settings:
    root: Path
    works: list[str] = field(default_factory=list)
    bib: list[str] = field(default_factory=list)
    depth: int = 2
    subjects: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    cap: int = 200
    contact: str = ""
    dsn: str = "sqlite:index.sqlite"
    share: bool = False

    @property
    def openalex_key(self) -> str | None:
        """Read from the environment only, so it is never written into a corpus or a cache file's name."""
        return os.environ.get("WEFT_OPENALEX_KEY") or None

    @property
    def works_dir(self) -> Path:
        return self.root / "works"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def crawl_dir(self) -> Path:
        return self.root / "crawl"

    @property
    def index_path(self) -> Path:
        """The index file for a sqlite dsn; a Postgres dsn has none."""
        rest = self.dsn.split("sqlite:", 1)[1] if self.dsn.startswith("sqlite:") else "index.sqlite"
        p = Path(rest)
        return p if p.is_absolute() else self.root / p

    def seed_bib_paths(self) -> list[Path]:
        return [self.root / b for b in self.bib]

    def fingerprint_material(self) -> list[str]:
        """What a plan's fingerprint is taken over, beside the seed texts: the settings that decide the walk."""
        return [
            f"depth={self.depth}",
            "subjects=" + ",".join(sorted(self.subjects)),
            "categories=" + ",".join(sorted(self.categories)),
            "works=" + ",".join(sorted(self.works)),
            "bib=" + ",".join(sorted(self.bib)),
        ]


def find_root(start: Path) -> Path | None:
    """The corpus root at or above `start`: the nearest directory holding `weft.toml`."""
    here = start if start.is_dir() else start.parent
    for d in [here, *here.parents]:
        if (d / CONFIG).is_file():
            return d
    return None


def load(start: Path | None = None) -> Settings:
    """The settings of the corpus at or above `start` (default: the current directory)."""
    root = find_root(start or Path.cwd())
    if root is None:
        raise ConfigError(f"no {CONFIG} here or above; run `weft init` to make a corpus")
    try:
        raw = tomllib.loads((root / CONFIG).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{root / CONFIG}: {exc}") from exc
    seeds = raw.get("seeds", {})
    crawl = raw.get("crawl", {})
    sources = raw.get("sources", {})
    store = raw.get("store", {})
    licence = raw.get("licence", {})
    settings = Settings(
        root=root,
        works=[str(w) for w in seeds.get("works", [])],
        bib=[str(b) for b in seeds.get("bib", [])],
        depth=int(crawl.get("depth", 2)),
        subjects=[str(s) for s in crawl.get("subjects", [])],
        categories=[str(c) for c in crawl.get("categories", [])],
        cap=int(crawl.get("cap", 200)),
        contact=str(sources.get("contact", "")),
        dsn=str(store.get("dsn", "sqlite:index.sqlite")),
        share=bool(licence.get("share", False)),
    )
    if settings.depth < 1:
        raise ConfigError("[crawl] depth must be at least 1")
    if not settings.works and not settings.bib:
        raise ConfigError("[seeds] name at least one work or one BibTeX file")
    for b in settings.seed_bib_paths():
        if not b.is_file():
            raise ConfigError(f"[seeds] bib names {b}, which is not a file")
    return settings


def write_template(root: Path) -> Path:
    """Write a corpus skeleton into `root`; refuses to overwrite an existing weft.toml."""
    path = root / CONFIG
    if path.exists():
        raise ConfigError(f"{path} exists")
    root.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    for d in ("works", "cache", "crawl"):
        (root / d).mkdir(exist_ok=True)
    return path
