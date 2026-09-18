"""A read-only HTTP face on the index, for the view and for anything else that would rather ask over a socket than run a command.

Local by default and read-only always: a corpus is other people's text, and nothing here writes to it. Result keys carry `#`, which a URL path would read as a fragment, so every key is passed as a query parameter.
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from weft import query
from weft.config import Settings
from weft.store import Store, open_store

Handler = Callable[[Store, dict[str, list[str]]], tuple[int, Any]]


def _one(params: dict[str, list[str]], name: str, default: str = "") -> str:
    return (params.get(name) or [default])[0]


def _int(params: dict[str, list[str]], name: str, default: int) -> int:
    try:
        return int(_one(params, name, str(default)))
    except ValueError:
        return default


def _flag(params: dict[str, list[str]], name: str) -> bool:
    return _one(params, name, "").lower() in {"1", "true", "yes"}


def _search(store: Store, params: dict[str, list[str]]) -> tuple[int, Any]:
    return 200, query.search(store, _one(params, "q"), limit=_int(params, "limit", 25))


def _result(store: Store, params: dict[str, list[str]]) -> tuple[int, Any]:
    found = query.get(store, _one(params, "key"), text=not _flag(params, "no_text"))
    return (200, found) if found is not None else (404, {"error": "no such result", "key": _one(params, "key")})


def _closure(store: Store, params: dict[str, list[str]]) -> tuple[int, Any]:
    return 200, query.closure(store, _one(params, "key"), depth=_int(params, "depth", 6), text=_flag(params, "text"))


def _dependents(store: Store, params: dict[str, list[str]]) -> tuple[int, Any]:
    return 200, query.dependents(store, _one(params, "key"), text=_flag(params, "text"))


def _work(store: Store, params: dict[str, list[str]]) -> tuple[int, Any]:
    found = query.neighbourhood(store, _one(params, "id"))
    return (200, found) if found.get("found") else (404, found)


def _versions(store: Store, params: dict[str, list[str]]) -> tuple[int, Any]:
    found = query.versions(store, _one(params, "id"))
    return (200, found) if found.get("found") else (404, found)


def _bib(store: Store, params: dict[str, list[str]]) -> tuple[int, Any]:
    found = query.bib(store, _one(params, "id"))
    return (200, found) if found is not None else (404, {"error": "no such work", "id": _one(params, "id")})


def _counts(store: Store, _params: dict[str, list[str]]) -> tuple[int, Any]:
    return 200, store.counts()


ROUTES: dict[str, Handler] = {
    "/search": _search,
    "/result": _result,
    "/closure": _closure,
    "/dependents": _dependents,
    "/work": _work,
    "/versions": _versions,
    "/bib": _bib,
    "/counts": _counts,
}


def make_server(settings: Settings, host: str = "127.0.0.1", port: int = 8791) -> ThreadingHTTPServer:
    """A server over this corpus's index. The caller owns its lifetime, which is what lets a test start and stop one."""

    class CorpusHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: object) -> None:  # noqa: A002 - the base class names it so
            return  # a query is not news; the CLI says what it started

        def do_GET(self) -> None:  # noqa: N802 - the base class names it so
            parsed = urllib.parse.urlsplit(self.path)
            handler = ROUTES.get(parsed.path)
            if handler is None:
                self._send(404, {"error": "no such route", "routes": sorted(ROUTES)})
                return
            params = urllib.parse.parse_qs(parsed.query)
            store = open_store(settings)
            try:
                status, payload = handler(store, params)
            except Exception as exc:  # a malformed query is an answer, not a crashed server
                status, payload = 400, {"error": str(exc)}
            finally:
                store.close()
            self._send(status, payload)

        def _send(self, status: int, payload: Any) -> None:
            body = (json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n").encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((host, port), CorpusHandler)


def serve(settings: Settings, host: str = "127.0.0.1", port: int = 8791) -> None:
    """Serve until interrupted."""
    server = make_server(settings, host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
