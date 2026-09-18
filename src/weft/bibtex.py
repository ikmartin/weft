"""A BibTeX entry for a corpus work: the handoff to a paper's own tool.

weft never writes into anyone's paper. When a mathematician finds a work here that they want to use, they take this entry, put it in their own bibliography, and their tool (loom) fetches and digests the work at depth 1 under their own citekey. So the entry has to be one loom's reader accepts: the fields it reads for identity are `doi`, `eprint` with `eprinttype`, `mrnumber` and `zbl`, and every identifier the corpus holds is written, since a DOI and an eprint name different artifacts of one work and both are useful.
"""

from __future__ import annotations

import re

from weft.model import Work

# The order fields are written in, for a stable entry a person can diff.
_FIELDS = ("title", "author", "year", "doi", "eprint", "eprinttype", "mrnumber", "zbl")
RANK = {"doi": 0, "arxiv": 1, "mr": 2, "zbl": 3, "work": 4}
_ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(\S+)$", re.I)


def citekey(identifier: str) -> str:
    """A BibTeX-safe key from an identifier: its text with every non-alphanumeric character dropped.

    `arxiv:1709.09864` becomes `arxiv170909864`. Deterministic, so two corpora hand out the same key for one work, and free of the characters BibTeX treats specially.
    """
    return re.sub(r"[^A-Za-z0-9]", "", identifier)


def identifiers(work: Work) -> list[str]:
    """The work's identifiers, ranked most useful first: a DOI, then a preprint, then MR, then Zbl, then a synthetic key.

    An arXiv DOI (`10.48550/arxiv.X`) is read as the preprint it names, so one artifact yields one field and not a `doi` that a reader would have to normalise back.
    """
    out: list[str] = []
    for ident in work.ids or [work.key]:
        scheme, _, value = ident.partition(":")
        scheme, value = scheme.lower().strip(), value.strip()
        if scheme == "doi" and (m := _ARXIV_DOI.match(value)):
            scheme, value = "arxiv", m.group(1)
        if value and f"{scheme}:{value}" not in out:
            out.append(f"{scheme}:{value}")
    return sorted(out, key=lambda i: RANK.get(i.partition(":")[0], 9))


def fields_for(work: Work) -> dict[str, str]:
    """The fields of the work's entry, in writing order, empty ones dropped.

    `eprinttype` accompanies `eprint` because loom reads the eprint as an arXiv number only when the archive is arXiv or unstated, and being explicit is what makes the entry survive being merged into a bibliography that uses biblatex.
    """
    out = {
        "title": work.title,
        "author": " and ".join(a for a in work.authors if a),
        "year": work.year,
    }
    for ident in identifiers(work):
        scheme, _, value = ident.partition(":")
        if scheme == "doi":
            out.setdefault("doi", value)
        elif scheme == "arxiv":
            out.setdefault("eprint", value)
            out.setdefault("eprinttype", "arXiv")
        elif scheme == "mr":
            out.setdefault("mrnumber", value)
        elif scheme == "zbl":
            out.setdefault("zbl", value)
    return {k: out[k] for k in _FIELDS if out.get(k)}


def entry_for(work: Work) -> str:
    """The BibTeX entry for one work of the corpus.

    Parameters
    ----------
    work : Work
        A work as the index holds it; its `ids` supply every identifier written.

    Returns
    -------
    str
        One `@article` entry, or `@misc` when the work has no year, keyed by the ranked-first identifier with non-alphanumerics dropped, ending in a newline.

    See Also
    --------
    citekey : the key alone.
    identifiers : the identifiers written, in the order they are ranked.
    """
    kind = "article" if work.year else "misc"
    lines = [f"@{kind}{{{citekey(identifiers(work)[0])},"]
    lines += [f"  {name} = {{{value}}}," for name, value in fields_for(work).items()]
    lines.append("}")
    return "\n".join(lines) + "\n"
