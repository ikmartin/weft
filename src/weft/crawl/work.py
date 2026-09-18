"""A crawled work's record, `works/<scheme>/<sanitised value>/work.json`.

One record per work, beside whatever was downloaded for it: what the work is, every identifier anything has for it, its subjects, its references, its versions, and how the crawl reached it. Several sources describe one work, so a record is built by merging, and identifiers are compared in one normal form.

**One work is one record under every identifier.** Keying on the first identifier seen recorded EGA I twice mid-walk, because sources add identifiers as the walk proceeds: the alias index in `plan.py` and `merge` here are what stop that.

The keys written are the corpus's contract with everything that reads it, so `payload` lists them explicitly rather than dumping the dataclass. `sources` and a reference's `zbmath` and `msc` are working notes of one walk and are not written.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from weft import model
from weft.files import write_atomic
from weft.identity import WorkId, sanitise

RECORD = 1
RANK = {"doi": 0, "arxiv": 1, "mr": 2, "zbl": 3, "work": 4}
_ARXIV_VERSION = re.compile(r"v\d+$")


def norm(ident: str) -> str:
    """One spelling per identifier: the scheme lowercased, a DOI's value lowercased (DOIs are case-insensitive), an arXiv number without its version (every version is the same work)."""
    scheme, _, value = ident.strip().partition(":")
    scheme = scheme.lower()
    value = value.strip()
    if scheme == "doi":
        value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.I).lower()
        m = re.match(r"^10\.48550/arxiv\.(.+)$", value)
        if m:
            return "arxiv:" + _ARXIV_VERSION.sub("", m.group(1))
    if scheme == "arxiv":
        value = _ARXIV_VERSION.sub("", value)
    return f"{scheme}:{value}"


def ranked(ids: list[str]) -> list[str]:
    """Identifiers without duplicates, most useful first: DOI, arXiv, MR, Zbl, synthetic."""
    seen: dict[str, str] = {}
    for i in ids:
        seen.setdefault(norm(i), i)
    return sorted(seen.values(), key=lambda i: RANK.get(i.partition(":")[0].lower(), 9))


def home_of(ident: str) -> str:
    """The directory a work is filed under, relative to `works/`: `arxiv/1709.09864`, `doi/10.1090_x`."""
    scheme, _, value = ident.partition(":")
    return WorkId(scheme.lower(), value).path


@dataclass
class Reference:
    """One entry of a work's reference list: the work it names where something identified it, the printed text otherwise.

    `zbmath` is zbMATH's own document number when zbMATH matched the entry without a DOI, which identifies the work exactly in one request rather than by a lookup; `msc` is what zbMATH says about its subject, which lets the subject filter run without asking at all. Neither is written to the record.
    """

    work: str = ""
    citekey: str = ""
    text: str = ""
    identified_by: str = ""  # declared | lookup | index
    zbmath: int | None = None
    msc: list[str] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return {"work": self.work, "citekey": self.citekey, "text": self.text, "identified_by": self.identified_by}


@dataclass
class Version:
    """An artifact of a work: `arxiv:1709.09864v3`, or the work key for something fetched as a PDF.

    A work has several artifacts, so a record holds a list. At M1 the list holds the version a download produced; extraction fills `method`, `numbering` and `extracted_at` later.
    """

    id: str
    has_source: bool = False
    has_pdf: bool = False
    method: str = ""
    numbering: str = ""
    extracted_at: str = ""

    work: str = ""  # the work key this is an artifact of, kept so a record round trip does not lose it

    @property
    def local(self) -> str:
        """The directory this version's artifacts live in, taken against the work it belongs to; its own value when that is unknown."""
        if not self.work:
            return sanitise(self.id.partition(":")[2] or self.id)
        return version_local(home_of(self.work), self.id)

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "has_source": self.has_source,
            "has_pdf": self.has_pdf,
            "method": self.method,
            "numbering": self.numbering,
            "extracted_at": self.extracted_at,
        }


