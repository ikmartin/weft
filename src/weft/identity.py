"""The global identity of a work: the scheme and value everything in the corpus keys on.

A citekey names a work inside one bibliography and changes whenever its author re-exports it; a global identifier names the same work on two machines, which is what lets a reference found in one paper and a seed named in the settings turn out to be one record. A work that states no identifier gets a deterministic `work:<hash>` over its folded surnames, title and year, so two corpora can still merge on a book that has no DOI.

An arXiv DOI (`10.48550/arxiv.X`) is normalised to `arxiv:X`: one artifact, one directory, however a bibliography happened to record it.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from weft.bib import BibEntry

# Resolution order. A DOI is preferred because it names the published work, which is what a bibliography cites; an eprint names a specific preprint, which is what weft can actually fetch. Both are kept when both exist: they are different facts, not competing answers.
SCHEMES = ("doi", "arxiv", "mr", "zbl", "work")
DISPLAY = {"arxiv": "arXiv", "doi": "doi", "mr": "MR", "zbl": "Zbl", "work": "work"}

_ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf|e-print)/([^\s?#]+)", re.I)
_DOI_URL = re.compile(r"(?:doi\.org/|dx\.doi\.org/)(10\.[^\s?#]+)", re.I)
_DOI_BARE = re.compile(r"^10\.\d{4,9}/\S+$")
_ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(\S+)$", re.I)
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class WorkId:
    """One global identifier for a work: its scheme, its value, and where the binding came from."""

    scheme: str
    value: str
    provenance: str = "declared"

    def __str__(self) -> str:
        return f"{DISPLAY.get(self.scheme, self.scheme)}:{self.value}"

    @property
    def path(self) -> str:
        """The corpus directory for this work, as `<scheme>/<sanitised value>`.

        The scheme is a directory of its own so that sanitisation rules stay local to a scheme and two schemes cannot collide on one string. Nobody navigates here by hand, so the value is mangled for safety rather than for looks.
        """
        return f"{self.scheme}/{sanitise(self.value)}"

    @property
    def preprint(self) -> bool:
        """Whether an artifact can be fetched under this identifier, which at M1 means arXiv."""
        return self.scheme == "arxiv"


def sanitise(value: str) -> str:
    """A path-safe form of an identifier's value: DOIs carry slashes and old arXiv ids carry them too.

    One-way. The identifier is recorded in the work's record, so nothing reads it back out of a path. Two values differing only where they are mangled would collide; no real DOI pair does.
    """
    return _UNSAFE.sub("_", value.strip())


def parse(text: str) -> WorkId | None:
    """A `scheme:value` identifier as the settings or a record write it, or None when it is not one."""
    raw = text.strip()
    if ":" not in raw:
        return None
    scheme, _, value = raw.partition(":")
    scheme = scheme.strip().lower()
    if scheme not in SCHEMES or not value.strip():
        return None
    return WorkId(scheme, value.strip())


def _eprint(entry: BibEntry) -> str | None:
    """The arXiv identifier of an entry, from `eprint` when the archive is arXiv or unstated."""
    e = entry.eprint
    if not e:
        return None
    kind = (entry.fields.get("eprinttype") or entry.fields.get("archiveprefix") or "arxiv").strip().lower()
    if kind != "arxiv":
        return None
    e = re.sub(r"^arxiv:", "", e.strip(), flags=re.I)
    if e and entry.version and not re.search(r"v\d+$", e):
        e = f"{e}v{entry.version}"
    return e or None


def _from_url(entry: BibEntry) -> WorkId | None:
    """An identifier recovered from a `url` field, for entries that carry the link but not the field."""
    url = entry.fields.get("url", "")
    if m := _ARXIV_URL.search(url):
        return WorkId("arxiv", m.group(1), "declared")
    if m := _DOI_URL.search(url):
        return WorkId("doi", m.group(1), "declared")
    return None


def declared(entry: BibEntry) -> list[WorkId]:
    """Every global identifier the entry states, in resolution order, most authoritative first.

    Parameters
    ----------
    entry : BibEntry
        The entry to read.

    Returns
    -------
    list of WorkId
        Both a DOI and an eprint when the entry has both, since they name different artifacts of one work; empty when the entry states none.

    See Also
    --------
    identify : the same, with a synthetic identifier when nothing is declared.
    """
    out: list[WorkId] = []
    doi = entry.fields.get("doi", "").strip()
    if doi and (_DOI_BARE.match(doi) or doi.startswith("10.")):
        # arXiv mints its own DOIs under 10.48550, so such a DOI names a preprint and not a published article; normalising it means one artifact has one directory however the bibliography recorded it
        if m := _ARXIV_DOI.match(doi):
            out.append(WorkId("arxiv", m.group(1), "declared"))
        else:
            out.append(WorkId("doi", doi, "declared"))
    if (e := _eprint(entry)) and not any(w.scheme == "arxiv" for w in out):
        out.append(WorkId("arxiv", e, "declared"))
    for name, scheme in (("mrnumber", "mr"), ("zbl", "zbl"), ("zblnumber", "zbl")):
        v = entry.fields.get(name, "").strip()
        if v and not any(w.scheme == scheme for w in out):
            out.append(WorkId(scheme, v, "declared"))
    if not out and (w := _from_url(entry)):
        out.append(w)
    return out


def _normalised(entry: BibEntry) -> str:
    """The author surnames, title and year of an entry, flattened so two machines agree byte for byte."""
    author = entry.fields.get("author", "")
    surnames = []
    for part in re.split(r"\s+and\s+", author):
        part = part.strip()
        if not part:
            continue
        surnames.append(part.split(",")[0] if "," in part else part.split()[-1] if part.split() else "")
    title = entry.fields.get("title", "")
    year = entry.fields.get("year", "")
    raw = "|".join(["+".join(surnames), title, year])
    folded = unicodedata.normalize("NFKD", raw)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9|+]+", "", folded.lower())


def synthetic(entry: BibEntry) -> WorkId:
    """A deterministic `work:<hash>` for an entry that states no identifier.

    Determinism across machines is the point: it is what lets two corpora merge on a book that has no DOI. Derived from the entry, so nothing needs storing.
    """
    digest = hashlib.sha256(_normalised(entry).encode("utf-8")).hexdigest()[:8]
    return WorkId("work", digest, "declared")


def identify(entry: BibEntry | None) -> list[WorkId]:
    """Every global identifier for a bibliography entry, most authoritative first.

    Parameters
    ----------
    entry : BibEntry or None
        The entry to identify; None yields an empty list, since a work with no entry has nothing to identify it by.

    Returns
    -------
    list of WorkId
        The declared identifiers in resolution order, or a single deterministic `work:<hash>` when the entry declares none. Never empty for a real entry, so a work always has somewhere to be filed.

    See Also
    --------
    declared : only what the entry states, without the synthetic fallback.
    """
    if entry is None:
        return []
    found = declared(entry)
    return found if found else [synthetic(entry)]


def primary(entry: BibEntry | None) -> WorkId | None:
    """The identifier a work's directory is named by: the first of `identify`."""
    ids = identify(entry)
    return ids[0] if ids else None
