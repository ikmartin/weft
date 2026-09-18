"""A polite client for one service: one rate budget per host, cached answers, an injected transport.

Every request weft makes goes through a `Service`, so the spacing a host asks for and the cache that makes a second plan fast are the same everywhere, and tests replace the transport rather than the network.

**The budget is per host, not per service or per command.** This is the lesson of loom's worst incident: a harvest of arXiv's OAI-PMH interface run while a fetch was in progress made arXiv answer 406 to every request from loom's HTTP client for about fifty minutes, while curl from the same machine was still served. A service throttles a client, not a command, so `BUDGET` is one object for the process and every `Service` and every downloader passes through it.
"""

from __future__ import annotations

import hashlib
import json
import os
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

Transport = Callable[[str, dict[str, str]], bytes]


class ServiceError(Exception):
    """A service could not be reached or refused the request."""


class NotFound(ServiceError):
    """The service answered that it has no such record."""


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
    ) -> None:
        self.spacing = dict(HOST_SPACING if spacing is None else spacing)
        self.clock = clock
        self.sleep = sleep
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
            if wait > 0:
                self.sleep(wait)
                self.waited += wait
            else:
                wait = 0.0
            self._last[host] = self.clock()
            self.taken += 1
            return wait


# The process's budget. Every Service and downloader uses this one unless a test hands over another.
BUDGET = HostBudget()


def http(url: str, headers: dict[str, str]) -> bytes:
    """GET with weft's User-Agent; the default transport when nothing is recorded."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            return bytes(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NotFound(url.split("?")[0]) from exc
        raise ServiceError(f"{url.split('?')[0]}: HTTP {exc.code} {exc.reason}") from exc
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
        self.budget.take(url)
        self.requests += 1
        try:
            body = self.transport(url, headers or {})
        except NotFound:
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.with_suffix(".absent").write_text(url, encoding="utf-8")
            raise
        except ServiceError as exc:
            self.failures += 1
            self.last_failure = str(exc)
            raise
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        return body

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any:
        try:
            return json.loads(self.get(url, headers).decode("utf-8"))
        except ValueError as exc:
            raise ServiceError(f"{self.name}: an answer that is not JSON from {url.split('?')[0]}") from exc
