"""Expanding a main file's inclusions into one text with a span map.

`\\input` and `\\include` are resolved as TeX does: the path as written, then with `.tex` appended; a braceless `\\input` name is accepted; a non-`.tex` file is an opaque inclusion whose text is never read. The expanded text holds every reached file's text exactly once, each child spliced in right after its inclusion command, so a section that starts in one file and continues in another is one unit and a result knows which file it was written in. Cycles and second inclusions are recorded and not expanded.

A name that resolves to nothing is reported as missing rather than probed for with `kpsewhich`: weft reads a paper it did not compile, where a name it cannot find is almost always a file of the TeX distribution, and a subprocess per unresolved name would cost more than the distinction is worth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from weft.tex.model import Location, Problem, SourceFile, Span
from weft.tex.tokenize import read_mandatory, tokenize

INCLUDE_CMDS = {"input", "include"}


@dataclass
class Segment:
    """One run of a file's text inside the expansion."""

    file: str
    file_start: int
    length: int
    exp_start: int

    @property
    def exp_end(self) -> int:
        return self.exp_start + self.length


@dataclass
class Inclusion:
    """One `\\input` or `\\include` site, and what became of it."""

    parent: str
    site_start: int
    site_end: int
    name: str
    kind: str
    child: str | None
    problem: str | None = None  # missing | cycle | double | opaque


@dataclass
class Expansion:
    """The main file and everything it includes, as one text, with the map back to the files."""

    master: str
    text: str = ""
    segments: list[Segment] = field(default_factory=list)
    inclusions: list[Inclusion] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    reached: dict[str, int] = field(default_factory=dict)

    def locate(self, exp_offset: int) -> tuple[str, int]:
        """(file, offset in that file) for an expanded offset."""
        lo, hi = 0, len(self.segments) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.segments[mid].exp_start <= exp_offset:
                lo = mid
            else:
                hi = mid - 1
        seg = self.segments[lo]
        return seg.file, seg.file_start + (exp_offset - seg.exp_start)

    def map_range(self, a: int, b: int) -> list[Span]:
        """File spans covering the expanded range [a, b), in order."""
        out: list[Span] = []
        for seg in self.segments:
            lo, hi = max(a, seg.exp_start), min(b, seg.exp_end)
            if lo < hi:
                out.append(Span(seg.file, seg.file_start + (lo - seg.exp_start), seg.file_start + (hi - seg.exp_start)))
        return out

    def exp_offset(self, file: str, offset: int) -> int | None:
        """The expanded offset of a file offset, or None when that file is not in the expansion."""
        for seg in self.segments:
            if seg.file == file and seg.file_start <= offset < seg.file_start + seg.length:
                return seg.exp_start + (offset - seg.file_start)
        return None


def resolve_inclusion(root: Path, name: str, known: frozenset[str] = frozenset()) -> str | None:
    """The paper-relative path an inclusion names, or None for an absolute path, an escape, or a name nothing in the paper answers to."""
    name = name.strip()
    if not name or name.startswith("/") or ".." in Path(name).parts:
        return None
    for cand in (name, name + ".tex"):
        rel = Path(cand).as_posix()
        if rel in known or (root / cand).is_file():
            return rel
    return None


def _read_include_arg(text: str, pos: int) -> tuple[str | None, int]:
    """The argument of an `\\input`-like command: a braced group, or a whitespace-delimited name (the primitive form)."""
    value, _, _, nxt = read_mandatory(text, pos)
    if value is None:
        return None, pos
    if nxt == pos + len(value) or text[pos:nxt].lstrip().startswith("{"):
        return value.strip(), nxt
    m = re.match(r"\s*([^\s{}\\]+)", text[pos:])
    if m:
        return m.group(1), pos + m.end()
    return value.strip(), nxt


def expand_master(master: SourceFile, root: Path, files: dict[str, SourceFile]) -> Expansion:
    """Splice every file the main file includes into one text.

    Parameters
    ----------
    master : SourceFile
        The paper's main file.
    root : Path
        The paper's directory.
    files : dict[str, SourceFile]
        Every file already read, by paper-relative path; an inclusion naming one that is not here is opaque.

    Returns
    -------
    Expansion
        The joined text, the segment map back to the files, and what each inclusion site did.
    """
    exp = Expansion(master=master.path)
    parts: list[str] = []
    cursor = [0]

    def emit(file: str, file_start: int, length: int) -> None:
        if length <= 0:
            return
        exp.segments.append(Segment(file, file_start, length, cursor[0]))
        cursor[0] += length

    def rec(src: SourceFile, stack: tuple[str, ...]) -> None:
        exp.reached[src.path] = exp.reached.get(src.path, 0) + 1
        text = src.clean
        pos = 0
        for t in tokenize(text):
            if t.kind != "cmd" or t.value not in INCLUDE_CMDS:
                continue
            name, arg_end = _read_include_arg(text, t.end)
            if name is None:
                continue
            emit(src.path, pos, arg_end - pos)
            parts.append(text[pos:arg_end])
            pos = arg_end
            inc = Inclusion(src.path, t.start, arg_end, name, t.value, None)
            exp.inclusions.append(inc)
            rel = resolve_inclusion(root, name, frozenset(files))
            loc = [Location(src.path, src.line_of(t.start))]
            if rel is None:
                inc.problem = "missing"
                exp.problems.append(Problem("info", "missing-include", f"\\{t.value}{{{name}}} names no file", loc))
                continue
            inc.child = rel
            if not rel.endswith(".tex") or rel not in files:
                inc.problem = "opaque"
                continue
            if rel in stack or rel == src.path:
                inc.problem = "cycle"
                chain = " -> ".join([*stack, src.path, rel])
                exp.problems.append(Problem("warning", "inclusion-cycle", f"inclusion cycle {chain}", loc))
                continue
            if rel in exp.reached:
                inc.problem = "double"
                exp.problems.append(Problem("warning", "double-inclusion", f"{rel} is included twice", loc))
                continue
            rec(files[rel], (*stack, src.path))
        emit(src.path, pos, len(text) - pos)
        parts.append(text[pos:])

    rec(master, ())
    exp.text = "".join(parts)
    return exp