@dataclass
class Record:
    """Everything the crawl knows about one work.

    `home` is the directory it is filed under, relative to `works/`. A seed keeps the identifier it was named by, version included, so its record sits where a reader would look for it.
    """

    ids: list[str]
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    msc: list[str] = field(default_factory=list)
    arxiv_category: str = ""
    arxiv_version: str = ""  # the version arXiv would serve, e.g. "v2": what a source download actually gets
    licence: str = ""
    depth: int = 0
    reached_from: list[str] = field(default_factory=list)
    reached_by: str = ""  # declared | lookup | index
    provenance: str = "declared"  # declared | resolved | asserted
    citekeys: list[str] = field(default_factory=list)
    references_known: bool = False
    references: list[Reference] = field(default_factory=list)
    versions: list[Version] = field(default_factory=list)
    download: dict[str, Any] = field(default_factory=dict)
    open_pdf: str = ""
    home: str = ""
    sources: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return norm(self.ids[0])

    @property
    def arxiv(self) -> str | None:
        """The arXiv identifier as held, version included where one was declared."""
        return next((i.partition(":")[2] for i in self.ids if i.lower().startswith("arxiv:")), None)

    @property
    def doi(self) -> str | None:
        return next((i.partition(":")[2] for i in self.ids if i.lower().startswith("doi:")), None)

    @property
    def downloadable(self) -> str:
        """`source` from arXiv, `pdf` from an open copy, or '' when only metadata is to be had."""
        return "source" if self.arxiv else "pdf" if self.open_pdf else ""

    @property
    def downloaded(self) -> bool:
        """Whether the bytes are on disk: a download record that is not a failure."""
        return bool(self.download) and not self.download.get("error")

    def version_for(self, kind: str) -> Version:
        """The version a download of this kind produces: the arXiv id with its `vN`, or the work key for a PDF."""
        if kind == "source" and self.arxiv:
            # the version arXiv serves, when it said which, so a result knows the artifact it was read from
            return Version(id=f"arxiv:{self.arxiv}{self.arxiv_version}", work=self.key, has_source=True)
        return Version(id=self.key, work=self.key, has_pdf=kind == "pdf")

    def version_from_local(self, local: str) -> Version:
        """The version whose artifacts sit in the directory `local` under this work's home: the inverse of `version_local`."""
        home = self.home or home_of(self.ids[0] if self.ids else self.key)
        hscheme, _, hvalue = home.partition("/")
        if local == "main":
            ident = f"{hscheme}:{hvalue}"
        elif "-" in local and local.split("-", 1)[0] in ("arxiv", "doi", "mr", "zbl", "work"):
            scheme, _, value = local.partition("-")
            ident = f"{scheme}:{value}"
        else:
            ident = f"{hscheme}:{hvalue}{local}"
        return Version(id=ident, work=self.key)

    def add_version(self, version: Version) -> Version:
        """Record a version, merging into one already held under the same id; returns the version held."""
        for v in self.versions:
            if v.id == version.id:
                v.has_source = v.has_source or version.has_source
                v.has_pdf = v.has_pdf or version.has_pdf
                v.method = v.method or version.method
                v.numbering = v.numbering or version.numbering
                v.extracted_at = v.extracted_at or version.extracted_at
                return v
        self.versions.append(version)
        return version

    def add_ids(self, more: list[str]) -> None:
        self.ids = ranked([*self.ids, *more])

    def add_references(self, more: list[Reference]) -> None:
        """Merge a source's reference list: one entry per identifier, and text entries only where no source resolved anything."""
        known = {norm(r.work) for r in self.references if r.work}
        for r in more:
            if r.work and norm(r.work) not in known:
                known.add(norm(r.work))
                self.references.append(r)
            elif not r.work and r.text and not any(x.text == r.text for x in self.references):
                self.references.append(r)
        if more:
            self.references_known = True

    def merge(self, other: Record) -> None:
        """Take in a record found to name this same work under another identifier."""
        self.add_ids(other.ids)
        self.fill(other.title, other.authors, other.year, other.msc)
        self.arxiv_category = self.arxiv_category or other.arxiv_category
        self.licence = self.licence or other.licence
        self.add_references(other.references)
        self.references_known = self.references_known or other.references_known
        for v in other.versions:
            self.add_version(v)
        self.depth = min(d for d in (self.depth, other.depth) if d) if self.depth or other.depth else 0
        self.reached_from += [k for k in other.reached_from if k not in self.reached_from]
        self.citekeys += [k for k in other.citekeys if k not in self.citekeys]
        self.reached_by = self.reached_by or other.reached_by
        # a binding is more than a default, so a resolved or asserted identity survives a merge with a declared one
        if self.provenance == "declared" and other.provenance != "declared":
            self.provenance = other.provenance
        self.open_pdf = self.open_pdf or other.open_pdf
        self.download = self.download or other.download
        for k, v in other.sources.items():
            self.sources.setdefault(k, v)
        self.home = self.home or other.home

    def fill(
        self, title: str = "", authors: list[str] | None = None, year: str = "", msc: list[str] | None = None
    ) -> None:
        """Take what a source knows that the record does not."""
        self.title = self.title or title
        self.authors = self.authors or list(authors or [])
        self.year = self.year or year
        for code in msc or []:
            if code not in self.msc:
                self.msc.append(code)

    def payload(self) -> dict[str, Any]:
        """The record as it is written: the corpus's contract with everything that reads `works/`."""
        return {
            "record": RECORD,
            "key": self.key,
            "ids": list(self.ids),
            "title": self.title,
            "authors": list(self.authors),
            "year": self.year,
            "msc": list(self.msc),
            "arxiv_category": self.arxiv_category,
            "arxiv_version": self.arxiv_version,
            "licence": self.licence,
            "depth": self.depth,
            "reached_from": list(self.reached_from),
            "reached_by": self.reached_by,
            "provenance": self.provenance,
            "citekeys": list(self.citekeys),
            "references_known": self.references_known,
            "references": [r.payload() for r in self.references],
            "versions": [v.payload() for v in self.versions],
            "download": dict(self.download),
            "open_pdf": self.open_pdf,
            "home": self.home,
        }

    def as_work(self) -> model.Work:
        """The domain object the index holds, which knows nothing of references or downloads."""
        return model.Work(
            key=self.key,
            ids=list(self.ids),
            title=self.title,
            authors=list(self.authors),
            year=self.year,
            msc=list(self.msc),
            arxiv_category=self.arxiv_category,
            licence=self.licence,
            depth=self.depth,
            reached_from=list(self.reached_from),
            reached_by=self.reached_by,
            provenance=self.provenance,
            citekeys=list(self.citekeys),
        )

    def as_versions(self) -> list[model.Version]:
        """The domain objects for this work's versions."""
        return [
            model.Version(
                id=v.id,
                work=self.key,
                has_source=v.has_source,
                has_pdf=v.has_pdf,
                method=v.method,
                numbering=v.numbering,
                extracted_at=v.extracted_at,
            )
            for v in self.versions
        ]


