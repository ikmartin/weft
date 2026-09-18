"""The questions a reader or an agent asks of a corpus, answered from the index.

One set of queries, whatever the delivery: the CLI prints them as JSON, the HTTP API serves the same payloads, and the MCP server wraps the same calls so an agent gets tools rather than a shell. Every payload carries its provenance -- how a statement was read, and why an edge exists -- because something reasoning over this must be able to tell a verbatim statement from a reconstructed one.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from weft.bibtex import entry_for
from weft.model import Edge, Result, Work
from weft.store import Store

MAX_DEPTH = 6


def _work_payload(work: Work) -> dict[str, Any]:
    return {
        "key": work.key,
        "ids": work.ids,
        "title": work.title,
        "authors": work.authors,
        "year": work.year,
        "msc": work.msc,
        "arxiv_category": work.arxiv_category,
        "depth": work.depth,
        "provenance": work.provenance,
        "citekeys": work.citekeys,
    }


def _result_payload(result: Result, *, text: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "key": str(result.key),
        "version": result.version,
        "local": result.local,
        "taxon": result.taxon,
        "number": result.number,
        "title": result.title,
        "aliases": result.aliases,
        "page": result.page,
    }
    if text:
        out["statement"] = result.statement
        out["proof"] = result.proof
    return out


def _edge_payload(edge: Edge) -> dict[str, Any]:
    return {
        "src": edge.src,
        "to": edge.to,
        "origin": edge.origin,
        "confidence": edge.confidence,
        "evidence": edge.evidence,
    }


def search(store: Store, text: str, *, limit: int = 25) -> dict[str, Any]:
    """Works whose title or authors answer `text`, with their versions."""
    found = []
    for work in store.search_works(text, limit=limit):
        payload = _work_payload(work)
        payload["versions"] = [v.id for v in store.versions_of(work.key)]
        found.append(payload)
    return {"query": text, "works": found}


def get(store: Store, key: str, *, text: bool = True) -> dict[str, Any] | None:
    """One result, with the statement and the proof the corpus holds for it."""
    result = store.result(key)
    if result is None:
        return None
    payload = _result_payload(result, text=text)
    payload["uses"] = [_edge_payload(e) for e in store.edges_from(key)]
    payload["used_by"] = [_edge_payload(e) for e in store.edges_to(key)]
    return payload


def closure(store: Store, key: str, *, depth: int = MAX_DEPTH, text: bool = False) -> dict[str, Any]:
    """Everything a result depends on, transitively, and the citations that name no result.

    A `cites` edge names a whole work rather than a result, so it ends a branch: it is reported as unresolved rather than followed, because following it would mean guessing which result was meant.
    """
    seen: set[str] = {key}
    order: list[str] = []
    unresolved: list[dict[str, Any]] = []
    queue: deque[tuple[str, int]] = deque([(key, 0)])
    while queue:
        current, at = queue.popleft()
        if at >= depth:
            continue
        for edge in store.edges_from(current):
            if edge.origin == "unspecified":
                unresolved.append(_edge_payload(edge))
                continue
            if edge.to in seen:
                continue
            seen.add(edge.to)
            order.append(edge.to)
            queue.append((edge.to, at + 1))
    results = [store.result(k) for k in order]
    return {
        "key": key,
        "depth": depth,
        "closure": [_result_payload(r, text=text) for r in results if r is not None],
        "missing": [k for k, r in zip(order, results, strict=True) if r is None],
        "unresolved": unresolved,
    }


def dependents(store: Store, key: str, *, text: bool = False) -> dict[str, Any]:
    """What uses a result, one step out."""
    edges = list(store.edges_to(key))
    results = {e.src: store.result(e.src) for e in edges}
    return {
        "key": key,
        "used_by": [
            {"edge": _edge_payload(e), "result": _result_payload(r, text=text) if (r := results[e.src]) else None}
            for e in edges
        ],
    }


def neighbourhood(store: Store, work_key: str) -> dict[str, Any]:
    """A work, its versions, its results, and the works around it in the citation graph."""
    work = store.work(work_key)
    if work is None:
        return {"key": work_key, "found": False}
    versions = list(store.versions_of(work.key))
    results = [r for v in versions for r in store.results_of(v.id)]
    cites: set[str] = set()
    for result in results:
        for edge in store.edges_from(str(result.key)):
            cites.add(edge.to if "#" not in edge.to else edge.to.partition("#")[0])
    return {
        "found": True,
        "work": _work_payload(work),
        "versions": [{"id": v.id, "method": v.method, "numbering": v.numbering, "results": 0} for v in versions],
        "results": [_result_payload(r, text=False) for r in results],
        "cites": sorted(cites),
        "references": [
            {"work": r.work, "citekey": r.citekey, "text": r.text, "identified_by": r.identified_by}
            for v in versions
            for r in store.references_of(v.id)
        ],
    }


def versions(store: Store, work_key: str) -> dict[str, Any]:
    """The versions of a work, and what each one states, so a result dropped between them is visible."""
    work = store.work(work_key)
    if work is None:
        return {"key": work_key, "found": False}
    out = []
    for version in store.versions_of(work.key):
        results = list(store.results_of(version.id))
        out.append(
            {
                "id": version.id,
                "method": version.method,
                "numbering": version.numbering,
                "extracted_at": version.extracted_at,
                "results": [{"local": r.local, "taxon": r.taxon, "number": r.number} for r in results],
            }
        )
    return {"found": True, "work": work.key, "versions": out}


def bib(store: Store, work_key: str) -> dict[str, Any] | None:
    """The bibliography entry for a work: the whole seam to a paper's own tool."""
    work = store.work(work_key)
    return None if work is None else {"key": work.key, "entry": entry_for(work)}
