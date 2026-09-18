"""Edges between results: what a paper states about its own results, and what it states about another paper's.

Three kinds, and no fourth. Inside one version, a `\\ref` in a statement or a proof to another result of the same version is an `internal` edge. Across papers, a citation carrying a locator (`\\cite[Theorem 9.4]{key}`) is a `locator` edge to the result it names, and a citation carrying none is an `unspecified` edge to the whole work. Nothing is inferred from similarity, from notation, or from a model's reading; those are the research question of plan 0.1 §11.

An ambiguity is logged rather than guessed at: a locator that answers several results of the cited work records no edge and appends a row to `docs/multi-match-record.md`, because a wrong dependency is worse than a missing one for anything reasoning over the graph.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from weft.config import Settings
from weft.crawl.work import load_all, norm
from weft.files import write_atomic
from weft.locators import forms_for, normalize, parts
from weft.model import Edge

CITE = re.compile(r"\\(?:cite|parencite|textcite|autocite|citep|citet|footcite)\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}")
REF = re.compile(r"\\(?:ref|eqref|cref|Cref|autoref)\s*\{([^}]*)\}")
RECORD = Path("docs") / "multi-match-record.md"


@dataclass
class Ambiguity:
    """A citation that named more than one result, or a multi-part postnote that resolved in part."""

    citing: str
    work: str
    postnote: str
    matched: list[str] = field(default_factory=list)
    kind: str = "several"

    def row(self, when: str) -> str:
        return (
            f"| {when} | `{self.citing}` | `{self.work}` | `{self.postnote}` | "
            f"`{normalize(self.postnote)}` | {', '.join(f'`{k}`' for k in self.matched) or '—'} | {self.kind} |"
        )


@dataclass
class LinkReport:
    """What one pass over a corpus found."""

    versions: int = 0
    internal: int = 0
    locator: int = 0
    unspecified: int = 0
    unmatched: int = 0
    ambiguous: list[Ambiguity] = field(default_factory=list)

    def payload(self) -> dict[str, object]:
        return {
            "versions": self.versions,
            "internal": self.internal,
            "locator": self.locator,
            "unspecified": self.unspecified,
            "unmatched": self.unmatched,
            "ambiguous": [
                {"citing": a.citing, "work": a.work, "postnote": a.postnote, "matched": a.matched, "kind": a.kind}
                for a in self.ambiguous
            ],
        }

    def summary(self) -> str:
        lines = [
            f"{self.versions} versions linked",
            f"  {self.internal} internal · {self.locator} by locator · {self.unspecified} to a work with no locator",
            f"  {self.unmatched} locators matched nothing · {len(self.ambiguous)} ambiguous, logged and not recorded",
        ]
        return "\n".join(lines)


@dataclass
class _Version:
    """One version's results as the linker needs them: the text to read citations out of, and what each result answers to."""

    ident: str
    work: str
    path: Path
    data: dict[str, Any]
    prefix: str = ""  # what the digest's ids carry, so a rewritten `\\ref` can be read back
    forms: list[tuple[str, set[str]]] = field(default_factory=list)  # (result key, the strings it answers to)
    by_label: dict[str, str] = field(default_factory=dict)  # a label or alias of this version to its result key


