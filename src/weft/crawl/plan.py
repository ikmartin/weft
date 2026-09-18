"""Planning a crawl from metadata alone.

The plan identifies the seeds, reads their reference lists from zbMATH Open, OpenAlex and any source already on disk, identifies each reference, keeps the works in the configured subjects and categories, and repeats to the chosen depth. **Depth 1 is the seeds**; a work at `depth` is included and not expanded. Nothing is downloaded. It writes a record per work and `crawl/plan.json`, and says what a fetch would do: how many works can be downloaded, in what order, within the cap, and at what cost.

A plan carries a fingerprint of the settings that decide the walk plus the seed texts, so a fetch refuses a plan that no longer describes the corpus.

The count is exact wherever an index lists a work's references and a floor where none does: a preprint's references are known only once its source is on disk, and the plan counts the works in that state.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from weft.bib import BibEntry, parse_bib
from weft.config import Settings
from weft.crawl import msc as M
from weft.crawl.arxiv import Arxiv
from weft.crawl.bibitem import from_source
from weft.crawl.bibitem import query as bib_query
from weft.crawl.net import Service, ServiceError
from weft.crawl.openalex import OpenAlex
from weft.crawl.work import Record, Reference, home_of, norm, ranked
from weft.crawl.work import load as load_record
from weft.crawl.work import save as save_record
from weft.crawl.zbmath import Zbmath
from weft.files import write_atomic
from weft.identity import declared, primary
from weft.identity import parse as parse_id
from weft.lookup import LookupRefused, Query, Resolver, _plain, _surname, query_for

PLAN = 1
# what a download is assumed to cost until the corpus has some of its own to average
AVG_SOURCE = 3_000_000
AVG_PDF = 1_000_000
SOURCE_SECONDS = 3.0
PDF_SECONDS = 1.0
_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")


class PlanRefused(Exception):
    """A plan cannot be made as asked, for a reason the author can fix."""


@dataclass(frozen=True)
class Seed:
    """One seed: an identifier `[seeds] works` names, or an entry of a `[seeds] bib` file."""

    label: str
    identifier: str = ""
    entry: BibEntry | None = None


def seeds(settings: Settings) -> list[Seed]:
    """Every seed of a corpus: the identifiers first, then the entries of each seed bibliography in file order.

    Parameters
    ----------
    settings : Settings
        The corpus's settings; `works` and `bib` are read.

    Returns
    -------
    list of Seed

    Raises
    ------
    PlanRefused
        `[seeds] works` names something that is not a `scheme:value` identifier.
    """
    out: list[Seed] = []
    for w in settings.works:
        if parse_id(w) is None:
            raise PlanRefused(
                f"[seeds] works names {w!r}, which is not a scheme:value identifier such as arxiv:1709.09864"
            )
        out.append(Seed(label=w, identifier=w))
    for path in settings.seed_bib_paths():
        for key, entry in parse_bib(_read(path)).items():
            out.append(Seed(label=key, entry=entry))
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def seed_texts(settings: Settings) -> list[str]:
    """The text of every seed bibliography, which the fingerprint is taken over along with the settings."""
    return [_read(p) for p in settings.seed_bib_paths()]


def fingerprint(settings: Settings, texts: list[str]) -> str:
    """What a plan was made from: the settings that decide the walk, and the seed bibliographies.

    The cap is not part of it, because raising or lowering the cap does not change which works the walk found; a fetch applies the current cap to the plan's order.
    """
    h = hashlib.sha256("\n".join(settings.fingerprint_material()).encode("utf-8"))
    for text in texts:
        h.update(b"\0" + text.encode("utf-8"))
    return "sha256:" + h.hexdigest()


@dataclass
class Clients:
    """The services a plan asks; tests pass fakes with the same methods."""

    zbmath: Any
    openalex: Any
    arxiv: Any
    resolver: Any

    def services(self) -> list[Service]:
        """The `Service` behind each client, for reporting what failed; a fake has none."""
        out: list[Service] = []
        for client in (self.zbmath, self.openalex, self.arxiv):
            s = getattr(client, "service", None)
            if isinstance(s, Service):
                out.append(s)
        for s in (getattr(self.resolver, "zb", None), getattr(self.resolver, "cr", None)):
            if isinstance(s, Service):
                out.append(s)
        return out


def default_clients(settings: Settings, *, refresh: bool = False) -> Clients:
    """The real services, caching under `cache/<service>/` and sharing the one host budget.

    Parameters
    ----------
    settings : Settings
        The corpus's settings; the cache directory, the Crossref contact and the OpenAlex key come from it.
    refresh : bool, default False
        Ask the services again instead of reading cached answers.

    Returns
    -------
    Clients
    """
    cache = settings.cache_dir
    return Clients(
        zbmath=Zbmath(Service("zbmath", cache, refresh=refresh)),
        openalex=OpenAlex(Service("openalex", cache, refresh=refresh), settings.openalex_key or ""),
        arxiv=Arxiv(Service("arxiv", cache, refresh=refresh)),
        resolver=Resolver(
            Service("zbmath-lookup", cache, refresh=refresh),
            Service("crossref", cache, refresh=refresh),
            contact=settings.contact,
        ),
    )


@dataclass
class Plan:
    """What a fetch would download, in what order, and what the walk found on the way."""

    record: int
    made: str
    fingerprint: str
    settings: dict[str, Any]
    subjects: list[str]
    categories: list[str]
    order: list[str]
    homes: dict[str, str]
    selected: list[str]
    counts: dict[str, int]
    estimate: dict[str, float]
    excluded: list[dict[str, Any]] = field(default_factory=list)
    unidentified: list[dict[str, Any]] = field(default_factory=list)
    bound: list[dict[str, Any]] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        """The plan as it is written and as `--json` prints it."""
        return {
            "record": self.record,
            "made": self.made,
            "fingerprint": self.fingerprint,
            "settings": self.settings,
            "subjects": self.subjects,
            "categories": self.categories,
            "order": self.order,
            "homes": self.homes,
            "selected": self.selected,
            "counts": self.counts,
            "estimate": self.estimate,
            "excluded": self.excluded,
            "unidentified": self.unidentified,
            "bound": self.bound,
        }

    def current(self, settings: Settings) -> bool:
        """Whether the fingerprint still matches the settings and the seed texts."""
        return self.fingerprint == fingerprint(settings, seed_texts(settings))

    def summary(self) -> str:
        """The plan as a person reads it before deciding to fetch."""
        c, e, s = self.counts, self.estimate, self.settings
        lines = [
            f"depth {s['depth']} · subjects {' '.join(self.subjects) or 'none'} · categories {' '.join(self.categories) or 'none'} · cap {s['cap']}",
            f"  {c['works']} works: {c['downloadable']} downloadable (arXiv {c['from_arxiv']}, open copies {c['open_copies']}), {c['metadata_only']} metadata only, {c['excluded']} excluded",
        ]
        outside = Counter(
            M.family(x["msc"][0]) for x in self.excluded if x["why"] == "outside the subjects" and x.get("msc")
        )
        if outside:
            lines.append(f"  excluded, outside the subjects: {_counted(dict(outside.most_common()), 8)}")
        uncategorised = Counter(x["category"] for x in self.excluded if x["why"] == "arXiv category not in categories")
        if uncategorised:
            lines.append(
                f"  excluded, no MSC code and a category not listed: {_counted(dict(uncategorised.most_common()), 8)}"
            )
        neither = sum(1 for x in self.excluded if x["why"] == "no MSC code and no arXiv category")
        if neither:
            lines.append(f"  excluded, no MSC code and no arXiv category: {neither}")
        if c["references_unknown"]:
            lines.append(
                f"  references not yet known for {c['references_unknown']} works (no index lists them; they are read from a source once it is fetched)"
            )
        size = f"{e['bytes'] / 1e9:.1f} GB" if e["bytes"] >= 1e9 else f"{e['bytes'] / 1e6:.0f} MB"
        lines.append(
            f"  to fetch: {c['selected'] - c['already_fetched']} ({c['already_fetched']} already on disk) · ~{size} · ~{e['seconds'] / 60:.0f} min · {c['lookups']} lookups made"
        )
        if c["over_cap"]:
            lines.append(
                f"  over the cap: {c['over_cap']} downloadable works would be left out; raise cap under [crawl] to include them"
            )
        lines.append(f"  bound by lookup: {c['bound']} · unidentified: {c['unidentified']}")
        lines.append("  the excluded, unidentified and bound works are listed in crawl/plan.json")
        return "\n".join(lines)


@dataclass
class Survey:
    """What the next level cites, counted, for an author choosing subjects and categories."""

    cited: dict[str, dict[str, int]]
    references: dict[str, dict[str, int]]
    counts: dict[str, int]

    def payload(self) -> dict[str, Any]:
        return {"cited": self.cited, "references": self.references, "counts": self.counts}

    def summary(self) -> str:
        """A survey as a person reads it before choosing subjects and categories."""
        c, cited, refs = self.counts, self.cited, self.references
        lines = [
            f"the {c['cited']} seed works, by primary MSC family: {_counted(cited['primary'])}",
            f"the {c['references']} works they cite, by primary MSC family: {_counted(refs['primary'])}",
            f"  by any of their codes: {_counted(refs['any'])}",
            f"  with no MSC code, by arXiv category: {_counted(refs['categories'])}",
            f"  with neither: {refs['neither'].get('works', 0)}",
            f"  not counted: {c['unidentified']} references not identified",
        ]
        if c["references_unknown"]:
            lines.append(
                f"  references not yet known for {c['references_unknown']} seed works (no index lists them; they are read from a source once it is fetched)"
            )
        lines.append(
            "set subjects = [...] under [crawl] to the MSC families to keep, and categories = [...] to the arXiv categories that keep a work with no MSC code, then plan"
        )
        return "\n".join(lines)


def _counted(counts: dict[str, int], limit: int = 12) -> str:
    return " · ".join(f"{k} {n}" for k, n in list(counts.items())[:limit]) or "none"


def _average(records: list[Record], kind: str, default: int) -> float:
    """The mean size of this kind of download among works already fetched, or the default before there are any."""
    sizes = [r.download["bytes"] for r in records if r.download.get("kind") == kind and r.download.get("bytes")]
    return sum(sizes) / len(sizes) if sizes else float(default)


def _text_query(text: str) -> Query:
    """A lookup for a reference known only as text: the whole text stands for the title, and the scoring reads a title and a surname out of it."""
    years = _YEAR.findall(text)
    return Query(text, (), years[-1] if years else "", text)


def artifacts(works: Path, record: Record) -> list[tuple[str, str]]:
    """The (kind, version-local) pairs already on disk for a work: an unpacked `src/`, a `paper.pdf`, under any version directory."""
    home = works / (record.home or home_of(record.ids[0]))
    out: list[tuple[str, str]] = []
    if not home.is_dir():
        return out
    for d in sorted(p for p in home.iterdir() if p.is_dir()):
        if (d / "src").is_dir():
            out.append(("source", d.name))
        if (d / "paper.pdf").is_file():
            out.append(("pdf", d.name))
    return out


class Planner:
    """One plan's walk. `log` receives a line per step, for a terminal to show progress."""

    def __init__(self, works: Path, clients: Clients, log: Callable[[str], None] = lambda _: None) -> None:
        self.works = works
        self.c = clients
        self.log = log
        self.alias: dict[str, Record] = {}  # every identifier of every work kept, to the one record of it
        self.excluded: list[dict[str, Any]] = []
        self._excluded_by: dict[str, dict[str, Any]] = {}
        self.unidentified: list[dict[str, Any]] = []
        self.bound: list[dict[str, Any]] = []
        self.lookups = 0
        self._queries: dict[str, Query] = {}

    # --- identification ---------------------------------------------------------------------------

    def _known(self, ids: list[str]) -> Record | None:
        return next((self.alias[norm(i)] for i in ids if norm(i) in self.alias), None)

    def _remember(self, record: Record) -> Record:
        """Index a work by each of its identifiers, merging it with any work already indexed under one of them; returns the record that remains.

        A work's identifiers grow as sources are read, so the same work reached by its arXiv number and by its DOI becomes one record once either source links the two. The shallower record remains, so a seed keeps its home.
        """
        while True:
            other = next(
                (self.alias[norm(i)] for i in record.ids if self.alias.get(norm(i), record) is not record), None
            )
            if other is None:
                break
            keep, gone = (record, other) if 0 < record.depth < other.depth else (other, record)
            keep.merge(gone)
            for i in gone.ids:
                self.alias[norm(i)] = keep
            record = keep
        for i in record.ids:
            self.alias[norm(i)] = record
        return record

    def _records(self) -> list[Record]:
        return list({id(w): w for w in self.alias.values()}.values())

    def _bind(self, q: Query, label: dict[str, Any]) -> list[str] | None:
        """The identifiers of a strong match, which becomes the work's identity, or None with the reason recorded.

        A match below STRONG leaves the work unidentified and counted, with the candidate kept as evidence: a wrong binding would put someone else's paper in the corpus under this work's name, and at depth every such work becomes a subtree.
        """
        self.lookups += 1
        try:
            found = self.c.resolver.candidates(q)
        except LookupRefused as exc:
            self.unidentified.append({**label, "why": str(exc)})
            return None
        strong = [c for c in found if c.strength == "strong"]
        if strong:
            self.bound.append({**label, **strong[0].evidence()})
            return ranked([strong[0].id, *strong[0].also])
        if found:
            self.unidentified.append(
                {
                    **label,
                    "why": "no strong match",
                    "candidate": found[0].id,
                    "confidence": found[0].confidence,
                    "matched": found[0].title,
                }
            )
        else:
            self.unidentified.append({**label, "why": "no match"})
        return None

    def depth_one(self, seed: Seed) -> Record | None:
        """A seed: by the identifier the settings or its entry state, or by a strong lookup match."""
        if seed.identifier:
            wid = parse_id(seed.identifier)
            record = Record(ids=[seed.identifier], depth=1, reached_by="declared", provenance="declared")
            record.home = wid.path if wid else home_of(seed.identifier)
            return record
        entry = seed.entry
        if entry is None:
            return None
        ids = declared(entry)
        if ids:
            record = Record(
                ids=ranked([str(i) for i in ids]),
                depth=1,
                reached_by="declared",
                provenance="declared",
                citekeys=[seed.label],
            )
            wid = primary(entry)
            record.home = wid.path if wid else home_of(record.ids[0])
            return record
        found = self._bind(query_for(entry), {"citekey": seed.label, "text": entry.fields.get("title", "")})
        if not found:
            return None
        record = Record(ids=found, depth=1, reached_by="lookup", provenance="resolved", citekeys=[seed.label])
        record.home = home_of(record.ids[0])
        return record

    def reference(self, ref: Reference) -> Record | None:
        """The work a reference names, identified by its identifier, zbMATH's document number, or a lookup of its text."""
        if ref.work:
            return Record(
                ids=[ref.work],
                msc=list(ref.msc),
                reached_by="index",
                provenance="declared",
                sources={"text": ref.text[:200]},
            )
        if ref.zbmath:
            try:
                zb = self.c.zbmath.by_document(ref.zbmath)
            except ServiceError:
                zb = None
            if zb and zb.ids:
                record = Record(
                    ids=ranked(zb.ids), reached_by="index", provenance="resolved", sources={"zbmath": zb.document}
                )
                record.fill(zb.title, zb.authors, str(zb.year or ""), zb.msc or ref.msc)
                return record
        if ref.text:
            q = self._queries.get(ref.text) or _text_query(ref.text)
            found = self._bind(q, {"text": ref.text[:200]})
            if found:
                return Record(
                    ids=found,
                    msc=list(ref.msc),
                    reached_by="lookup",
                    provenance="resolved",
                    sources={"text": ref.text[:200]},
                )
        return None

    # --- metadata -----------------------------------------------------------------------------------

    def enrich(self, record: Record, expand: bool) -> None:
        """Fill a work from zbMATH and OpenAlex, and, when it is to be expanded, collect its references from both and from its source if on disk."""
        zb = None
        for ident in list(record.ids):
            if norm(ident).partition(":")[0] in ("doi", "arxiv", "zbl"):
                try:
                    zb = self.c.zbmath.by_id(ident)
                except ServiceError:
                    zb = None
                if zb:
                    break
        if zb:
            record.add_ids(zb.ids)
            record.fill(zb.title, zb.authors, str(zb.year or ""), zb.msc)
            record.sources["zbmath"] = zb.document
        oa = None
        for ident in list(record.ids):
            if norm(ident).partition(":")[0] in ("doi", "arxiv"):
                try:
                    oa = self.c.openalex.by_id(ident)
                except ServiceError:
                    oa = None
                if oa:
                    break
        if oa:
            record.add_ids(oa.ids)
            record.fill(oa.title, oa.authors, str(oa.year or ""))
            record.open_pdf = record.open_pdf or oa.open_pdf
            record.sources["openalex"] = oa.openalex
        if not expand:
            return
        if zb and zb.references:
            record.add_references(zb.references)
        if oa and oa.references:
            try:
                listed = self.c.openalex.batch(oa.references)
            except ServiceError:
                listed = []
            for r in listed:
                if not r.ids and r.title and r.authors:
                    # OpenAlex knows the work but not an identifier: look it up by title, first author and year, not as bare text
                    self._queries[r.title] = Query(_plain(r.title), (_surname(r.authors[0]),), str(r.year or ""))
            record.add_references(
                [
                    Reference(
                        work=r.ids[0] if r.ids else "", text=r.title or "", identified_by="index" if r.ids else ""
                    )
                    for r in listed
                ]
            )
        for kind, local in artifacts(self.works, record):
            if kind != "source":
                continue
            refs = []
            for item in from_source(self.works / (record.home or home_of(record.ids[0])) / local / "src"):
                rid = f"arxiv:{item.arxiv}" if item.arxiv else f"doi:{item.doi}" if item.doi else ""
                if not rid:
                    self._queries[item.text] = bib_query(item)
                refs.append(
                    Reference(work=rid, citekey=item.key, text=item.text, identified_by="declared" if rid else "")
                )
            record.add_references(refs)

    def _classify(self, records: list[Record]) -> None:
        """Give each work an MSC code or an arXiv category where either is to be had, for the subject filter."""
        for w in records:
            if w.msc:
                continue
            for ident in list(w.ids):
                if norm(ident).partition(":")[0] not in ("doi", "arxiv", "zbl"):
                    continue
                try:
                    zb = self.c.zbmath.by_id(ident)
                except ServiceError:
                    zb = None
                if zb:
                    w.add_ids(zb.ids)
                    w.fill(zb.title, zb.authors, str(zb.year or ""), zb.msc)
                    w.sources["zbmath"] = zb.document
                    break
        for w in records:
            if w.msc or w.arxiv:
                continue
            # zbMATH has no record under this identifier, often a book cited by one edition's DOI: OpenAlex gives the title and authors, and perhaps an arXiv number, and zbMATH is then asked by title
            oa = None
            if w.doi:
                try:
                    oa = self.c.openalex.by_id(f"doi:{w.doi}")
                except ServiceError:
                    oa = None
            if oa:
                w.add_ids(oa.ids)
                w.fill(oa.title, oa.authors, str(oa.year or ""))
                w.open_pdf = w.open_pdf or oa.open_pdf
                w.sources["openalex"] = oa.openalex
            if w.title and w.authors:
                try:
                    zb = self.c.zbmath.by_title(w.title, w.authors, int(w.year) if w.year[:4].isdigit() else None)
                except ServiceError:
                    zb = None
                if zb:
                    w.add_ids(zb.ids)
                    w.fill(zb.title, zb.authors, str(zb.year or ""), zb.msc)
                    w.sources["zbmath"] = zb.document
        pending = [w.arxiv for w in records if not w.msc and w.arxiv and not w.arxiv_category]
        if pending:
            try:
                cats = self.c.arxiv.categories([a for a in pending if a])
            except ServiceError:
                cats = {}
            for w in records:
                if not w.msc and w.arxiv:
                    w.arxiv_category = w.arxiv_category or cats.get(norm("arxiv:" + w.arxiv).partition(":")[2], "")

    # --- the walk -----------------------------------------------------------------------------------

    def _seeds(self, found: list[Seed], expand: bool) -> list[Record]:
        """The seeds, identified and filled, with their references read when they are to be expanded."""
        self.log(f"identifying {len(found)} seeds")
        for seed in found:
            record = self.depth_one(seed)
            if record is not None:
                self._remember(record)
        for record in self._records():
            self.enrich(record, expand=expand)
            self._remember(record)
        return self._records()

    def _next(self, frontier: list[Record], depth: int) -> list[Record]:
        """The works the frontier cites that are not yet known, identified and classified, at `depth`."""
        self.log(f"depth {depth}: reading the references of {len(frontier)} works")
        fresh: list[Record] = []
        seen: dict[str, Record] = {}
        for i, w in enumerate(sorted(frontier, key=lambda x: (-len(x.reached_from), x.key)), 1):
            self.log(f"  {i}/{len(frontier)} {w.ids[0]}: {len(w.references)} references")
            own = {norm(x) for x in w.ids}
            for ref in w.references:
                cand = self.reference(ref)
                if cand is None or any(norm(x) in own for x in cand.ids):
                    continue
                target = self._known(cand.ids) or next((seen[norm(x)] for x in cand.ids if norm(x) in seen), None)
                if target is not None:
                    if w.key not in target.reached_from:
                        target.reached_from.append(w.key)
                    continue
                gone = next((self._excluded_by[norm(x)] for x in cand.ids if norm(x) in self._excluded_by), None)
                if gone is not None:
                    gone["cited_by"] += 1
                    continue
                cand.depth = depth
                cand.reached_from = [w.key]
                fresh.append(cand)
                for x in cand.ids:
                    seen[norm(x)] = cand
        self.log(f"depth {depth}: classifying {len(fresh)} works by subject")
        self._classify(fresh)
        return fresh

    def survey(self, found: list[Seed]) -> Survey:
        """Count what the seeds cite, by MSC family and arXiv category; nothing is kept and no record is written."""
        first = self._seeds(found, expand=True)
        fresh = self._next(first, 2)
        # classifying can show two references name one work, or a seed
        kept: dict[int, Record] = {}
        for c in fresh:
            if self._known(c.ids) is None:
                w = self._remember(c)
                kept[id(w)] = w
        references = [w for w in kept.values() if w.depth == 2]
        return Survey(
            cited={k: dict(v.most_common()) for k, v in M.tally([(w.msc, w.arxiv_category) for w in first]).items()},
            references={
                k: dict(v.most_common()) for k, v in M.tally([(w.msc, w.arxiv_category) for w in references]).items()
            },
            counts={
                "cited": len(first),
                "references": len(references),
                "bound": len(self.bound),
                "unidentified": len(self.unidentified),
                "references_unknown": sum(1 for w in first if not w.references_known),
                "lookups": self.lookups,
            },
        )

    def run(self, settings: Settings, found: list[Seed], texts: list[str]) -> Plan:
        """Walk to `settings.depth`, keeping the configured subjects, and write a record per work and the plan."""
        if settings.depth < 1:
            raise PlanRefused("[crawl] depth must be at least 1: depth 1 is the seeds themselves")
        subjects = M.families(settings.subjects)
        if settings.depth > 1 and not subjects:
            raise PlanRefused(
                'set subjects under [crawl] to MSC families such as ["14N"] to plan past depth 1; `weft survey` counts what the seeds cite'
            )
        frontier = self._seeds(found, expand=settings.depth > 1)
        for d in range(2, settings.depth + 1):
            fresh = self._next(frontier, d)
            kept: list[Record] = []
            for c in fresh:
                if self._known(c.ids) is None:  # classifying can show a reference names a work already kept
                    verdict = M.passes(c.msc, c.arxiv_category, subjects, settings.categories)
                    if not verdict:
                        why = (
                            "outside the subjects"
                            if c.msc
                            else "arXiv category not in categories"
                            if c.arxiv_category
                            else "no MSC code and no arXiv category"
                        )
                        out = {
                            "id": c.ids[0],
                            "title": c.title or c.sources.get("text", ""),
                            "depth": d,
                            "why": why,
                            "cited_by": len(c.reached_from),
                            "msc": c.msc[:3],
                            "category": c.arxiv_category,
                        }
                        self.excluded.append(out)
                        for x in c.ids:
                            self._excluded_by[norm(x)] = out
                        continue
                    c.home = home_of(c.ids[0])
                kept.append(self._remember(c))
            frontier = [w for w in {id(w): w for w in kept}.values() if w.depth == d]
            self.log(f"depth {d}: {len(frontier)} works kept, {len(fresh) - len(kept)} excluded")
            for c in frontier:
                self.enrich(c, expand=d < settings.depth)
                self._remember(c)
            frontier = [w for w in self._records() if w.depth == d]
        return self._finish(settings, subjects, texts)

    def _finish(self, settings: Settings, subjects: list[str], texts: list[str]) -> Plan:
        records = self._records()
        for w in records:
            # a citing work may have been merged since, under a key of higher rank
            keys = [self.alias[norm(k)].key if norm(k) in self.alias else k for k in w.reached_from]
            w.reached_from = [k for k in dict.fromkeys(keys) if k != w.key]
        ordered = sorted(records, key=lambda w: (w.depth, -len(w.reached_from), w.key))
        for w in ordered:
            previous = load_record(self.works / (w.home or home_of(w.ids[0])) / "work.json")
            if previous and previous.download:
                w.download = previous.download  # a re-plan keeps what was already fetched
                for v in previous.versions:
                    w.add_version(v)
            else:
                for kind, local in artifacts(self.works, w):
                    # bytes put there by an earlier crawl whose record is gone; they count against the cap the same way
                    w.download = w.download or {"kind": kind, "from": "", "at": "", "bytes": 0}
                    found = w.version_from_local(local)
                    found.has_source = kind == "source"
                    found.has_pdf = kind == "pdf"
                    w.add_version(found)
            save_record(self.works, w)
        downloadable = [w for w in ordered if w.downloadable]
        selected = downloadable[: max(0, settings.cap)]
        on_disk = [w for w in selected if w.downloaded]
        to_fetch = [w for w in selected if not w.downloaded]
        counts = {
            "works": len(ordered),
            "downloadable": len(downloadable),
            "from_arxiv": sum(1 for w in downloadable if w.downloadable == "source"),
            "open_copies": sum(1 for w in downloadable if w.downloadable == "pdf"),
            "metadata_only": len(ordered) - len(downloadable),
            "excluded": len(self.excluded),
            "references_unknown": sum(1 for w in ordered if w.depth < settings.depth and not w.references_known),
            "lookups": self.lookups,
            "bound": len(self.bound),
            "unidentified": len(self.unidentified),
            "selected": len(selected),
            "already_fetched": len(on_disk),
            "over_cap": max(0, len(downloadable) - max(0, settings.cap)),
        }
        sources = sum(1 for w in to_fetch if w.downloadable == "source")
        pdfs = len(to_fetch) - sources
        estimate = {
            "bytes": float(
                sources * _average(ordered, "source", AVG_SOURCE) + pdfs * _average(ordered, "pdf", AVG_PDF)
            ),
            "seconds": sources * SOURCE_SECONDS + pdfs * PDF_SECONDS,
        }
        return Plan(
            record=PLAN,
            made=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            fingerprint=fingerprint(settings, texts),
            settings=_settings_payload(settings),
            subjects=subjects,
            categories=sorted(set(settings.categories)),
            order=[w.key for w in ordered],
            homes={w.key: w.home for w in ordered},
            selected=[w.key for w in selected],
            counts=counts,
            estimate=estimate,
            excluded=sorted(self.excluded, key=lambda e: (e["depth"], -e["cited_by"], e["id"])),
            unidentified=self.unidentified,
            bound=self.bound,
        )


