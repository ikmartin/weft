"""A polite client for one service: one rate budget per host, cached answers, an injected transport.

Every request weft makes goes through a `Service`, so the spacing a host asks for and the cache that makes a second plan fast are the same everywhere, and tests replace the transport rather than the network.

**The budget is per host, not per service or per command.** This is the lesson of loom's worst incident: a harvest of arXiv's OAI-PMH interface run while a fetch was in progress made arXiv answer 406 to every request from loom's HTTP client for about fifty minutes, while curl from the same machine was still served. A service throttles a client, not a command, so `BUDGET` is one object for the process and every `Service` and every downloader passes through it.
"""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from weft import __version__

USER_AGENT = f"weft/{__version__} (+https://github.com/ikmartin/weft)"

# Seconds between two requests to one host. arXiv asks for one request every three seconds on a single connection; Crossref's public pool reports one a second, and zbMATH Open asks for a reasonable rate without stating a number, so it gets the same; OpenAlex allows ten a second and is asked for five.
HOST_SPACING = {
    "arxiv.org": 3.0,
    "export.arxiv.org": 3.0,
    "api.zbmath.org": 1.0,
    "api.crossref.org": 1.0,
    "api.openalex.org": 0.2,
}
DEFAULT_SPACING = 1.0

# Names a directory of recorded answers; when it is set the default transport reads from it and makes no request.
OFFLINE = "WEFT_OFFLINE_RESPONSES"
# Where the last request to each host is recorded, so two weft processes do not double the rate a service sees. A service throttles a client, and a second process is the same client.
STATE = "WEFT_STATE_DIR"

Transport = Callable[[str, dict[str, str]], bytes]


class ServiceError(Exception):
    """A service could not be reached or refused the request; `code` is the HTTP status where there was one."""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code


class NotFound(ServiceError):
    """The service answered that it has no such record."""


def _default_state_dir() -> Path | None:
    """Where this machine records its last request per host: `$WEFT_STATE_DIR`, else a directory under the user's cache. `WEFT_STATE_DIR=` empty turns sharing off, which is what the tests do."""
    named = os.environ.get(STATE)
    if named is not None:
        return Path(named) if named else None
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "weft" / "hosts"


class HostBudget:
    """How often one host may be asked, and when each was last asked.

    Shared by every service and every downloader, whatever command they serve. `clock` and `sleep` are injected so a test can watch the spacing without waiting for it.

    Parameters
    ----------
    spacing : dict of str to float, optional
        Seconds between requests, by host; default `HOST_SPACING`. A host not named gets `DEFAULT_SPACING`.
    clock : callable, default `time.monotonic`
    sleep : callable, default `time.sleep`
    """

    def __init__(
        self,
        spacing: dict[str, float] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        state_dir: Path | None = None,
    ) -> None:
        self.spacing = dict(HOST_SPACING if spacing is None else spacing)
        self.clock = clock
        self.sleep = sleep
        self.state = state_dir if state_dir is not None else _default_state_dir()
        self.waited = 0.0
        self.taken = 0
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def host(self, url: str) -> str:
        """The bucket a request is counted against: the URL's host, with one operator's hosts sharing a bucket.

        arXiv's metadata and its e-prints answer on different hosts but throttle one client together, which is how loom earned an hour of 406s by harvesting while a fetch ran.
        """
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        return "arxiv.org" if host.endswith("arxiv.org") else host

    def seconds(self, host: str) -> float:
        """The spacing this host asks for."""
        return self.spacing.get(host, DEFAULT_SPACING)

    def take(self, url: str, minimum: float = 0.0) -> float:
        """Wait until this host may be asked again, record the request, and return the seconds waited.

        Parameters
        ----------
        url : str
            The request about to be made; only its host matters.
        minimum : float, default 0.0
            A spacing this caller needs beyond the host's own, which is how bulk downloads leave more room than metadata queries: arXiv answers an API query every three seconds and refuses e-prints asked for that fast.

        Returns
        -------
        float
            How long the caller was held back, 0.0 when the host was free.
        """
        host = self.host(url)
        with self._lock:
            gap = max(self.seconds(host), minimum)
            last = self._last.get(host)
            wait = 0.0 if last is None else last + gap - self.clock()
            shared = self._shared_wait(host, gap)
            wait = max(wait, shared)
            if wait > 0:
                self.sleep(wait)
                self.waited += wait
            else:
                wait = 0.0
            self._last[host] = self.clock()
            self._record_shared(host)
            self.taken += 1
            return wait

    def _shared_wait(self, host: str, gap: float) -> float:
        """How long another process's last request to this host still asks us to wait; 0.0 with no shared state."""
        path = self._state_path(host)
        if path is None:
            return 0.0
        try:
            last = float(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 0.0
        return max(0.0, last + gap - time.time())

    def _record_shared(self, host: str) -> None:
        path = self._state_path(host)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{time.time():.3f}\n", encoding="utf-8")
        except OSError:
            pass  # a corpus on a read-only disk still crawls; it just cannot tell another process what it did

    def _state_path(self, host: str) -> Path | None:
        return None if self.state is None else self.state / f"{host}.last"


# Statuses worth asking again about. A 406 is here as belt and braces behind `CONTEXT`: it was arXiv's answer to a handshake with no ALPN, and a 406 that still arrives is not the request's fault.
RETRY = (406, 429, 500, 502, 503)
ATTEMPTS = 3


def _context() -> ssl.SSLContext:
    """A TLS context that advertises ALPN, which is what every other HTTP client does and what arXiv's edge requires.

    Python's `urllib` never calls `set_alpn_protocols`, so its ClientHello carries no ALPN extension; curl and httpx always send one. arXiv's edge answers such a handshake with 406 Not Acceptable, some of the time and on some paths, which is what the refusals of 2026-09-17 and 2026-09-18 actually were -- read first as a missing header, then as a rate limit, then as a wrong hostname, and none of those. Measured on 2026-09-18 over six interleaved pairs against one OAI endpoint: the default context 3/6, this context 6/6, with the failures and successes alternating on the same identifiers minutes apart.
    """
    ctx = ssl.create_default_context()
    ctx.set_alpn_protocols(["http/1.1"])
    return ctx


CONTEXT = _context()
OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler(context=CONTEXT))

