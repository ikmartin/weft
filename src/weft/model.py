"""The corpus's domain model: a work has versions, a version has results, and results are linked where the papers say so.

Results belong to a version rather than to a work, because numbering is a property of an artifact and because versions differ in content: a published thesis can drop a result its preprint states. "The same result in two versions" is a mapping with evidence, never an identity.

Nothing here knows about SQL, HTTP or the filesystem. Files under `works/` are the truth; the index is derived from them and can be thrown away.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# How a work entered the corpus, and how sure the identification is.
PROVENANCE = ("declared", "resolved", "asserted")
# How a version's results were read.
METHODS = ("latex", "pdf", "manual")
# Why an edge exists. `locator` and `unspecified` are what a paper states; nothing else is inferred in 0.1.
ORIGINS = ("internal", "locator", "unspecified")


@dataclass(frozen=True)
class Key:
    """A result's global key: `arxiv:1709.09864v3#thm-4.1`, a version and a paper-local part."""

    version: str
    local: str

    def __str__(self) -> str:
        return f"{self.version}#{self.local}"

    @classmethod
    def parse(cls, text: str) -> Key:
        version, _, local = text.partition("#")
        if not version or not local:
            raise ValueError(f"{text!r} is not a result key (want `version#local`)")
        return cls(version, local)


@dataclass
class Work:
    """A scholarly item: one paper or one book, under every identifier anything has for it."""

    key: str  # the ranked-first identifier, e.g. "arxiv:1709.09864"
    ids: list[str] = field(default_factory=list)
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    msc: list[str] = field(default_factory=list)
    arxiv_category: str = ""
    licence: str = ""
    depth: int = 0
    reached_from: list[str] = field(default_factory=list)  # work keys that cite this one
    reached_by: str = ""  # declared | lookup | index
    provenance: str = "declared"
    citekeys: list[str] = field(default_factory=list)  # what the seeds call it, where they do


@dataclass
class Version:
    """An artifact of a work: `arxiv:1709.09864v3`, or a published DOI. Carries what was read and how."""

    id: str
    work: str
    has_source: bool = False
    has_pdf: bool = False
    method: str = ""  # one of METHODS, once results have been read
    numbering: str = ""  # "compiled" or "emulated"
    extracted_at: str = ""


@dataclass
class Result:
    """One statement of one version, with its proof when the paper gives one and the corpus keeps it."""

    version: str
    local: str  # "thm-4.1"
    taxon: str  # "Theorem"
    number: str = ""
    title: str = ""
    statement: str = ""  # LaTeX, verbatim
    proof: str = ""  # LaTeX, verbatim; empty when the paper gives none or the policy drops it
    aliases: list[str] = field(default_factory=list)  # the paper's own labels
    page: str = ""

    @property
    def key(self) -> Key:
        return Key(self.version, self.local)


@dataclass
class Edge:
    """A dependency the papers state: result to result, or result to a whole work when the citation says no more."""

    src: str  # a result key
    to: str  # a result key, or a work key when origin is "unspecified"
    origin: str  # one of ORIGINS
    confidence: float = 1.0
    evidence: str = ""  # the locator as printed, or the citing file and offset


@dataclass
class Reference:
    """A version's bibliography entry, as printed and as identified."""

    version: str
    work: str  # the identified work key, "" while unidentified
    citekey: str = ""  # as the citing paper prints it
    text: str = ""  # the display text of the \\bibitem or entry
    identified_by: str = ""  # declared | lookup | index


@dataclass
class SameAs:
    """A result of one version and a result of another taken to be the same statement."""

    left: str  # a result key
    right: str  # a result key
    confidence: float = 1.0
    evidence: str = ""
