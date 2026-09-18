"""Replay the corpus into the index: `works/` is the truth and everything queryable is reconstructed from it.

One `work.json` per work, one optional `results.json` per version beside its source, one optional `same_as.json` per work. A record that cannot be read is reported and skipped: a rebuild over a corpus with one bad file still produces an index for the rest, because refusing the whole replay over one malformed file would make the derived thing able to hold the truth hostage.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from weft.config import Settings
from weft.model import Edge, Reference, Result, SameAs, Version, Work
from weft.store import Store

log = logging.getLogger(__name__)

RECORD = 1
RECORD_NAME = "work.json"
RESULTS_NAME = "results.json"
SAME_AS_NAME = "same_as.json"

COUNT_NAMES = ("works", "versions", "results", "edges", "references", "same_as")


class Malformed(Exception):
    """A file that does not hold the record it claims to; the caller reports it and moves on."""


def rebuild(settings: Settings, store: Store) -> dict[str, int]:
    """Clear the index and replay every record under `settings.works_dir` into it.

    Parameters
    ----------
    settings : Settings
        The corpus whose `works/` tree is replayed.
    store : Store
        The index to fill; it is cleared first, so a rebuild never leaves a row no file accounts for.

    Returns
    -------
    dict[str, int]
        Rows written, under the keys 'works', 'versions', 'results', 'edges', 'references' and 'same_as'.

    See Also
    --------
    weft.store.open_store : the index named by the corpus's dsn.
    """
    store.clear()
    counts = dict.fromkeys(COUNT_NAMES, 0)
    root = settings.works_dir
    if not root.is_dir():
        log.warning("%s: no works/ directory; the index is empty", settings.root)
        return counts
    for path in sorted(root.rglob(RECORD_NAME)):
        try:
            counts_of_record = _replay_work(path, store)
        except Malformed as exc:
            log.warning("skipped %s: %s", path, exc)
            continue
        for name, n in counts_of_record.items():
            counts[name] += n
    return counts


def _replay_work(path: Path, store: Store) -> dict[str, int]:
    """Write one work.json, its versions, its references and whatever results.json files sit beside them.

    Raises Malformed for a file rebuild cannot use at all; a single unusable version or reference entry is reported and dropped without losing the work.
    """
    raw = _read(path)
    if not isinstance(raw, dict):
        raise Malformed("not a JSON object")
    if _int(raw.get("record")) != RECORD:
        raise Malformed(f"record version {raw.get('record')!r}, want {RECORD}")
    key = _str(raw.get("key"))
    if not key:
        raise Malformed("no key")

    work = Work(
        key=key,
        ids=_strs(raw.get("ids")) or [key],
        title=_str(raw.get("title")),
        authors=_strs(raw.get("authors")),
        year=_str(raw.get("year")),
        msc=_strs(raw.get("msc")),
        arxiv_category=_str(raw.get("arxiv_category")),
        licence=_str(raw.get("licence")),
        depth=_int(raw.get("depth")),
        reached_from=_strs(raw.get("reached_from")),
        reached_by=_str(raw.get("reached_by")),
        provenance=_str(raw.get("provenance")) or "declared",
        citekeys=_strs(raw.get("citekeys")),
    )
    versions = _versions(raw.get("versions"), key, path)
    references = _references(raw.get("references"), _reference_version(key, versions), path)

    counts = dict.fromkeys(COUNT_NAMES, 0)
    counts["works"] = store.upsert_works([work])
    counts["versions"] = store.upsert_versions(versions)
    counts["references"] = store.upsert_references(references)

    home = path.parent
    for results_path in sorted(home.glob(f"*/{RESULTS_NAME}")):
        try:
            results, edges, same_as = _read_results(results_path)
        except Malformed as exc:
            log.warning("skipped %s: %s", results_path, exc)
            continue
        counts["results"] += store.upsert_results(results)
        counts["edges"] += store.upsert_edges(edges)
        counts["same_as"] += store.upsert_same_as(same_as)
    counts["same_as"] += store.upsert_same_as(_read_same_as(home / SAME_AS_NAME))
    return counts


def _reference_version(work: str, versions: list[Version]) -> str:
    """The version a work-level bibliography is attributed to: the last one with a source, whose `\\bibitem`s were the ones read, else the last version, else the work itself for a metadata-only node."""
    sourced = [v.id for v in versions if v.has_source]
    if sourced:
        return sourced[-1]
    return versions[-1].id if versions else work


def _versions(raw: Any, work: str, path: Path) -> list[Version]:
    out: list[Version] = []
    for entry in _objects(raw):
        vid = _str(entry.get("id"))
        if not vid:
            log.warning("%s: a version with no id, dropped", path)
            continue
        out.append(
            Version(
                id=vid,
                work=work,
                has_source=bool(entry.get("has_source")),
                has_pdf=bool(entry.get("has_pdf")),
                method=_str(entry.get("method")),
                numbering=_str(entry.get("numbering")),
                extracted_at=_str(entry.get("extracted_at")),
            )
        )
    return out


def _references(raw: Any, version: str, path: Path) -> list[Reference]:
    out: list[Reference] = []
    for entry in _objects(raw):
        text = _str(entry.get("text"))
        citekey = _str(entry.get("citekey"))
        if not text and not citekey:
            log.warning("%s: a reference with neither citekey nor text, dropped", path)
            continue
        out.append(
            Reference(
                version=version,
                work=_str(entry.get("work")),
                citekey=citekey,
                text=text,
                identified_by=_str(entry.get("identified_by")),
            )
        )
    return out


def _read_results(path: Path) -> tuple[list[Result], list[Edge], list[SameAs]]:
    """One version's extraction output: its results, the edges read out of them, and any cross-version mapping it recorded."""
    raw = _read(path)
    if not isinstance(raw, dict):
        raise Malformed("not a JSON object")
    version = _str(raw.get("version"))
    if not version:
        raise Malformed("no version")
    results: list[Result] = []
    for entry in _objects(raw.get("results")):
        local = _str(entry.get("local"))
        if not local:
            log.warning("%s: a result with no local part, dropped", path)
            continue
        results.append(
            Result(
                version=version,
                local=local,
                taxon=_str(entry.get("taxon")),
                number=_str(entry.get("number")),
                title=_str(entry.get("title")),
                statement=_str(entry.get("statement")),
                proof=_str(entry.get("proof")),
                aliases=_strs(entry.get("aliases")),
                page=_str(entry.get("page")),
            )
        )
    return results, _edges(raw.get("edges"), path), _same_as(raw.get("same_as"), path)


