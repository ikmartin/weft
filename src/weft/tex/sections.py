"""Sectioning units over the expanded main file.

A unit runs from its heading to the next heading of equal or higher level, or to `\\end{document}`. The hierarchy is computed on the expanded text, so a section beginning in one file and continuing in another is one unit. A heading's label is the first `\\label` on its line, or on the next non-blank line unless that line opens an environment or another heading -- which is what lets a compiled number be matched to a section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from weft.tex.expand import Expansion
from weft.tex.model import SourceFile
from weft.tex.tokenize import read_args

LEVELS = {
    "part": -1,
    "chapter": 0,
    "section": 1,
    "subsection": 2,
    "subsubsection": 3,
    "paragraph": 4,
    "subparagraph": 5,
}
LEVEL_NAMES = {v: k for k, v in LEVELS.items()}
_SECT = re.compile(r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)(\*?)\s*(?=[\[{])")
_LABEL = re.compile(r"\\label\s*\{([^}]*)\}")
_OPENER = re.compile(r"^\s*\\(begin\s*\{|part|chapter|section|subsection|subsubsection|paragraph|subparagraph)")


@dataclass
class SectionUnit:
    """One heading and the region it owns."""

    name: str
    starred: bool
    level: int
    exp_start: int
    exp_end: int
    title: str
    file: str
    offset: int  # heading offset in its file
    heading_end: int  # offset in the file just past the title's closing brace
    labels: list[str] = field(default_factory=list)
    parent: SectionUnit | None = field(default=None, repr=False)
    children: list[SectionUnit] = field(default_factory=list)


def body_range(exp: Expansion) -> tuple[int, int]:
    """The expanded offsets of `\\begin{document}` and `\\end{document}`, or the whole text when a document has neither."""
    text = exp.text
    m = re.search(r"\\begin\s*\{document\}", text)
    start = m.end() if m else 0
    e = re.search(r"\\end\s*\{document\}", text)
    end = e.start() if e else len(text)
    return start, end


def find_sections(exp: Expansion, files: dict[str, SourceFile]) -> list[SectionUnit]:
    """Every sectioning unit of the document body, in order, with parents and labels filled in.

    Parameters
    ----------
    exp : Expansion
        The expanded main file.
    files : dict[str, SourceFile]
        The files it reached, by paper-relative path.

    Returns
    -------
    list of SectionUnit
        In document order; a starred heading is included and marked, since it takes no number.
    """
    text = exp.text
    start, end = body_range(exp)
    units: list[SectionUnit] = []
    for m in _SECT.finditer(text, start, end):
        name, starred = m.group(1), bool(m.group(2))
        (_short, title), _spans, after = read_args(text, m.end(), "om")
        if title is None:
            continue
        file, offset = exp.locate(m.start())
        units.append(
            SectionUnit(
                name=name,
                starred=starred,
                level=LEVELS[name],
                exp_start=m.start(),
                exp_end=end,
                title=re.sub(r"\s+", " ", title.strip()),
                file=file,
                offset=offset,
                heading_end=offset + (after - m.start()),
            )
        )
    for i, u in enumerate(units):
        for later in units[i + 1 :]:
            if later.level <= u.level:
                u.exp_end = later.exp_start
                break
    stack: list[SectionUnit] = []
    for u in units:
        while stack and stack[-1].level >= u.level:
            stack.pop()
        if stack:
            u.parent = stack[-1]
            stack[-1].children.append(u)
        stack.append(u)
    for u in units:
        src = files.get(u.file)
        if src is not None:
            u.labels = heading_labels(src.clean, u.heading_end)
    return units


def heading_labels(clean: str, heading_end: int) -> list[str]:
    """Labels on the heading's line, else on the next non-blank line unless it opens an environment or another heading."""
    line_end = clean.find("\n", heading_end)
    line_end = len(clean) if line_end < 0 else line_end
    same_line = _LABEL.findall(clean, heading_end, line_end)
    if same_line:
        return [re.sub(r"\s+", " ", x).strip() for x in same_line]
    pos = line_end + 1
    while pos < len(clean):
        nl = clean.find("\n", pos)
        nl = len(clean) if nl < 0 else nl
        line = clean[pos:nl]
        if line.strip():
            if _OPENER.match(line):
                return []
            return [re.sub(r"\s+", " ", x).strip() for x in _LABEL.findall(line)]
        pos = nl + 1
    return []
