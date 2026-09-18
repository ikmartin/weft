"""Dataclasses the LaTeX layer shares.

Offsets are character offsets into a file's decoded text; comments are blanked, never removed, so an offset in `clean` is the same offset in `text`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, order=True)
class Span:
    """Half-open [start, end) character range in one source-relative file."""

    file: str
    start: int
    end: int

    def __len__(self) -> int:
        return self.end - self.start


@dataclass
class SourceFile:
    """One file of a paper: `text` as decoded, `clean` with every comment replaced by spaces of equal length."""

    path: str
    abspath: Path
    text: str
    clean: str
    encoding: str
    line_starts: list[int] = field(default_factory=list)

    def line_of(self, offset: int) -> int:
        """1-based line containing `offset`."""
        lo, hi = 0, len(self.line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.line_starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    def col_of(self, offset: int) -> int:
        return offset - self.line_starts[self.line_of(offset) - 1] + 1

    def slice(self, span: Span) -> str:
        return self.text[span.start : span.end]


@dataclass(frozen=True)
class Location:
    file: str
    line: int


@dataclass
class Problem:
    """Something the reader could not do with a paper's source: a missing inclusion, an inclusion cycle, a style it had to guess at.

    Nobody's build depends on these -- weft reads someone else's paper and has no author to report to -- so they ride along on the extraction report rather than stopping it.
    """

    severity: str  # error | warning | info
    code: str
    message: str
    locations: list[Location] = field(default_factory=list)


@dataclass(frozen=True)
class Macro:
    """A macro definition from the preamble closure; `args` counts parameters, `default` is the optional first argument's default."""

    name: str
    args: int
    body: str
    default: str | None = None
    kind: str = "newcommand"


@dataclass(frozen=True)
class Taxon:
    """A theorem-like environment declared by \\newtheorem or \\declaretheorem: `env` is the paper's name for it, `name` the display name."""

    env: str
    name: str
    style: str
    numbered: bool
    file: str
    offset: int
    counter: str | None = None
    within: str | None = None


@dataclass(frozen=True)
class Directive:
    """One `% !LOOM` or `% !TEX` line: its key, its value, and where it was read."""

    key: str
    value: str
    file: str
    offset: int
    line: int
    form: str  # bare | kv | begin | end | tex | unknown


@dataclass
class Env:
    """One environment occurrence in a file's environment tree."""

    name: str
    start: int
    end: int
    body_start: int
    body_end: int
    optarg: str | None
    optarg_span: tuple[int, int] | None
    children: list[Env] = field(default_factory=list)
    parent: Env | None = field(default=None, repr=False)
    theorem_like: bool = False
    is_proof: bool = False

    def own_ranges(self) -> list[tuple[int, int]]:
        """[start, end) pieces of this environment's own text: its region minus its children's regions."""
        pieces: list[tuple[int, int]] = []
        pos = self.start
        for child in self.children:
            if child.start > pos:
                pieces.append((pos, child.start))
            pos = child.end
        if self.end > pos:
            pieces.append((pos, self.end))
        return pieces