# The process's budget. Every Service and downloader uses this one unless a test hands over another.
BUDGET = HostBudget()


def http(url: str, headers: dict[str, str]) -> bytes:
    """GET with weft's User-Agent; the default transport when nothing is recorded."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with OPENER.open(req, timeout=60) as resp:
            return bytes(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NotFound(url.split("?")[0]) from exc
        raise ServiceError(f"{url.split('?')[0]}: HTTP {exc.code} {exc.reason}", exc.code) from exc
    except urllib.error.URLError as exc:
        raise ServiceError(f"{url.split('?')[0]}: {exc.reason}") from exc


def offline_dir() -> Path | None:
    """The recorded-answer directory `WEFT_OFFLINE_RESPONSES` names, or None."""
    d = os.environ.get(OFFLINE)
    return Path(d) if d else None


def answer_path(directory: Path, service: str, url: str) -> Path:
    """Where a recorded answer for one service and one URL lives: `<dir>/<service>/<sha256(url)[:32]>.json`."""
    return directory / service / (hashlib.sha256(url.encode("utf-8")).hexdigest()[:32] + ".json")


def offline(service: str, directory: Path) -> Transport:
    """A transport that reads recorded answers from `directory` and never makes a request.

    A miss raises `ServiceError` naming the URL and the file that would have answered it, because a demo that silently skipped a request would be reported as a service having nothing to say.
    """

    def read(url: str, headers: dict[str, str]) -> bytes:
        path = answer_path(directory, service, url)
        if not path.is_file():
            raise ServiceError(f"{OFFLINE}={directory} has no recorded answer for {url} (expected {path})")
        return path.read_bytes()

    return read


def transport_for(service: str, default: Transport = http) -> Transport:
    """`default`, or the offline transport for this service when `WEFT_OFFLINE_RESPONSES` names a directory."""
    d = offline_dir()
    return offline(service, d) if d is not None else default


class Service:
    """One service's requests: spaced by its host's budget, and answered from `cache` when asked before.

    Parameters
    ----------
    name : str
        Names the cache directory, the recorded-answer directory and the counters.
    cache : Path or None, default None
        A directory of raw answers keyed by URL. Headers are not part of the key, so a key sent as a header never names a file.
    transport : callable, optional
        `(url, headers) -> bytes`; default the offline transport when one is configured, else a real GET.
    refresh : bool, default False
        Ignore cached answers and ask again.
    budget : HostBudget, optional
        Default the process's `BUDGET`, which is what makes two services on one host serialise.
    """

    def __init__(
        self,
        name: str,
        cache: Path | None = None,
        transport: Transport | None = None,
        refresh: bool = False,
        budget: HostBudget | None = None,
    ) -> None:
        self.name = name
        self.cache = cache / name if cache else None
        self.transport = transport if transport is not None else transport_for(name)
        self.refresh = refresh
        self.budget = budget if budget is not None else BUDGET
        self.requests = 0
        self.cached = 0
        self.failures = 0
        self.last_failure = ""

    def _path(self, url: str) -> Path | None:
        return self.cache / (hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]) if self.cache else None

    def get(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        """The body at `url`; NotFound is cached too, so a record known to be absent is not asked for again."""
        path = self._path(url)
        if path is not None and not self.refresh:
            if path.with_suffix(".absent").is_file():
                self.cached += 1
                raise NotFound(url.split("?")[0])
            if path.is_file():
                self.cached += 1
                return path.read_bytes()
        body = b""
        for attempt in range(ATTEMPTS):
            self.budget.take(url)
            self.requests += 1
            try:
                body = self.transport(url, headers or {})
                break
            except NotFound:
                if path is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.with_suffix(".absent").write_text(url, encoding="utf-8")
                raise
            except ServiceError as exc:
                self.failures += 1
                self.last_failure = str(exc)
                if exc.code not in RETRY or attempt == ATTEMPTS - 1:
                    raise
                self.budget.sleep(2.0 * (attempt + 1))
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        return body

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any:
        try:
            return json.loads(self.get(url, headers).decode("utf-8"))
        except ValueError as exc:
            raise ServiceError(f"{self.name}: an answer that is not JSON from {url.split('?')[0]}") from exc
