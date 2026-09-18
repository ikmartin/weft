"""`% !LOOM` and `% !TEX` directive lines.

weft writes them, in a digest's provenance header, and reads them: back out of a digest it wrote, and out of a paper's own source, where `% !TEX root` and `% !TEX program` are the two an author is likely to have left behind. A directive is a declaration, never an action.
"""

from __future__ import annotations

import re

from weft.tex.model import Directive, SourceFile

# The digest contract's header keys (docs/specs/digest.md §2). An unknown key is kept and ignored, per 2.10, so this set decides nothing but what a reader recognises.
KNOWN_KEYS = {
    "digest",
    "prefix",
    "extracted-from",
    "published-as",
    "method",
    "proofs",
    "created",
    "requires",
    "numbering",
    "tool",
}
LIST_KEYS = {"requires"}
BARE_KEYS = {"ignore"}
REGION_KEYS = {"macros"}
HEAD_LINES = 20

_LINE = re.compile(r"^[ \t]*%[ \t]*!(LOOM|TEX)[ \t]+(.*?)[ \t]*$", re.M)


def parse_directives(src: SourceFile) -> list[Directive]:
    """Every directive line in a file, in order.

    Parameters
    ----------
    src : SourceFile
        The file to read; the raw text is used, since a directive is itself a comment.

    Returns
    -------
    list of Directive
        With `form` one of 'kv' (`key: value`), 'begin'/'end' (a region such as the macro block), 'bare', 'tex' or 'unknown'.
    """
    out: list[Directive] = []
    for m in _LINE.finditer(src.text):
        family, rest = m.group(1), m.group(2)
        line = src.line_of(m.start())
        if family == "TEX":
            tm = re.match(r"(root|program)\s*=\s*(.+)$", rest)
            if tm:
                out.append(Directive(tm.group(1), tm.group(2).strip(), src.path, m.start(), line, "tex"))
            continue
        if rest in BARE_KEYS:
            out.append(Directive(rest, "", src.path, m.start(), line, "bare"))
            continue
        rm = re.match(r"(begin|end)\s+([a-z][a-z-]*)$", rest)
        if rm:
            out.append(Directive(rm.group(2), "", src.path, m.start(), line, rm.group(1)))
            continue
        km = re.match(r"([a-z][a-z-]*)\s*:\s*(.*)$", rest)
        if km:
            out.append(Directive(km.group(1), km.group(2).strip(), src.path, m.start(), line, "kv"))
            continue
        out.append(Directive(rest.split()[0] if rest.split() else rest, rest, src.path, m.start(), line, "unknown"))
    return out


def list_value(value: str) -> list[str]:
    """A comma-separated directive value as a list, empty entries dropped."""
    return [v.strip() for v in value.split(",") if v.strip()]
