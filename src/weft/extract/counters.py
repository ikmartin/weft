"""amsthm counter emulation: numbers for results when no `.aux` says what the paper printed.

Sectioning counters step and reset their descendants; a theorem counter shared with `[theorem]` follows the owning declaration's `[section]`-style reset; `\\newtheorem*` results have no number; `\\appendix` letters the section counter. A number read from an `.aux` resynchronises the emulation, so one label with a real number fixes the ones that follow it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from weft.tex.model import Taxon

LEVELS = {"part": 0, "chapter": 0, "section": 1, "subsection": 2, "subsubsection": 3, "paragraph": 4, "subparagraph": 5}


@dataclass
class Numbering:
    """The counters of one document, stepped in document order."""

    taxa: dict[str, Taxon]
    sec: list[int] = field(default_factory=lambda: [0, 0, 0, 0, 0, 0])
    counters: dict[str, int] = field(default_factory=dict)
    appendix: bool = False

    def _counter(self, taxon: Taxon) -> str:
        return taxon.counter or taxon.env

    def _within(self, taxon: Taxon) -> str | None:
        c = self._counter(taxon)
        owner = self.taxa.get(c)
        return owner.within if owner is not None and owner.within else taxon.within

    def heading(self, name: str, starred: bool = False) -> str | None:
        """Step a sectioning counter; returns the heading's number, or None for a starred heading or a part."""
        level = LEVELS.get(name)
        if level is None or starred or name == "part":
            return None
        self.sec[level] += 1
        for deeper in range(level + 1, len(self.sec)):
            self.sec[deeper] = 0
        for _env, t in self.taxa.items():
            c = self._counter(t)
            w = self._within(t)
            if w is not None and LEVELS.get(w, 99) >= level:
                self.counters[c] = 0
        return self.section_number(level)

    def mark_appendix(self) -> None:
        """`\\appendix`: sections letter from A, and everything below them restarts."""
        self.appendix = True
        self.sec[1] = 0
        for deeper in range(2, len(self.sec)):
            self.sec[deeper] = 0

    def section_number(self, level: int) -> str:
        parts: list[str] = []
        for lv in range(1, level + 1):
            n = self.sec[lv]
            if lv == 1 and self.appendix:
                parts.append(chr(ord("A") + max(n, 1) - 1))
            else:
                parts.append(str(n))
        return ".".join(parts)

    def theorem(self, taxon: Taxon) -> str | None:
        """Step the taxon's counter and return the result's number, or None for an unnumbered taxon."""
        if not taxon.numbered:
            return None
        c = self._counter(taxon)
        self.counters[c] = self.counters.get(c, 0) + 1
        w = self._within(taxon)
        prefix = self.section_number(LEVELS[w]) if w in LEVELS else ""
        return f"{prefix}.{self.counters[c]}" if prefix else str(self.counters[c])

    def resync(self, taxon: Taxon, number: str) -> None:
        """Set the counters from an authoritative number such as `4.1`, so the emulated numbers after it follow the paper."""
        pieces = number.split(".")
        last = pieces[-1]
        if last.isdigit():
            self.counters[self._counter(taxon)] = int(last)
        w = self._within(taxon)
        if w in LEVELS and len(pieces) > 1:
            for i, piece in enumerate(pieces[:-1]):
                lv = i + 1
                if piece.isdigit():
                    self.sec[lv] = int(piece)
                elif re.fullmatch(r"[A-Z]", piece) and lv == 1:
                    self.appendix = True
                    self.sec[1] = ord(piece) - ord("A") + 1
