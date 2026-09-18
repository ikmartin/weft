"""Extraction, per version of a work: read the unpacked LaTeX source and write the statements and proofs beside it.

Results belong to a version and not to a work, so this is the unit: one directory of somebody's e-print, one `digest.tex` and one `results.json` next to it, one version entry of `work.json` updated. A work whose two versions differ -- a published article that drops a lemma its preprint states, and renumbers what follows -- is two extractions that disagree, which is the case the data model exists for.

Numbering comes from the paper's own compile when an `.aux` is already beside the source, and from counter emulation otherwise, because a corpus is a LaTeX run per work and most of those runs would fail on somebody else's document class. `--compile` buys the real numbers for one work at the price of running latexmk over it.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from weft import __version__
from weft.config import Settings
from weft.crawl.work import Record, Version, load_all, norm, version_dir
from weft.extract.extract import Extraction, Provenance, Refused, extract, find_main, read_paper, slug_prefix
from weft.extract.write import DIGEST_NAME, RESULTS_NAME, write_version
from weft.tex.aux import AuxNumber, parse_aux, read_numbers

log = logging.getLogger(__name__)

SOURCE_DIR = "src"


def now() -> str:
    """The extraction timestamp, ISO 8601. `WEFT_FIXED_TIME` overrides it, so a test can compare bytes."""
    fixed = os.environ.get("WEFT_FIXED_TIME")
    if fixed:
        return fixed
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class VersionOutcome:
    """What became of one version: extracted, already done, or refused with the reason."""

    work: str
    version: str
    status: str  # extracted | done | refused
    results: int = 0
    proofs: int = 0
    numbering: str = ""
    main: str = ""
    reason: str = ""
    taxa: dict[str, str] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "work": self.work,
            "version": self.version,
            "status": self.status,
            "results": self.results,
            "proofs": self.proofs,
            "numbering": self.numbering,
            "main": self.main,
        }
        if self.reason:
            out["reason"] = self.reason
        return out


@dataclass
class ExtractReport:
    """Every version one `weft extract` run looked at."""

    proofs: str = "verbatim"
    outcomes: list[VersionOutcome] = field(default_factory=list)

    @property
    def extracted(self) -> list[VersionOutcome]:
        return [o for o in self.outcomes if o.status == "extracted"]

    @property
    def refused(self) -> list[VersionOutcome]:
        return [o for o in self.outcomes if o.status == "refused"]

    def payload(self) -> dict[str, Any]:
        return {
            "proofs": self.proofs,
            "versions": len(self.outcomes),
            "extracted": len(self.extracted),
            "refused": len(self.refused),
            "results": sum(o.results for o in self.extracted),
            "proofs_kept": sum(o.proofs for o in self.extracted),
            "outcomes": [o.payload() for o in self.outcomes],
        }

    def summary(self) -> str:
        if not self.outcomes:
            return "Nothing to extract: no version has a source that is not already extracted."
        lines = [
            f"{len(self.extracted)} of {len(self.outcomes)} versions extracted, "
            f"{sum(o.results for o in self.extracted)} results, "
            f"{sum(o.proofs for o in self.extracted)} proofs kept ({self.proofs})"
        ]
        for o in self.outcomes:
            if o.status == "extracted":
                lines.append(f"  {o.version}: {o.results} results, {o.proofs} proofs, {o.numbering}, from {o.main}")
            elif o.status == "done":
                lines.append(f"  {o.version}: already extracted; --all to do it again")
            else:
                lines.append(f"  {o.version}: refused, {o.reason}")
        return "\n".join(lines)


def source_dir(settings: Settings, record: Record, version: Version) -> Path:
    """Where a version's unpacked source sits: `works/<home>/<version-local>/src/`."""
    return version_dir(settings.works_dir, record, version) / SOURCE_DIR


def declared_prefix(settings: Settings, record: Record, version: Version) -> str:
    """The id prefix the record names for this version, or '' when it names none.

    A prefix is declared rather than derived (§2.2), so a record may carry one under `prefix`, on the version entry or on the work; nothing writes it, and a person editing a record is who it is for. Without one, the prefix is the version identifier slugged.
    """
    path = settings.works_dir / (record.home or "") / "work.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(raw, dict):
        return ""
    for entry in raw.get("versions", []):
        if isinstance(entry, dict) and entry.get("id") == version.id and entry.get("prefix"):
            return slug_prefix(str(entry["prefix"]))
    return slug_prefix(str(raw["prefix"])) if isinstance(raw.get("prefix"), str) and raw["prefix"] else ""


def provenance_for(settings: Settings, record: Record, version: Version, *, proofs: str) -> Provenance:
    """What this version's digest header will say (docs/specs/digest.md §2).

    `digest:` carries the work's global identifier, which is §2.1's corpus case: the citekeys a record holds are what *other* papers call this work, and one of them naming this work in its own digest while the same string names something else in the citations inside its proofs would make `{key}` mean two works in one file. `extracted-from:` is always the version, since that is the artifact the statements and their numbers were read from, and `published-as:` names the work a bibliography cites when that is a different artifact -- an arXiv DOI is the same artifact under another spelling, so it is not one.
    """
    published = f"doi:{record.doi}" if record.doi else ""
    if published and norm(published) == norm(version.id):
        published = ""
    return Provenance(
        digest=record.key,
        prefix=declared_prefix(settings, record, version) or slug_prefix(version.id),
        extracted_from=version.id,
        published_as=published,
        proofs=proofs,
        created=now()[:10],
        tool=f"weft {__version__}",
    )


