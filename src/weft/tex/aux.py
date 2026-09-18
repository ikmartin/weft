"""Theorem, section and equation numbers read from a compiled paper's `.aux`.

Both the plain form `\\newlabel{ID}{{NUMBER}{PAGE}}` and hyperref's `\\newlabel{ID}{{NUMBER}{PAGE}{TITLE}{ANCHOR}{}}` are read; cleveref's `@cref` entries are skipped. A number read here is the paper's own, which is why extraction prefers it to anything it can count for itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from weft.tex.tokenize import match_group

_NEWLABEL = re.compile(r"\\newlabel\{")


@dataclass(frozen=True)
class AuxNumber:
    """What a compile recorded for one label: the number it printed and the page it fell on."""

    number: str
    page: int | None


def parse_aux(text: str) -> dict[str, AuxNumber]:
    """Every `\\newlabel` of an `.aux` file's text, by label.

    Parameters
    ----------
    text : str
        The contents of the `.aux` file.

    Returns
    -------
    dict[str, AuxNumber]
        Label to number and page; labels whose payload cannot be read are skipped rather than guessed at.
    """
    out: dict[str, AuxNumber] = {}
    for m in _NEWLABEL.finditer(text):
        open_pos = m.end() - 1
        close = match_group(text, open_pos)
        if close < 0:
            continue
        label = text[open_pos + 1 : close - 1]
        if label.endswith("@cref"):
            continue
        rest = close
        if rest >= len(text) or text[rest] != "{":
            continue
        end = match_group(text, rest)
        if end < 0:
            continue
        payload = text[rest + 1 : end - 1]
        parts: list[str] = []
        pos = 0
        while pos < len(payload) and payload[pos] == "{":
            q = match_group(payload, pos)
            if q < 0:
                break
            parts.append(payload[pos + 1 : q - 1])
            pos = q
        if not parts:
            continue
        number = re.sub(r"\\relax\s*", "", parts[0]).strip()
        page: int | None = None
        if len(parts) > 1:
            pm = re.match(r"\s*(\d+)", parts[1])
            page = int(pm.group(1)) if pm else None
        out[re.sub(r"\s+", " ", label).strip()] = AuxNumber(number, page)
    return out


def aux_beside(paper_dir: Path, main_rel: str) -> Path | None:
    """The `.aux` already sitting with the source, if there is exactly one candidate.

    Parameters
    ----------
    paper_dir : Path
        The unpacked source directory.
    main_rel : str
        The main file, relative to it.

    Returns
    -------
    Path or None
        The `.aux` named after the main file, else the only `.aux` in the directory, else None. Several unrelated ones are no answer at all, so numbering falls back to emulation rather than reading a number off another document.
    """
    named = paper_dir / Path(main_rel).with_suffix(".aux")
    if named.is_file():
        return named
    found = sorted(p for p in paper_dir.glob("*.aux") if p.is_file())
    return found[0] if len(found) == 1 else None


def read_numbers(paper_dir: Path, main_rel: str) -> dict[str, AuxNumber]:
    """The numbers of the `.aux` beside the source, or an empty mapping when there is none."""
    p = aux_beside(paper_dir, main_rel)
    if p is None:
        return {}
    return parse_aux(p.read_text(encoding="utf-8", errors="replace"))