def record_path(works: Path, record: Record) -> Path:
    """Where a record is written: `works/<home>/work.json`, with the home filled in from its first identifier."""
    record.home = record.home or home_of(record.ids[0])
    return works / record.home / "work.json"


def version_local(home: str, ident: str) -> str:
    """The directory a version's artifacts live in, under the work's home: what the identifier adds to the home, or `main` when it adds nothing.

    The home already names the work, so `arxiv:1709.09864` under `arxiv/1709.09864` is `main` and its v2 is `v2`; an artifact of another scheme keeps its own name, which is how a source fetched from arXiv sits under a work homed by its journal DOI.
    """
    scheme, _, value = ident.partition(":")
    local = sanitise(value)
    hscheme, _, hvalue = home.partition("/")
    if scheme == hscheme and local.startswith(hvalue):
        return local[len(hvalue) :] or "main"
    return f"{scheme}-{local}"


def version_dir(works: Path, record: Record, version: Version) -> Path:
    """Where a version's artifacts live: `works/<home>/<version-local>/`."""
    home = record.home or home_of(record.ids[0])
    return works / home / version_local(home, version.id)


def save(works: Path, record: Record) -> Path:
    """Write a work's record into its home under `works`; returns the file.

    Parameters
    ----------
    works : Path
        The corpus's `works/` directory.
    record : Record
        The record to write; its `home` is filled in if empty.

    Returns
    -------
    Path
        The record file. Written whole or not at all, because a fetch killed mid-write must not leave a record that no longer loads.
    """
    path = record_path(works, record)
    write_atomic(path, json.dumps(record.payload(), indent=1, ensure_ascii=False) + "\n")
    return path


def load(path: Path) -> Record | None:
    """A work's record, or None when the file is not one weft can read."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("ids"):
            return None
        return Record(
            ids=[str(i) for i in data["ids"]],
            title=str(data.get("title", "")),
            authors=[str(a) for a in data.get("authors", [])],
            year=str(data.get("year", "")),
            msc=[str(m) for m in data.get("msc", [])],
            arxiv_category=str(data.get("arxiv_category", "")),
            arxiv_version=str(data.get("arxiv_version", "")),
            licence=str(data.get("licence", "")),
            depth=int(data.get("depth", 0)),
            reached_from=[str(k) for k in data.get("reached_from", [])],
            reached_by=str(data.get("reached_by", "")),
            provenance=str(data.get("provenance", "declared")),
            citekeys=[str(k) for k in data.get("citekeys", [])],
            references_known=bool(data.get("references_known", False)),
            references=[
                Reference(
                    work=str(r.get("work", "")),
                    citekey=str(r.get("citekey", "")),
                    text=str(r.get("text", "")),
                    identified_by=str(r.get("identified_by", "")),
                )
                for r in data.get("references", [])
            ],
            versions=[
                Version(
                    id=str(v["id"]),
                    work=str(data.get("key", "")),
                    has_source=bool(v.get("has_source", False)),
                    has_pdf=bool(v.get("has_pdf", False)),
                    method=str(v.get("method", "")),
                    numbering=str(v.get("numbering", "")),
                    extracted_at=str(v.get("extracted_at", "")),
                )
                for v in data.get("versions", [])
                if v.get("id")
            ],
            download=dict(data.get("download") or {}),
            open_pdf=str(data.get("open_pdf", "")),
            home=str(data.get("home", "")),
        )
    except (OSError, ValueError, TypeError, KeyError):
        return None


def load_all(works: Path) -> dict[str, Record]:
    """Every record under `works/`, by normal key.

    Found by walking rather than by a fixed depth, because a home is `<scheme>/<value>` and a value need not be one path component. Anything inside an unpacked source is somebody else's file and is passed over.
    """
    out: dict[str, Record] = {}
    for path in sorted(works.rglob("work.json")):
        if "src" in path.relative_to(works).parts:
            continue
        w = load(path)
        if w and w.ids:
            out[w.key] = w
    return out