def numbers_for(paper_dir: Path, main: str, *, compile: bool, engine: str | None = None) -> dict[str, AuxNumber]:
    """The paper's own numbers: the `.aux` beside the source, or a latexmk run when one is asked for and there is none."""
    aux = read_numbers(paper_dir, main)
    if aux or not compile:
        return aux
    from weft.tex.runner import compile_tex

    with tempfile.TemporaryDirectory(prefix="weft-extract-") as tmp:
        res = compile_tex(paper_dir, main, Path(tmp), engine or "pdflatex")
        if res.aux is not None and res.aux.exists():
            return parse_aux(res.aux.read_text(encoding="utf-8", errors="replace"))
        log.warning("%s: no .aux from latexmk (%s); numbering is emulated", paper_dir, res.first_error)
    return {}


def extract_version(
    settings: Settings,
    record: Record,
    version: Version,
    *,
    proofs: str = "verbatim",
    compile: bool = False,
    engine: str | None = None,
) -> Extraction:
    """Extract one version of one work, writing `digest.tex`, `results.json` and the record's version entry.

    Parameters
    ----------
    settings : Settings
        The corpus.
    record : Record
        The work's record, as loaded from `works/<home>/work.json`; it is written back with the version entry updated.
    version : Version
        The version to extract; its source must be unpacked under `<version>/src/`.
    proofs : {'verbatim', 'none'}, default 'verbatim'
        Whether proofs are kept. 'verbatim' is the corpus default; 'none' is what a paper's own quilt writes (§2.6).
    compile : bool, default False
        Run latexmk for the real numbers when no `.aux` is already beside the source.
    engine : str, optional
        The engine for that run; the paper's `% !TEX program` or pdflatex by default.

    Returns
    -------
    Extraction
        The digest text, the statements and the report.

    Raises
    ------
    Refused
        When the source is missing, or no main file can be chosen; the message says which.

    See Also
    --------
    extract_corpus : the same over every version of a corpus.
    """
    src = source_dir(settings, record, version)
    if not src.is_dir():
        raise Refused(f"no source unpacked at {src}")
    main = find_main(src)
    paper = read_paper(src, main)
    aux = numbers_for(src, main, compile=compile, engine=engine or paper.closure.engine)
    made = extract(paper, provenance_for(settings, record, version, proofs=proofs), aux=aux)
    write_version(settings.works_dir, record, version, made, at=now())
    return made


def sourced(settings: Settings, idents: list[str] | tuple[str, ...] = ()) -> Iterator[tuple[Record, Version]]:
    """Every version of the corpus whose source is unpacked, restricted to the named works.

    Parameters
    ----------
    settings : Settings
        The corpus.
    idents : sequence of str
        Works to restrict to, by any identifier they hold; empty means the whole corpus.

    Yields
    ------
    tuple[Record, Version]
        In corpus order, a record and one of its versions. A version with no source is not yielded at all: a work reached only as metadata is in the citation graph and absent from the result graph, which is a fact about the corpus and not a failure of extraction.
    """
    wanted = {norm(i) for i in idents}
    for record in load_all(settings.works_dir).values():
        if wanted and not ({norm(i) for i in record.ids} | {record.key}) & wanted:
            continue
        for version in record.versions:
            if (version_dir(settings.works_dir, record, version) / SOURCE_DIR).is_dir():
                yield record, version


def extract_corpus(
    settings: Settings,
    idents: list[str] | tuple[str, ...] = (),
    *,
    proofs: str = "verbatim",
    redo: bool = False,
    compile: bool = False,
) -> ExtractReport:
    """Extract every version of the corpus that has a source and no results, or the named works' versions.

    Parameters
    ----------
    settings : Settings
        The corpus.
    idents : sequence of str
        Works to restrict to, by any identifier they hold; empty means every work.
    proofs : {'verbatim', 'none'}, default 'verbatim'
        Whether proofs are kept.
    redo : bool, default False
        Re-extract versions that already have a `results.json`.
    compile : bool, default False
        Run latexmk where no `.aux` is beside the source.

    Returns
    -------
    ExtractReport
        One outcome per version looked at: extracted, already done, or refused with the reason. One paper weft cannot read costs that paper and not the run.

    See Also
    --------
    extract_version : one version, with the exception rather than a report.
    """
    report = ExtractReport(proofs=proofs)
    for record, version in sourced(settings, idents):
        where = version_dir(settings.works_dir, record, version)
        if (where / RESULTS_NAME).is_file() and not redo:
            report.outcomes.append(VersionOutcome(record.key, version.id, "done"))
            continue
        try:
            made = extract_version(settings, record, version, proofs=proofs, compile=compile)
        except Refused as exc:
            report.outcomes.append(VersionOutcome(record.key, version.id, "refused", reason=str(exc)))
            continue
        except (
            OSError,
            ValueError,
            RecursionError,
        ) as exc:  # somebody else's LaTeX, read on a machine that is not theirs
            log.warning("%s: %s", version.id, exc)
            report.outcomes.append(
                VersionOutcome(record.key, version.id, "refused", reason=f"{type(exc).__name__}: {exc}")
            )
            continue
        report.outcomes.append(
            VersionOutcome(
                work=record.key,
                version=version.id,
                status="extracted",
                results=len(made.statements),
                proofs=made.report.proofs_kept,
                numbering=made.report.numbering,
                main=made.report.main,
                taxa=dict(made.report.taxa),
            )
        )
    return report


__all__ = [
    "DIGEST_NAME",
    "RESULTS_NAME",
    "ExtractReport",
    "Extraction",
    "Refused",
    "VersionOutcome",
    "extract_corpus",
    "extract_version",
    "now",
    "provenance_for",
    "source_dir",
    "sourced",
]