def _edges(raw: Any, path: Path) -> list[Edge]:
    out: list[Edge] = []
    for entry in _objects(raw):
        src, to = _str(entry.get("src")), _str(entry.get("to"))
        if not src or not to:
            log.warning("%s: an edge missing an end, dropped", path)
            continue
        out.append(
            Edge(
                src=src,
                to=to,
                origin=_str(entry.get("origin")),
                confidence=_float(entry.get("confidence")),
                evidence=_str(entry.get("evidence")),
            )
        )
    return out


def _same_as(raw: Any, path: Path) -> list[SameAs]:
    out: list[SameAs] = []
    for entry in _objects(raw):
        left, right = _str(entry.get("left")), _str(entry.get("right"))
        if not left or not right:
            log.warning("%s: a same_as pair missing a side, dropped", path)
            continue
        out.append(
            SameAs(
                left=left, right=right, confidence=_float(entry.get("confidence")), evidence=_str(entry.get("evidence"))
            )
        )
    return out


def _read_same_as(path: Path) -> list[SameAs]:
    """A work-level mapping between its versions' results, as a bare list or under a `same_as` key; absent is the normal case."""
    if not path.is_file():
        return []
    try:
        raw = _read(path)
    except Malformed as exc:
        log.warning("skipped %s: %s", path, exc)
        return []
    entries = raw.get("same_as") if isinstance(raw, dict) else raw
    return _same_as(entries, path)


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise Malformed(f"unreadable ({exc.strerror or exc})") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Malformed(f"not JSON ({exc})") from exc


def _objects(raw: Any) -> Iterable[dict[str, Any]]:
    return [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _strs(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str) and v] if isinstance(value, list) else []


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _float(value: Any) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 1.0
