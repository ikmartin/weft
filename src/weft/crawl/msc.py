"""Subjects and categories: which works a crawl keeps.

`[crawl] subjects` lists MSC families, the first three characters of a code (`14N` for `14N35`); a work zbMATH has classified is kept when any of its codes is in one. `[crawl] categories` lists arXiv categories; a work with no MSC code, typically a recent preprint, is kept when its primary category is one of them.

**Filtering is configured, never inferred.** Two measurements say so. A default of "the families of the seeds' primary MSC codes" excluded `14L`, algebraic groups, the primary family of 20 of the works the seeds cite and a code of 45. A table mapping MSC families to arXiv categories, measured on 1,675 arXiv records, held the category authors chose for 93% of algebraic-geometry papers, 75% of PDE and 38% of ODE; it was removed. Any correspondence weft held would suit some fields and silently lose papers in others, so `weft survey` counts what is there and the author chooses.
"""

from __future__ import annotations

import re
from collections import Counter

_CODE = re.compile(r"^(\d\d)([A-Z-])?")


def family(code: str) -> str:
    """The family of an MSC code: `14N35` -> `14N`, `14-02` -> `14-`, `14` -> `14-`."""
    m = _CODE.match(code.strip())
    if not m:
        return code.strip()[:3]
    return m.group(1) + (m.group(2) or "-")


def families(codes: list[str]) -> list[str]:
    """The distinct families of some codes, sorted."""
    return sorted({family(c) for c in codes if _CODE.match(c.strip())})


def passes(msc: list[str], arxiv_category: str, fams: list[str], categories: list[str]) -> bool | None:
    """Whether a work is kept: by its MSC codes when it has any, by its arXiv category otherwise, and None when it has neither."""
    if msc:
        chosen = set(fams)
        return any(family(c) in chosen for c in msc)
    if arxiv_category:
        return arxiv_category in categories
    return None


def tally(works: list[tuple[list[str], str]]) -> dict[str, Counter[str]]:
    """Counts over (MSC codes, arXiv category) pairs: primary families, families of any code, the categories of works with no code, and works with neither."""
    out: dict[str, Counter[str]] = {
        "primary": Counter(),
        "any": Counter(),
        "categories": Counter(),
        "neither": Counter(),
    }
    for msc, category in works:
        if msc:
            out["primary"][family(msc[0])] += 1
            out["any"].update(families(msc))
        elif category:
            out["categories"][category] += 1
        else:
            out["neither"]["works"] += 1
    return out
