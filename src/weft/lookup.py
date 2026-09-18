"""Which work a bibliography entry or a formatted reference is: a lookup at zbMATH Open, then Crossref.

Measured on two real papers: every bibliography parsed, and 9% of 103 entries carried a usable identifier. A `\\bibitem` is display text and mathematics styles rarely print a DOI, so most of a citation network has to be identified by title, surnames and year.

Every returned record is scored here rather than trusting either service's own score, so a confidence means the same thing whichever service answered. The core takes a `Query`, which a BibTeX entry and a formatted reference string both reduce to.

Unlike loom, weft **binds** a match at or above `STRONG` as the work's identity, because a walk cannot proceed on candidates alone; below it the work stays unidentified and is counted. loom refuses to bind because a wrong binding would edit an author's bibliography; weft owns its corpus.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from weft.bib import BibEntry
from weft.crawl.net import NotFound, Service, ServiceError
from weft.identity import WorkId

ZBMATH = "https://api.zbmath.org/v1/document/_search"
CROSSREF = "https://api.crossref.org/works"

STRONG = 0.9
POSSIBLE = 0.75


class LookupRefused(Exception):
    """The query has too little to look up, or every service asked failed."""


@dataclass(frozen=True)
class Query:
    """What is known about a work: the text a service is searched with, and the facts a match is scored against."""

    title: str
    surnames: tuple[str, ...] = ()
    year: str = ""
    text: str = ""

    @property
    def bibliographic(self) -> str:
        """One free-text reference string, which is what Crossref's `query.bibliographic` matches best."""
        return self.text or " ".join(x for x in [" ".join(self.surnames), self.title, self.year] if x)


@dataclass
class Candidate:
    """One identifier a service proposed for a work, with what it matched."""

    id: str
    source: str
    confidence: float
    title: str
    authors: list[str] = field(default_factory=list)
    year: str = ""
    also: list[str] = field(default_factory=list)

    @property
    def strength(self) -> str:
        return "strong" if self.confidence >= STRONG else "possible"

    def evidence(self) -> dict[str, Any]:
        """What was matched, for the plan to record beside the binding it made."""
        return {
            "id": self.id,
            "also": list(self.also),
            "source": self.source,
            "confidence": self.confidence,
            "title": self.title,
            "year": self.year,
        }


def _plain(text: str) -> str:
    """Bibliography markup removed: braces, accent commands and math delimiters, so `{{Gromov}}--{{Witten}}` compares as `Gromov-Witten`."""
    t = re.sub(r"\\[`'^\"~=.uvHck]\s*\{?\s*([A-Za-z])\s*\}?", r"\1", text)
    t = re.sub(r"\\[A-Za-z]+\s*", " ", t)
    t = t.replace("{", "").replace("}", "").replace("$", "").replace("--", "-")
    return re.sub(r"\s+", " ", t).strip()


def _fold(text: str) -> str:
    """Lowercase ASCII words, for comparing titles and names written with different conventions."""
    t = unicodedata.normalize("NFKD", _plain(text))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def query_for(entry: BibEntry) -> Query:
    """The query for a BibTeX entry: its title, the surnames of its authors, and its year."""
    surnames: list[str] = []
    for part in re.split(r"\s+and\s+", entry.fields.get("author", "")):
        part = _plain(part)
        if not part or part.lower() == "others":
            continue
        surnames.append(part.split(",")[0].strip() if "," in part else part.split()[-1])
    # biblatex writes `date = {1998-06}` where BibTeX writes `year = {1998}`
    year = (entry.fields.get("year") or entry.fields.get("date") or "").strip()[:4]
    return Query(_plain(entry.fields.get("title", "")), tuple(surnames), year)


def _surname(name: str) -> str:
    """A name's surname, folded: what precedes the comma in `Arabia, Alberto`, the last word in `Alberto Arabia`."""
    folded = _fold(name.split(",")[0] if "," in name else name).split()
    return folded[-1] if folded else ""


