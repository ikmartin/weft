"""Writing one version's extraction into the corpus: `digest.tex`, `results.json`, and the version entry of `work.json`.

Files are truth and the index is derived from them (the plan's §4), so everything an extraction found is written here and nothing is kept only in a database. `results.json` is the shape `weft.store.rebuild` reads: the same results as the digest, as data, so the index's source is not a LaTeX parser.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from weft.crawl.work import Record, Version, save, version_dir
from weft.extract.extract import Extraction, Statement
from weft.files import write_atomic

RESULTS_NAME = "results.json"
DIGEST_NAME = "digest.tex"
METHOD = "latex"


@dataclass(frozen=True)
class Written:
    """Where one version's extraction landed."""

    digest: Path
    results: Path
    record: Path


_LABEL = re.compile(r"\\label\s*\{[^}]*\}[ \t]*\n?")


def without_labels(text: str) -> str:
    """A statement or proof as data: the same text with its `\\label` commands taken out.

    The digest keeps them, because a `\\ref` elsewhere in the file has to land somewhere, and they are prefixed there so two papers' `eq:main` can sit in one bundle. The index must not: a label carrying the version's prefix would make one statement two, and telling a published article's theorem from its preprint's is exactly the comparison the version model exists for. Nothing is lost -- the paper's own labels are the `aliases` field.
    """
    return _LABEL.sub("", text).strip("\n")


def result_payload(st: Statement) -> dict[str, Any]:
    """One result as `results.json` carries it, and as `weft.store.rebuild` reads it back.

    The keys are the corpus's contract with the index: `local` is the paper-local part of the key, `aliases` are the paper's own labels as the paper wrote them, and `page` is a string because a version that was never compiled has none.
    """
    return {
        "local": st.local,
        "taxon": st.taxon,
        "number": st.number,
        "title": st.title,
        "statement": without_labels(st.statement),
        "proof": without_labels(st.proof_text),
        "aliases": list(st.aliases),
        "page": st.page,
    }


def results_payload(version: str, extraction: Extraction) -> dict[str, Any]:
    """One version's extraction output as a whole.

    `edges` is written empty: the two cross-paper cases a paper states are read in M3, and an empty list is the honest record that this extraction looked for none, rather than an absent key a reader has to guess about.
    """
    return {
        "version": version,
        "method": METHOD,
        "numbering": extraction.report.numbering,
        "results": [result_payload(st) for st in extraction.statements],
        "edges": [],
    }


def write_version(works: Path, record: Record, version: Version, extraction: Extraction, *, at: str) -> Written:
    """Write the digest, the results and the updated record for one version.

    Parameters
    ----------
    works : Path
        The corpus's `works/` directory.
    record : Record
        The work's record; its version entry is updated and the whole record is rewritten through its own save path.
    version : Version
        The version extracted; it must be one of `record.versions`, since that is the entry that is updated.
    extraction : Extraction
        What the extractor produced.
    at : str
        The ISO 8601 timestamp recorded as `extracted_at`.

    Returns
    -------
    Written
        The three paths, each written whole or not at all.
    """
    where = version_dir(works, record, version)
    digest = where / DIGEST_NAME
    results = where / RESULTS_NAME
    write_atomic(digest, extraction.digest)
    write_atomic(results, json.dumps(results_payload(version.id, extraction), indent=1, ensure_ascii=False) + "\n")
    held = record.add_version(version)
    held.method = METHOD
    held.numbering = extraction.report.numbering
    held.extracted_at = at
    return Written(digest=digest, results=results, record=save(works, record))
