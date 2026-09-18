"""Locators: what a `\\cite[POSTNOTE]{citekey}` names, and what a result answers to (the digest contract, docs/specs/digest.md §6).

Normalisation lowercases, expands the abbreviation table, strips `~`, `\\S`, `\\href`, parentheses, trailing part selectors such as `(1)` or `(ii)`, page references, and the words see/cf/also, and folds plurals and Roman numerals; a postnote naming several results is split on commas, semicolons, and `and`, a bare number inheriting the taxon of the part before it.
"""

from __future__ import annotations

import re

ABBREV = {
    "thm": "theorem",
    "theorem": "theorem",
    "theorems": "theorem",
    "lem": "lemma",
    "lemma": "lemma",
    "lemmas": "lemma",
    "lemmata": "lemma",
    "prop": "proposition",
    "proposition": "proposition",
    "propositions": "proposition",
    "cor": "corollary",
    "corollary": "corollary",
    "corollaries": "corollary",
    "def": "definition",
    "defn": "definition",
    "definition": "definition",
    "definitions": "definition",
    "rem": "remark",
    "rmk": "remark",
    "remark": "remark",
    "remarks": "remark",
    "ex": "example",
    "exa": "example",
    "example": "example",
    "examples": "example",
    "sec": "section",
    "sect": "section",
    "section": "section",
    "sections": "section",
    "subsec": "subsection",
    "subsection": "subsection",
    "eq": "equation",
    "eqn": "equation",
    "equation": "equation",
    "equations": "equation",
    "conj": "conjecture",
    "conjecture": "conjecture",
    "constr": "construction",
    "construction": "construction",
    "cond": "condition",
    "condition": "condition",
    "conv": "convention",
    "convention": "convention",
    "notn": "notation",
    "notation": "notation",
    "ch": "chapter",
    "chap": "chapter",
    "chapter": "chapter",
    "chapters": "chapter",
    "app": "appendix",
    "appendix": "appendix",
    "tag": "tag",
    "tags": "tag",
    "ass": "assumption",
    "assumption": "assumption",
    "assumptions": "assumption",
    "hyp": "hypothesis",
    "hypothesis": "hypothesis",
    "q": "question",
    "question": "question",
    "para": "paragraph",
    "paragraph": "paragraph",
    "fig": "figure",
    "figure": "figure",
    "tab": "table",
    "table": "table",
}
TAXON_WORDS = set(ABBREV.values())
ROMAN = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
    "xi": 11,
    "xii": 12,
}
DROP_WORDS = {"see", "cf", "also", "eg", "ie", "the", "of", "in", "compare", "esp", "especially"}
_SPLIT = re.compile(r"\s*(?:;|,|\band\b|&)\s*")
_PAGE = re.compile(r"\b(?:pp?|pages?)\.?\s*\d+\s*(?:--?|–|—)?\s*\d*")
_PART = re.compile(r"\s*\((?:\d+|[ivxl]+|[a-z])\)")
_LOCATOR = re.compile(r"\\cite\s*\[([^\]]*)\]")


def normalize(text: str) -> str:
    """The canonical form of a postnote or locator; '' when nothing but a page reference or filler remains."""
    s = text
    s = re.sub(r"\\href\s*\{[^}]*\}\s*\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\S\b|§", " section ", s)
    s = re.sub(r"\\[A-Za-z@]+\*?\s*", " ", s)
    s = s.replace("~", " ").replace("{", "").replace("}", "").replace("\\", " ")
    s = s.lower()
    s = _PAGE.sub(" ", s)
    s = _PART.sub(" ", s)
    s = s.replace("(", " ").replace(")", " ")
    s = re.sub(r"(?<=[a-z])\.(?=\s|$)", "", s)  # the period of an abbreviation, never the dot inside a.31
    s = re.sub(r"[,;:]+", " ", s)
    words = [w for w in re.split(r"\s+", s.strip()) if w]
    out: list[str] = []
    for w in words:
        if w in DROP_WORDS:
            continue
        out.append(ABBREV.get(w, w))
    for i in range(1, len(out)):
        if out[i] in ROMAN and out[i - 1] in TAXON_WORDS:
            out[i] = str(ROMAN[out[i]])
    return " ".join(out)


def parts(postnote: str) -> list[str]:
    """The normalised results a postnote names: one per comma, semicolon, or `and`; a bare number takes the taxon of the part before it."""
    out: list[str] = []
    last_taxon: str | None = None
    for raw in _SPLIT.split(_PAGE.sub(" ", postnote)):
        n = normalize(raw)
        if not n:
            continue
        words = n.split(" ")
        if words[0] in TAXON_WORDS:
            last_taxon = words[0]
        elif last_taxon and re.match(r"^[a-z]?\d", words[0]):
            n = f"{last_taxon} {n}"
        out.append(n)
    return out


def locator_of(title: str | None) -> str | None:
    """The locator inside a digest node's title, `{\\cite[LOCATOR]{citekey}}`."""
    if not title:
        return None
    m = _LOCATOR.search(title)
    return m.group(1).strip() if m else None


def forms_for(local: str, taxon: str, number: str, aliases: list[str], locator: str) -> set[str]:
    """Every normalised string that names this result: its locator, each part of it, and `<taxon> <number>` read off its paper-local part and off every alias.

    An alias such as `thm-1.2.1` beside the local part `thm-1.0.1` is what lets one result answer another version's numbering; `setup` also answers standing assumptions.
    """
    out: set[str] = set()
    if locator:
        out.add(normalize(locator))
        out.update(parts(locator))
    if taxon and number:
        out.add(normalize(f"{taxon} {number}"))
    for label in [local, *aliases]:
        if not label:
            continue
        if label == "setup" or label.endswith("-setup"):
            out.add(normalize("standing assumptions"))
        pieces = label.split("-")
        if len(pieces) >= 2 and pieces[0] in ABBREV:
            out.add(normalize(f"{ABBREV[pieces[0]]} {'-'.join(pieces[1:])}"))
    out.discard("")
    return out


def match(postnote: str, candidates: list[tuple[str, set[str]]]) -> list[str]:
    """Keys of the candidates any part of the postnote names, in candidate order. Several keys is an ambiguity the caller logs rather than guesses at (docs/multi-match-record.md)."""
    wanted = set(parts(postnote))
    if not wanted:
        return []
    return [key for key, forms in candidates if forms & wanted]