def score(q: Query, title: str, authors: list[str], year: str) -> float:
    """How likely a returned record is the queried work, from 0 to 1.

    Parameters
    ----------
    q : Query
        What is known about the work.
    title : str
        The record's title.
    authors : list of str
        The record's authors, in any name order.
    year : str
        The record's year.

    Returns
    -------
    float
        0.75 * the folded title ratio, + 0.15 when the first queried surname appears among the record's authors, + 0.10 when the years are within one, rounded to three places. A title alone that matches exactly still reaches `POSSIBLE`, never `STRONG`, because a different book can share a title.

    Notes
    -----
    A query that is only a formatted reference -- `A. Arabia, Cycles de Schubert…, Invent. Math. 85 (1986)`, with no title known apart from the text -- is scored by the record's title appearing within the text and an author's surname appearing in it, which is what a person checking the match would look for.
    """
    qt, rt = _fold(q.title), _fold(title)
    if not qt or not rt:
        return 0.0
    free_text = bool(q.text) and q.title == q.text
    if free_text:
        ratio = 1.0 if len(rt) >= 12 and f" {rt} " in f" {qt} " else difflib.SequenceMatcher(None, qt, rt).ratio()
    else:
        ratio = difflib.SequenceMatcher(None, qt, rt).ratio()
        # a subtitle one side omits should not sink an otherwise exact title
        if rt.startswith(qt) or qt.startswith(rt):
            ratio = max(ratio, 0.92)
    s = 0.75 * ratio
    folded = " ".join(_fold(a) for a in authors)
    if q.surnames and _fold(q.surnames[0]) and _fold(q.surnames[0]) in folded:
        s += 0.15
    elif free_text and any(len(sn) > 1 and f" {sn} " in f" {qt} " for sn in (_surname(a) for a in authors)):
        s += 0.15
    if q.year[:4].isdigit() and str(year)[:4].isdigit() and abs(int(q.year[:4]) - int(str(year)[:4])) <= 1:
        s += 0.10
    return round(min(1.0, s), 3)


def _zbmath_candidates(q: Query, data: dict[str, Any]) -> list[Candidate]:
    out: list[Candidate] = []
    for r in data.get("result") or []:
        title = r.get("title")
        title = title.get("title", "") if isinstance(title, dict) else str(title or "")
        authors = [a.get("name", "") for a in (r.get("contributors") or {}).get("authors", [])]
        year = str(r.get("year") or "")
        dois = [
            link["identifier"] for link in r.get("links") or [] if link.get("type") == "doi" and link.get("identifier")
        ]
        # zbMATH also knows a work's preprint, which is the identifier weft can actually fetch
        preprints = [
            link["identifier"]
            for link in r.get("links") or []
            if link.get("type") == "arxiv" and link.get("identifier")
        ]
        zbl = str(r.get("identifier") or "")
        conf = score(q, title, authors, year)
        if conf < POSSIBLE:
            continue
        ids = [f"doi:{d}" for d in dois] + ([f"zbl:{zbl}"] if zbl else []) + [f"arxiv:{a}" for a in preprints]
        if not ids:
            continue
        out.append(Candidate(ids[0], "zbMATH Open", conf, title, authors, year, ids[1:]))
    return out


def _crossref_candidates(q: Query, data: dict[str, Any]) -> list[Candidate]:
    out: list[Candidate] = []
    for it in (data.get("message") or {}).get("items", []):
        title = " ".join(it.get("title") or [])
        authors = [" ".join(x for x in [a.get("given", ""), a.get("family", "")] if x) for a in it.get("author") or []]
        parts = ((it.get("issued") or {}).get("date-parts") or [[None]])[0]
        year = str(parts[0]) if parts and parts[0] else ""
        conf = score(q, title, authors, year)
        if conf < POSSIBLE or not it.get("DOI"):
            continue
        out.append(Candidate(f"doi:{it['DOI']}", "Crossref", conf, title, authors, year))
    return out