def _settings_payload(settings: Settings) -> dict[str, Any]:
    """The settings a plan was made from, as the plan records them."""
    return {
        "depth": settings.depth,
        "subjects": list(settings.subjects),
        "categories": list(settings.categories),
        "cap": settings.cap,
        "works": list(settings.works),
        "bib": list(settings.bib),
    }


def plan_path(settings: Settings) -> Path:
    return settings.crawl_dir / "plan.json"


def save_plan(settings: Settings, made: Plan) -> Path:
    """Write a plan into `crawl/plan.json`; returns the file."""
    path = plan_path(settings)
    write_atomic(path, json.dumps(made.payload(), indent=1, ensure_ascii=False) + "\n")
    return path


def load_plan(settings: Settings) -> Plan | None:
    """The corpus's plan, or None when there is none or it cannot be read."""
    try:
        data = json.loads(plan_path(settings).read_text(encoding="utf-8"))
        return Plan(**data)
    except (OSError, ValueError, TypeError):
        return None


def plan(settings: Settings, *, refresh: bool = False, clients: Clients | None = None) -> Plan:
    """Walk the citation network from the seeds to `[crawl] depth` and write the plan and a record per work.

    Parameters
    ----------
    settings : Settings
        The corpus's settings.
    refresh : bool, default False
        Ask the services again instead of reading cached answers.
    clients : Clients, optional
        The services to ask; default the real ones. Tests pass fakes, and no test touches the network.

    Returns
    -------
    Plan
        Written to `crawl/plan.json`. Nothing is downloaded.

    Raises
    ------
    PlanRefused
        A seed is not an identifier, the depth is below 1, or the depth is past 1 with no subjects configured.

    See Also
    --------
    survey : what the next level cites, for choosing those subjects.
    weft.crawl.fetch.fetch : downloading what this selected.
    """
    found = seeds(settings)
    used = clients if clients is not None else default_clients(settings, refresh=refresh)
    made = Planner(settings.works_dir, used).run(settings, found, seed_texts(settings))
    save_plan(settings, made)
    return made


def survey(settings: Settings, *, refresh: bool = False, clients: Clients | None = None) -> Survey:
    """Count what the seeds cite, by MSC family and arXiv category, so the subjects can be chosen from what is there.

    Parameters
    ----------
    settings : Settings
        The corpus's settings; the depth is not used, since a survey always looks one level past the seeds.
    refresh : bool, default False
        Ask the services again instead of reading cached answers.
    clients : Clients, optional
        The services to ask; default the real ones.

    Returns
    -------
    Survey
        No plan is written and no record is kept.

    See Also
    --------
    plan : the walk itself, once subjects are configured.
    """
    found = seeds(settings)
    used = clients if clients is not None else default_clients(settings, refresh=refresh)
    return Planner(settings.works_dir, used).survey(found)