def _load(settings: Settings) -> list[_Version]:
    """Every version with extracted results, with its forms built."""
    out: list[_Version] = []
    for path in sorted(settings.works_dir.rglob("results.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        ident = str(data.get("version", ""))
        if not ident:
            continue
        # the results file names its version; which work that version belongs to is the record's business, one directory up
        record = path.parent.parent / "work.json"
        try:
            work = str(json.loads(record.read_text(encoding="utf-8")).get("key", ""))
        except (OSError, json.JSONDecodeError):
            work = ""
        version = _Version(ident=ident, work=work, path=path, data=data, prefix=_prefix_of(path.parent, ident))
        for result in list(data.get("results", [])):
            local = str(result.get("local", ""))
            if not local:
                continue
            key = f"{ident}#{local}"
            aliases = [str(a) for a in result.get("aliases", [])]
            version.forms.append(
                (key, forms_for(local, str(result.get("taxon", "")), str(result.get("number", "")), aliases, ""))
            )
            for label in [local, *aliases]:
                version.by_label.setdefault(label, key)
        out.append(version)
    return out


def _prefix_of(directory: Path, ident: str) -> str:
    """The prefix this version's ids carry, from its digest's header, else derived from the version id as extraction derives it."""
    header = directory / "digest.tex"
    try:
        for line in header.read_text(encoding="utf-8").splitlines()[:20]:
            if m := re.match(r"^%\s*!LOOM\s+prefix:\s*(\S+)", line):
                return m.group(1)
    except OSError:
        pass
    return re.sub(r"[^A-Za-z0-9.-]+", "-", ident)


def _citekeys(settings: Settings) -> dict[str, dict[str, str]]:
    """Per work key, what each citekey in its bibliography resolved to: `{citing work: {citekey: cited work}}`.

    A citation names whichever artifact its author had in hand, and a corpus files a work under whichever identifier ranked first, so a paper citing `arxiv:0902.0087` and a record keyed `doi:10.2140/gt.2019.23.1621` are the same work under two names. Every identifier a record carries is resolved to that record's key here; without it a bibliography can be fully identified and still draw no edge.
    """
    records = load_all(settings.works_dir)
    canonical = {norm(ident): key for key, record in records.items() for ident in record.ids}
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for key, record in records.items():
        for reference in record.references:
            if reference.citekey and reference.work:
                out[key][reference.citekey] = canonical.get(norm(reference.work), reference.work)
    return out


def _text_of(result: dict[str, Any]) -> str:
    return f"{result.get('statement', '')}\n{result.get('proof', '')}"


def link(settings: Settings, *, log: Path | None = None) -> LinkReport:
    """Draw every edge the papers state, write them into each version's `results.json`, and log what was ambiguous."""
    versions = _load(settings)
    by_work: dict[str, list[_Version]] = defaultdict(list)
    for version in versions:
        by_work[version.work].append(version)
    citekeys = _citekeys(settings)
    report = LinkReport(versions=len(versions))

    for version in versions:
        edges: list[Edge] = []
        known = citekeys.get(version.work, {})
        for result in list(version.data.get("results", [])):
            local = str(result.get("local", ""))
            if not local:
                continue
            src = f"{version.ident}#{local}"
            text = _text_of(result)
            for label in REF.findall(text):
                # a `\\ref` inside a digest names a prefixed id, because two papers' `eq:main` must not collide; the paper's own label is what the aliases hold
                name = label.strip()
                bare = (
                    name[len(version.prefix) + 1 :]
                    if version.prefix and name.startswith(version.prefix + "-")
                    else name
                )
                target = version.by_label.get(bare) or version.by_label.get(name)
                if target and target != src:
                    edges.append(Edge(src=src, to=target, origin="internal", evidence=f"\\ref{{{name}}}"))
            for postnote, keys in CITE.findall(text):
                for citekey in (k.strip() for k in keys.split(",") if k.strip()):
                    work = known.get(citekey)
                    if not work:
                        continue
                    if not postnote.strip():
                        edges.append(Edge(src=src, to=work, origin="unspecified", evidence=f"\\cite{{{citekey}}}"))
                        continue
                    drawn, troubles, missed = _resolve(src, work, postnote, by_work.get(work, []))
                    edges.extend(drawn)
                    report.ambiguous.extend(troubles)
                    report.unmatched += missed
        report.internal += sum(1 for e in edges if e.origin == "internal")
        report.locator += sum(1 for e in edges if e.origin == "locator")
        report.unspecified += sum(1 for e in edges if e.origin == "unspecified")
        version.data["edges"] = [
            {"src": e.src, "to": e.to, "origin": e.origin, "confidence": e.confidence, "evidence": e.evidence}
            for e in edges
        ]
        write_atomic(version.path, json.dumps(version.data, indent=2, sort_keys=True) + "\n")

    if report.ambiguous:
        _log(settings, report.ambiguous, log)
    return report


def _resolve(src: str, work: str, postnote: str, versions: list[_Version]) -> tuple[list[Edge], list[Ambiguity], int]:
    """The edges a locator draws, the ambiguities it raises, and how many of its parts named nothing.

    A postnote is resolved part by part, because `Theorems 1.1 and 2.3` names two results and is not an ambiguity. A part that answers in several versions of one work is one result under several numberings, so the latest version answers; a part that answers two different results is the case we do not know how to decide, and it is logged instead.
    """
    drawn: list[Edge] = []
    troubles: list[Ambiguity] = []
    missed = 0
    wanted = parts(postnote) or [normalize(postnote)]
    for part in wanted:
        if not part:
            continue
        hits: list[str] = []
        for version in versions:
            hits.extend(key for key, forms in version.forms if part in forms)
        if not hits:
            missed += 1
            continue
        locals_hit = {key.partition("#")[2] for key in hits}
        if len(locals_hit) == 1:
            drawn.append(Edge(src=src, to=sorted(hits)[-1], origin="locator", evidence=part))
            continue
        kind = "several" if len(wanted) == 1 else "partial"
        troubles.append(Ambiguity(citing=src, work=work, postnote=postnote.strip(), matched=sorted(hits), kind=kind))
    return drawn, troubles, missed


def _log(settings: Settings, found: list[Ambiguity], log: Path | None) -> None:
    """Append the ambiguities to the record a decision will later be taken from."""
    path = log if log is not None else Path(__file__).resolve().parents[2] / RECORD
    when = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    empty = "_None yet: the linker lands in M3._"
    header = "| when | citing | cited work | postnote | normalised | matched | kind |\n|---|---|---|---|---|---|---|\n"
    rows = "\n".join(a.row(when) for a in found) + "\n"
    text = text.replace(empty, header + rows) if empty in text else text.rstrip("\n") + "\n" + rows
    path.write_text(text, encoding="utf-8")
