"""zbMATH Open: MSC codes and resolved reference lists.

Looked up by DOI, arXiv number or Zbl number through `_search`, by title and first author for a work it does not know by identifier (a book cited by one edition's or one chapter's DOI, typically), and by zbMATH's own document number for a reference zbMATH matched. A record's references carry the DOI and the document number of the works zbMATH matched them to, with their MSC codes; old papers often have none, recent published ones many. Data CC-BY-SA 4.0.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from weft.crawl.net import NotFound, Service
from weft.crawl.work import Reference, norm
from weft.lookup import STRONG, Query, _plain, _surname, score

BASE = "https://api.zbmath.org/v1/document"
_ZBL = re.compile(r"^\d{4}\.\d{5}$")


@dataclass
class ZbRecord:
    """One zbMATH document: its number, its identifiers, its subjects and the references it resolved."""

    document: int
    ids: list[str]
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    msc: list[str] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    original: str = ""  # the title in the language of publication, when zbMATH gives the work an English one


def parse(r: dict[str, Any]) -> ZbRecord:
    """One zbMATH document as a record."""
    ids: list[str] = []
    ident = str(r.get("identifier") or "")
    if _ZBL.match(ident):
        ids.append(f"zbl:{ident}")
    elif ident.lower().startswith("arxiv:"):
        ids.append("arxiv:" + ident.split(":", 1)[1])
    for link in r.get("links") or []:
        if link.get("type") == "doi" and link.get("identifier"):
            ids.append(f"doi:{link['identifier']}")
        if link.get("type") == "arxiv" and link.get("identifier"):
            ids.append(f"arxiv:{link['identifier']}")
    t = r.get("title")
    title = str(t.get("title") or "") if isinstance(t, dict) else str(t or "")
    original = str(t.get("original") or "") if isinstance(t, dict) else ""
    year = str(r.get("year") or "")[:4]
    refs: list[Reference] = []
    for ref in r.get("references") or []:
        zb = ref.get("zbmath") or {}
        doi = ref.get("doi")
        refs.append(
            Reference(
                work=f"doi:{doi}" if doi else "",
                text=(ref.get("text") or "").strip(),
                identified_by="index" if doi else "",
                zbmath=zb.get("document_id") or None,
                msc=list(zb.get("msc") or []),
            )
        )
    return ZbRecord(
        document=int(r.get("id") or 0),
        ids=ids,
        title=title,
        original=original,
        authors=[a.get("name", "") for a in (r.get("contributors") or {}).get("authors", [])],
        year=int(year) if year.isdigit() else None,
        msc=[m["code"] for m in r.get("msc") or [] if m.get("code")],
        references=refs,
    )


class Zbmath:
    """The three lookups the crawl makes: by identifier, by zbMATH's own document number, and by title."""

    def __init__(self, service: Service) -> None:
        self.service = service

    def _search(self, query: str) -> list[dict[str, Any]]:
        url = (
            BASE + "/_search?" + urllib.parse.urlencode({"search_string": query, "page": "0", "results_per_page": "3"})
        )
        try:
            data = self.service.get_json(url)
        except NotFound:
            return []
        return list(data.get("result") or [])

    def by_id(self, ident: str) -> ZbRecord | None:
        """The record for a DOI, an arXiv number or a Zbl number, when zbMATH has exactly that work."""
        scheme, _, value = norm(ident).partition(":")
        field_name = {"doi": "doi", "arxiv": "arxiv", "zbl": "an"}.get(scheme)
        if not field_name:
            return None
        for r in self._search(f"{field_name}:{value}"):
            rec = parse(r)
            if any(norm(i) == norm(ident) for i in rec.ids):
                return rec
        return None

    def by_document(self, document: int) -> ZbRecord | None:
        """The record for zbMATH's own document number, which identifies a matched reference exactly in one request."""
        try:
            data = self.service.get_json(f"{BASE}/{int(document)}")
        except NotFound:
            return None
        r = data.get("result")
        r = r[0] if isinstance(r, list) and r else r
        return parse(r) if isinstance(r, dict) else None

    def by_title(self, title: str, authors: list[str], year: int | None) -> ZbRecord | None:
        """The record matching a title, first author and year at or above STRONG; None without an author, since a title alone is never strong.

        Both the English title and the title in the language of publication are scored, because the cited form is often the latter.
        """
        surname = _surname(authors[0]) if authors else ""
        words = re.sub(r"[^\w\s-]", " ", _plain(title)).split()
        if not surname or not words:
            return None
        q = Query(" ".join(words), (surname,), str(year or ""))
        scored = [
            (max(score(q, t, rec.authors, str(rec.year or "")) for t in (rec.title, rec.original)), rec)
            for rec in map(parse, self._search(f"ti:{q.title} & au:{surname}"))
        ]
        best = max(scored, key=lambda t: t[0], default=None)
        return best[1] if best and best[0] >= STRONG else None
