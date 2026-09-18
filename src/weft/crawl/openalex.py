"""OpenAlex: reference lists zbMATH lacks, open copies of published papers, and DOIs.

One work by DOI is free; a batch of up to 50 by OpenAlex id is one list call: Graber-Pandharipande's 19 references came back as 18 works, 16 with DOIs and 5 with an open PDF. An arXiv preprint's record lists no references. A key is sent as a bearer header from `WEFT_OPENALEX_KEY`, so it never appears in a URL or names a cache file; without one, requests draw on the small anonymous allowance. Data CC0.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from weft.crawl.net import NotFound, Service
from weft.crawl.work import norm

BASE = "https://api.openalex.org/works"
BATCH = 50
SELECT = "id,doi,title,publication_year,authorships,best_oa_location,locations,referenced_works"
_ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf)/((?:[a-z-]+(?:\.[A-Z]{2})?/)?\d{4}\.?\d{3,5})", re.I)


@dataclass
class OaRecord:
    """One OpenAlex work: its own id, the identifiers it carries, and what it references."""

    openalex: str
    ids: list[str]
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    references: list[str] = field(default_factory=list)
    open_pdf: str = ""


def parse(w: dict[str, Any]) -> OaRecord:
    """One OpenAlex work as a record; an arXiv location becomes an `arxiv:` identifier."""
    ids: list[str] = []
    if w.get("doi"):
        ids.append(norm("doi:" + str(w["doi"])))
    arxiv = ""
    for loc in [w.get("best_oa_location") or {}, *(w.get("locations") or [])]:
        for url in (loc.get("landing_page_url"), loc.get("pdf_url")):
            if url and (m := _ARXIV_URL.search(url)):
                arxiv = m.group(1)
    if arxiv:
        ids.append(f"arxiv:{arxiv}")
    ids = list(dict.fromkeys(norm(i) for i in ids))  # arXiv's own DOI and its location name one identifier
    best = w.get("best_oa_location") or {}
    pdf = best.get("pdf_url") or ""
    return OaRecord(
        openalex=str(w.get("id") or "").rsplit("/", 1)[-1],
        ids=ids,
        title=str(w.get("title") or ""),
        authors=[((a.get("author") or {}).get("display_name") or "") for a in w.get("authorships") or []],
        year=w.get("publication_year"),
        references=[str(r).rsplit("/", 1)[-1] for r in w.get("referenced_works") or []],
        # an arXiv copy is fetched as source, so an open copy is kept only when it is somewhere else
        open_pdf="" if _ARXIV_URL.search(pdf) else pdf,
    )


class OpenAlex:
    """Works by identifier and in batches; the key, when there is one, travels as a header."""

    def __init__(self, service: Service, key: str = "") -> None:
        self.service = service
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}

    def by_id(self, ident: str) -> OaRecord | None:
        """The record for a DOI or an arXiv number (through arXiv's DOI), or None when OpenAlex has none."""
        scheme, _, value = norm(ident).partition(":")
        if scheme == "doi":
            doi = value
        elif scheme == "arxiv":
            doi = f"10.48550/arxiv.{value}"
        else:
            return None
        url = f"{BASE}/doi:{urllib.parse.quote(doi, safe='/.:')}?select={SELECT}"
        try:
            return parse(self.service.get_json(url, self.headers))
        except NotFound:
            return None

    def batch(self, openalex_ids: list[str]) -> list[OaRecord]:
        """Records for OpenAlex ids, 50 to a request."""
        out: list[OaRecord] = []
        for i in range(0, len(openalex_ids), BATCH):
            chunk = openalex_ids[i : i + BATCH]
            url = f"{BASE}?filter=openalex_id:{'|'.join(chunk)}&per-page={BATCH}&select={SELECT}"
            try:
                data = self.service.get_json(url, self.headers)
            except NotFound:
                continue
            out += [parse(w) for w in data.get("results") or []]
        return out
