"""A minimal BibTeX reader: entry keys and the fields identification and a seed list need.

A seed file is someone's own bibliography, so the reader tolerates what real files hold: `(` as well as `{`, concatenation with `#`, quoted values, and `@string`/`@comment`/`@preamble` blocks it steps over. It is not a BibTeX implementation -- macros are not expanded and cross-references are not followed -- because nothing downstream needs more than the entry's own fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_ENTRY = re.compile(r"@(\w+)\s*[{(]")
_FIELD = re.compile(r"\s*([A-Za-z][\w-]*)\s*=\s*")


def match_group(text: str, pos: int, open_ch: str = "{", close_ch: str = "}") -> int:
    """Given `text[pos] == open_ch`, the offset just past the matching `close_ch`, or -1 when unbalanced.

    Escaped delimiters and nested braces are honoured, and matching crosses newlines, so a field value split over lines is one value.
    """
    if pos >= len(text) or text[pos] != open_ch:
        return -1
    depth = 0
    i = pos
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{" and open_ch != "{":
            j = match_group(text, i, "{", "}")
            i = j if j > 0 else i + 1
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


@dataclass
class BibEntry:
    """One entry: its citekey, its type, and its fields with names lowercased and whitespace collapsed."""

    key: str
    type: str
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def eprint(self) -> str | None:
        return self.fields.get("eprint")

    @property
    def version(self) -> str | None:
        """The arXiv version an entry names, from a `version` field or a `vN` suffix on the eprint."""
        v = self.fields.get("version")
        if v:
            return v
        e = self.eprint or ""
        m = re.search(r"v(\d+)$", e)
        return m.group(1) if m else None


def _value(text: str, pos: int) -> tuple[str, int]:
    """One field value from `pos`, and where it ends: a braced group, a quoted string, a bare word, or several joined by `#`."""
    p = pos
    n = len(text)
    parts: list[str] = []
    while p < n:
        while p < n and text[p] in " \t\n":
            p += 1
        if p >= n:
            break
        ch = text[p]
        if ch == "{":
            q = match_group(text, p)
            if q < 0:
                break
            parts.append(text[p + 1 : q - 1])
            p = q
        elif ch == '"':
            q = text.find('"', p + 1)
            q = n if q < 0 else q
            parts.append(text[p + 1 : q])
            p = q + 1
        else:
            m = re.match(r"[^,#}\n]+", text[p:])
            if not m:
                break
            parts.append(m.group(0).strip())
            p += m.end()
        while p < n and text[p] in " \t\n":
            p += 1
        if p < n and text[p] == "#":
            p += 1
            continue
        break
    return "".join(parts), p


def parse_bib(text: str) -> dict[str, BibEntry]:
    """Every entry of a BibTeX file, by citekey.

    Parameters
    ----------
    text : str
        The file's contents.

    Returns
    -------
    dict of str to BibEntry
        In the order they appear; a repeated citekey keeps the last entry, as BibTeX itself does. `@comment`, `@preamble` and `@string` blocks are skipped.
    """
    entries: dict[str, BibEntry] = {}
    for m in _ENTRY.finditer(text):
        etype = m.group(1).lower()
        open_ch = text[m.end() - 1]
        close_ch = "}" if open_ch == "{" else ")"
        end = match_group(text, m.end() - 1, open_ch, close_ch)
        if end < 0:
            continue
        body = text[m.end() : end - 1]
        if etype in ("comment", "preamble", "string"):
            continue
        key_m = re.match(r"\s*([^,]+?)\s*,", body)
        if not key_m:
            continue
        entry = BibEntry(key=key_m.group(1), type=etype)
        pos = key_m.end()
        while pos < len(body):
            fm = _FIELD.match(body, pos)
            if not fm:
                nxt = body.find(",", pos)
                if nxt < 0:
                    break
                pos = nxt + 1
                continue
            value, pos = _value(body, fm.end())
            entry.fields[fm.group(1).lower()] = re.sub(r"\s+", " ", value).strip()
            nxt = body.find(",", pos)
            if nxt < 0:
                break
            pos = nxt + 1
        entries[entry.key] = entry
    return entries
