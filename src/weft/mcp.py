"""The corpus as tools an agent can call, over MCP on stdio.

The same questions as the CLI and the HTTP API, wrapped so that a model gets tools rather than a shell: `weft.query` is the only thing here that knows anything, and every tool is a few lines around one of its calls. The acceptance test for this surface is a single question -- *what does this theorem depend on, and where is each dependency stated* -- which `closure` with text answers in one call.

Read-only, local, and dependency-free: JSON-RPC 2.0 over newline-delimited stdin and stdout, which is what MCP's stdio transport is. `dispatch` is a pure function of a request and a corpus, so the protocol is tested without a subprocess.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import IO, Any

from weft import query
from weft.config import Settings
from weft.store import Store, open_store

PROTOCOL = "2025-06-18"
SERVER = {"name": "weft", "title": "weft corpus", "version": "0.1"}

INVALID_PARAMS = -32602
METHOD_NOT_FOUND = -32601
INTERNAL = -32603

Call = Callable[[Store, dict[str, Any]], Any]


@dataclass
class Tool:
    """One MCP tool: what a model is told about it, and the call it makes over the index."""

    name: str
    description: str
    properties: dict[str, Any]
    required: list[str]
    run: Call
    read_only: bool = True

    @property
    def schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": self.properties, "required": self.required}

    def listing(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.schema,
            "annotations": {"readOnlyHint": self.read_only, "openWorldHint": False},
        }


KEY = {"type": "string", "description": "A result key, as `arxiv:1709.09864v2#thm-4.1`."}
WORK = {"type": "string", "description": "A work key, as `arxiv:1709.09864` or `doi:10.1007/s002220050293`."}
TEXT = {"type": "boolean", "description": "Include each result's statement and proof text.", "default": False}

TOOLS: list[Tool] = [
    Tool(
        "search_works",
        "Works whose title or authors answer a query, with the versions the corpus holds for each. The way in when all you have is a name.",
        {"text": {"type": "string"}, "limit": {"type": "integer", "default": 25}},
        ["text"],
        lambda store, a: query.search(store, str(a.get("text", "")), limit=int(a.get("limit", 25))),
    ),
    Tool(
        "get_result",
        "One result by key: its statement, its proof where the corpus keeps one, and the edges into and out of it.",
        {"key": KEY, "text": {**TEXT, "default": True}},
        ["key"],
        lambda store, a: query.get(store, str(a.get("key", "")), text=bool(a.get("text", True))),
    ),
    Tool(
        "closure",
        "Everything a result depends on, transitively, and the citations that name a work rather than a result. With `text`, each dependency arrives stated, which answers `what does this theorem depend on, and where is each dependency stated` in one call.",
        {"key": KEY, "depth": {"type": "integer", "default": query.MAX_DEPTH}, "text": TEXT},
        ["key"],
        lambda store, a: query.closure(
            store, str(a.get("key", "")), depth=int(a.get("depth", query.MAX_DEPTH)), text=bool(a.get("text", False))
        ),
    ),
    Tool(
        "dependents",
        "What uses a result, one step out: the edge and the result that draws it.",
        {"key": KEY, "text": TEXT},
        ["key"],
        lambda store, a: query.dependents(store, str(a.get("key", "")), text=bool(a.get("text", False))),
    ),
    Tool(
        "work",
        "A work, its versions, its results and the works it cites.",
        {"id": WORK},
        ["id"],
        lambda store, a: query.neighbourhood(store, str(a.get("id", ""))),
    ),
    Tool(
        "versions",
        "The versions of a work and what each one states, so a result dropped between a preprint and its article is visible.",
        {"id": WORK},
        ["id"],
        lambda store, a: query.versions(store, str(a.get("id", ""))),
    ),
    Tool(
        "bib",
        "A BibTeX entry for a work, with every identifier the corpus holds for it.",
        {"id": WORK},
        ["id"],
        lambda store, a: query.bib(store, str(a.get("id", ""))),
    ),
    Tool(
        "counts",
        "How much the corpus holds: works, versions, results, edges, references.",
        {},
        [],
        lambda store, _a: store.counts(),
    ),
]

BY_NAME = {tool.name: tool for tool in TOOLS}


@dataclass
class Session:
    """What one connection remembers: whether the client has initialised, and which protocol version was agreed."""

    protocol: str = PROTOCOL
    initialised: bool = False
    notes: list[str] = field(default_factory=list)


def _error(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _ok(rid: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _content(payload: Any) -> dict[str, Any]:
    """A tool's answer as MCP carries it: the JSON as text, and the same object structured where there is one.

    A model reads the text; a client that validates against the schema reads `structuredContent`. Sending both costs nothing and lets either work.
    """
    out: dict[str, Any] = {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2, sort_keys=True, default=str)}],
        "isError": False,
    }
    if isinstance(payload, dict):
        out["structuredContent"] = payload
    return out


def _call(settings: Settings, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one tool over a freshly opened index, so a corpus rebuilt under a long-lived server is still read correctly."""
    tool = BY_NAME.get(name)
    if tool is None:
        return {"content": [{"type": "text", "text": f"no such tool: {name}"}], "isError": True}
    store = open_store(settings)
    try:
        payload = tool.run(store, arguments)
    except Exception as exc:  # a bad argument is an answer the model can act on, not a dead server
        return {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True}
    finally:
        store.close()
    if payload is None:
        return {"content": [{"type": "text", "text": "nothing in this corpus answers to that key"}], "isError": True}
    return _content(payload)


def dispatch(settings: Settings, session: Session, request: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC message in, one response out, or None for a notification.

    Parameters
    ----------
    settings : Settings
        The corpus every tool reads.
    session : Session
        Per-connection state; mutated by `initialize`.
    request : dict
        A decoded JSON-RPC 2.0 request or notification.

    Returns
    -------
    dict or None
        The response to write back, or None where the message was a notification and the protocol forbids an answer.
    """
    method = str(request.get("method", ""))
    rid = request.get("id")
    params = request.get("params") or {}
    if rid is None and method.startswith("notifications/"):
        if method == "notifications/initialized":
            session.initialised = True
        return None
    if method == "initialize":
        asked = str(params.get("protocolVersion") or PROTOCOL)
        session.protocol = asked if asked == PROTOCOL else PROTOCOL
        return _ok(
            rid,
            {
                "protocolVersion": session.protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER,
                "instructions": "A read-only library of mathematical results. Keys are `<version>#<local>`; `closure` with text answers what a theorem depends on and where each dependency is stated.",
            },
        )
    if method == "ping":
        return _ok(rid, {})
    if method == "tools/list":
        return _ok(rid, {"tools": [tool.listing() for tool in TOOLS]})
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(rid, INVALID_PARAMS, "arguments must be an object")
        return _ok(rid, _call(settings, name, arguments))
    if method in {"resources/list", "prompts/list"}:
        return _ok(rid, {"resources": [], "prompts": []} if method == "resources/list" else {"prompts": []})
    return _error(rid, METHOD_NOT_FOUND, f"no such method: {method}")


def serve_stdio(settings: Settings, stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> None:
    """Answer MCP over newline-delimited JSON-RPC until the client closes the stream."""
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    session = Session()
    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue  # a stdio transport carries one message per line; a torn line is not ours to repair
        if not isinstance(request, dict):
            continue
        try:
            response = dispatch(settings, session, request)
        except Exception as exc:  # pragma: no cover - a bug here must still leave the client an answer
            response = _error(request.get("id"), INTERNAL, f"{type(exc).__name__}: {exc}")
        if response is not None:
            sink.write(json.dumps(response) + "\n")
            sink.flush()
