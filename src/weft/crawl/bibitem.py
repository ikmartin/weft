"""Formatted bibliographies: `\\bibitem`s wherever they sit in a paper's source.

arXiv does not run BibTeX, so a submitter supplies the formatted bibliography, and measuring real papers shows they usually paste `\\begin{thebibliography}` into a .tex file rather than ship a .bbl. **The unit is therefore `\\bibitem` wherever it occurs, not a file extension.** An entry is display text -- authors, title, journal, pages -- so an identifier is read from it where one is printed, and otherwise the text is what a lookup is made from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from weft.lookup import Query

BIBITEM = re.compile(r"\\bibitem(?:\[[^\]]*\])?\s*\{([^}]*)\}")
# `\arXiv{2407.08747}` is as common as a bare "arXiv:2407.08747", so the separator includes a brace
ARXIV = re.compile(r"arxiv(?:\.org/(?:abs|pdf)/|[:/\s{]*)((?:[a-z-]+(?:\.[A-Z]{2})?/)?\d{4}\.?\d{3,5}(?:v\d+)?)", re.I)
_COMMENT = re.compile(r"(?<!\\)%[^\n]*")
DOI = re.compile(r"\b10\.\d{4,9}/[^\s,}$\\]+")
_TITLE = re.compile(
    r"\\(?:textit|emph|textsl)\s*\{((?:[^{}]|\{[^{}]*\})*)\}|\{\\(?:it|em|sl)\s+((?:[^{}]|\{[^{}]*\})*)\}"
)
_YEAR = re.compile(r"\((1[89]\d\d|20\d\d)\)|\b(1[89]\d\d|20\d\d)\b")
_END = re.compile(r"\\end\{thebibliography\}")


@dataclass(frozen=True)
class BibItem:
    """One formatted entry: its key, the display text, the identifiers printed in it, and its raw source, which still says where the title is."""

    key: str
    text: str
    arxiv: str | None = None
    doi: str | None = None
    raw: str = ""


def _clean(text: str) -> str:
    """Display text without markup, for reading and for a lookup."""
    t = re.sub(r"%[^\n]*", " ", text)
    t = re.sub(r"\\(?:textit|emph|textbf|textsl|textsc|mathrm|mbox|url|href\{[^}]*\})\s*\{([^{}]*)\}", r"\1", t)
    t = re.sub(r"\{\\(?:it|em|bf|sl|sc)\s+([^{}]*)\}", r"\1", t)
    t = re.sub(r"\\(?:newblock|bibinfo\{[^}]*\})", " ", t)
    t = re.sub(r"\\[`'^\"~=.uvHck]\s*\{?\s*([A-Za-z])\s*\}?", r"\1", t)
    t = re.sub(r"\\[A-Za-z]+\s*", " ", t)
    t = t.replace("~", " ").replace("{", "").replace("}", "").replace("--", "-")
    return re.sub(r"\s+", " ", t).strip(" .,;")


def entries(text: str) -> list[BibItem]:
    """Every `\\bibitem` in a source text, in order, each ending where the next begins or the bibliography ends.

    Parameters
    ----------
    text : str
        One file's contents, .tex or .bbl.

    Returns
    -------
    list of BibItem
        A commented-out entry, or a commented-out line of one, is not part of the bibliography.
    """
    text = _COMMENT.sub("", text)
    marks = list(BIBITEM.finditer(text))
    out: list[BibItem] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end() : end]
        if stop := _END.search(body):
            body = body[: stop.start()]
        arxiv = ARXIV.search(body)
        doi = DOI.search(body)
        out.append(
            BibItem(
                m.group(1).strip(),
                _clean(body),
                arxiv.group(1) if arxiv else None,
                doi.group(0).rstrip(".") if doi else None,
                body,
            )
        )
    return out


def from_source(src: Path) -> list[BibItem]:
    """The `\\bibitem`s of an unpacked source, from its `.bbl` files and then its `.tex` files, without duplicates by key."""
    seen: set[str] = set()
    out: list[BibItem] = []
    for path in sorted(src.rglob("*.bbl")) + sorted(src.rglob("*.tex")):
        for item in entries(path.read_text(encoding="utf-8", errors="replace")):
            if item.key not in seen:
                seen.add(item.key)
                out.append(item)
    return out


def query(item: BibItem) -> Query:
    """A lookup for a formatted entry: the italicised title where the style marks one, the authors' surnames before it, the year.

    Without a marked title the whole text stands for the title, which a bibliographic search tolerates and weft's scoring then judges.
    """
    title = ""
    head = item.text
    if item.raw and (m := _TITLE.search(item.raw)):
        title = _clean(m.group(1) or m.group(2) or "")
        head = _clean(item.raw[: m.start()])
    # one author per comma or `and`; the last capitalised word of each is the surname, whichever order the style writes names in
    surnames = tuple(
        words[-1] for chunk in re.split(r",|\band\b|&", head) if (words := re.findall(r"[A-ZÀ-Ž][A-Za-zÀ-ž'-]+", chunk))
    )
    # an arXiv number (`1912.06162`) or a DOI can look like a year, so both go before one is read; a year in parentheses is the style's own, otherwise the last one printed is the publication's
    plain = DOI.sub(" ", ARXIV.sub(" ", re.sub(r"https?://\S+", " ", item.raw or item.text)))
    bracketed = [m.group(1) for m in _YEAR.finditer(plain) if m.group(1)]
    loose = [m.group(2) for m in _YEAR.finditer(plain) if m.group(2)]
    year = bracketed[0] if bracketed else loose[-1] if loose else ""
    return Query(title or item.text, surnames[:4], year, item.text)