class Resolver:
    """Asks zbMATH Open, then Crossref, through services that share the host budget and the cache.

    Parameters
    ----------
    zbmath : Service
        The service for `api.zbmath.org`.
    crossref : Service
        The service for `api.crossref.org`.
    contact : str, default ''
        An address sent to Crossref as `mailto`, which routes requests to its polite pool. Sent only when set.

    See Also
    --------
    candidates : the whole lookup, best match first.
    """

    def __init__(self, zbmath: Service, crossref: Service, contact: str = "") -> None:
        self.zb = zbmath
        self.cr = crossref
        self.contact = contact

    @property
    def requests(self) -> int:
        """Requests that reached a service, cached answers excluded."""
        return self.zb.requests + self.cr.requests

    def zbmath(self, q: Query) -> list[Candidate]:
        terms = [f"ti:{q.title}"] + ([f"au:{q.surnames[0]}"] if q.surnames else [])
        params = {"search_string": " & ".join(terms), "page": "0", "results_per_page": "5"}
        return _zbmath_candidates(q, self.zb.get_json(ZBMATH + "?" + urllib.parse.urlencode(params)))

    def crossref(self, q: Query) -> list[Candidate]:
        params = {"query.bibliographic": q.bibliographic, "rows": "5", "select": "DOI,title,author,issued"}
        if self.contact:
            params["mailto"] = self.contact
        return _crossref_candidates(q, self.cr.get_json(CROSSREF + "?" + urllib.parse.urlencode(params)))

    def candidates(self, q: Query) -> list[Candidate]:
        """Every candidate for a query, best first, one per work.

        Parameters
        ----------
        q : Query
            What is known about the work; a query with no title is refused rather than sent.

        Returns
        -------
        list of Candidate
            Merged so that two services describing one record are one candidate.

        Raises
        ------
        LookupRefused
            The query has no title, or every service asked failed. A 404 is no match rather than a failure.

        Notes
        -----
        zbMATH Open is asked first, since it covers mathematics best and gives a Zbl number to works with no DOI. Crossref is asked when zbMATH found nothing strong, or found a strong match with no DOI, since a DOI is the identifier a corpus most usefully carries.
        """
        if not q.title:
            raise LookupRefused("the entry has no title to look up")
        found: list[Candidate] = []
        errors: list[str] = []
        try:
            found += self.zbmath(q)
        except NotFound:
            pass
        except (ServiceError, ValueError) as exc:
            errors.append(str(exc))
        best = max(found, key=lambda c: c.confidence, default=None)
        if best is None or best.strength != "strong" or not best.id.startswith("doi:"):
            try:
                found += self.crossref(q)
            except NotFound:
                pass
            except (ServiceError, ValueError) as exc:
                errors.append(str(exc))
        if not found and errors:
            raise LookupRefused("; ".join(errors))
        return merge(found)


RANK = {"doi": 0, "arxiv": 1, "mr": 2, "zbl": 3}


def merge(found: list[Candidate]) -> list[Candidate]:
    """One candidate per work, best first.

    Two services describing the same record -- the same identifier, or the same title and year -- are one work: their identifiers are pooled and the lead is the most useful of them (a DOI, then a preprint, then MR, then Zbl), and the confidence is the higher of the two. Ties between different works go to the one with the more useful identifier.
    """
    works: list[Candidate] = []
    for c in sorted(found, key=lambda c: -c.confidence):
        ids = {c.id.lower(), *(a.lower() for a in c.also)}
        same = next(
            (
                w
                for w in works
                if ids & {w.id.lower(), *(a.lower() for a in w.also)}
                or (_fold(w.title) == _fold(c.title) and (w.year[:4] == c.year[:4] or not w.year or not c.year))
            ),
            None,
        )
        if same is None:
            order = sorted([c.id, *c.also], key=lambda x: RANK.get(x.partition(":")[0], 9))
            works.append(Candidate(order[0], c.source, c.confidence, c.title, list(c.authors), c.year, order[1:]))
            continue
        pool = [same.id, *same.also] + [
            x for x in [c.id, *c.also] if x.lower() not in {y.lower() for y in [same.id, *same.also]}
        ]
        pool.sort(key=lambda x: RANK.get(x.partition(":")[0], 9))
        same.id, same.also = pool[0], pool[1:]
        if c.source not in same.source:
            same.source += f", {c.source}"
        same.confidence = max(same.confidence, c.confidence)
    works.sort(key=lambda w: (-w.confidence, RANK.get(w.id.partition(":")[0], 9)))
    return works


def as_workid(c: Candidate) -> WorkId:
    """A candidate's identifier, marked as resolved rather than declared."""
    scheme, _, value = c.id.partition(":")
    return WorkId(scheme, value, "resolved")
