"""The polite client: one rate budget per host, cached answers and absences, and the offline transport."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from support import Tick, budget
from weft.crawl import download, net
from weft.crawl.fetch import default_downloaders
from weft.crawl.net import HostBudget

Transport = Callable[[str, dict[str, str]], bytes]


def test_a_service_caches_answers_and_absences_and_can_be_refreshed(tmp_path: Path) -> None:
    calls: list[str] = []

    def transport(url: str, headers: dict[str, str]) -> bytes:
        calls.append(url)
        if "missing" in url:
            raise net.NotFound(url)
        return b'{"ok": true}'

    s = net.Service("x", tmp_path, transport, budget=budget())
    assert s.get_json("https://e/1") == {"ok": True}
    assert s.get_json("https://e/1") == {"ok": True}
    for _ in range(2):
        with pytest.raises(net.NotFound):
            s.get("https://e/missing")
    assert calls == ["https://e/1", "https://e/missing"] and s.cached == 2
    net.Service("x", tmp_path, transport, refresh=True, budget=budget()).get("https://e/1")
    assert calls[-1] == "https://e/1"


def test_a_key_sent_as_a_header_never_names_a_cache_file(tmp_path: Path) -> None:
    s = net.Service("openalex", tmp_path, lambda url, headers: b"{}", budget=budget())
    s.get("https://api.openalex.org/works/W1", {"Authorization": "Bearer secret"})
    assert all("secret" not in p.name for p in (tmp_path / "openalex").iterdir())


def test_a_service_counts_its_failures_so_a_plan_can_say_what_it_lacks() -> None:
    def refuse(url: str, headers: dict[str, str]) -> bytes:
        raise net.ServiceError(f"{url}: HTTP 403 Forbidden")

    s = net.Service("openalex", None, refuse, budget=budget())
    for _ in range(2):
        with pytest.raises(net.ServiceError):
            s.get("https://e/w")
    assert s.failures == 2 and "403" in s.last_failure


def test_one_budget_per_host_holds_back_every_service_that_asks() -> None:
    """The lesson of loom's worst incident: arXiv throttled the client, not the command, so the budget is per host and shared."""
    b = budget()
    clock = b.clock
    assert isinstance(clock, Tick)
    asked: list[tuple[float, str]] = []

    def transport(url: str, headers: dict[str, str]) -> bytes:
        asked.append((clock.now, url))
        return b"{}"

    metadata = net.Service("zbmath", None, transport, budget=b)
    lookup = net.Service("zbmath-lookup", None, transport, budget=b)
    # two services on one host serialise: one request a second between them, whichever asked
    metadata.get("https://api.zbmath.org/v1/document/1")
    lookup.get("https://api.zbmath.org/v1/document/_search?x=1")
    metadata.get("https://api.zbmath.org/v1/document/2")
    assert [t for t, _ in asked] == [0.0, 1.0, 2.0]
    # another host is not held back by it, and keeps its own spacing
    fast = net.Service("openalex", None, transport, budget=b)
    fast.get("https://api.openalex.org/works/W1")
    fast.get("https://api.openalex.org/works/W2")
    assert [t for t, _ in asked[3:]] == [2.0, 2.2]
    # arXiv asks for three seconds, and both of its hosts are asked under that name
    arxiv = net.Service("arxiv", None, transport, budget=b)
    arxiv.get("https://export.arxiv.org/api/query?x=1")
    arxiv.get("https://export.arxiv.org/api/query?x=2")
    assert [t for t, _ in asked[5:]] == [2.2, 5.2]
    assert b.seconds("arxiv.org") == 3.0 and b.seconds("anything.else") == net.DEFAULT_SPACING


def test_every_service_and_downloader_shares_the_process_budget() -> None:
    assert net.Service("a").budget is net.BUDGET and net.Service("b").budget is net.BUDGET
    where = default_downloaders()
    assert where.arxiv.__self__.budget is net.BUDGET  # type: ignore[attr-defined]
    assert where.web.__self__.budget is net.BUDGET  # type: ignore[attr-defined]


def test_the_offline_transport_answers_from_a_directory_and_names_a_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://api.zbmath.org/v1/document/1"
    recorded = tmp_path / "recorded"
    path = net.answer_path(recorded, "zbmath", url)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"result": [{"id": 1}]}), encoding="utf-8")
    monkeypatch.setenv(net.OFFLINE, str(recorded))
    s = net.Service("zbmath", budget=budget())
    assert s.get_json(url) == {"result": [{"id": 1}]}
    with pytest.raises(net.ServiceError) as exc:
        s.get("https://api.zbmath.org/v1/document/2")
    assert "https://api.zbmath.org/v1/document/2" in str(exc.value) and str(recorded) in str(exc.value)
    # nothing else changes: with no directory named, the transport is a real GET
    monkeypatch.delenv(net.OFFLINE)
    assert net.transport_for("zbmath") is net.http


def test_two_budgets_sharing_a_directory_hold_each_other_back(tmp_path: Path) -> None:
    """A second process is the same client to a service, so the last request to a host is recorded where both can see it."""
    waited: list[float] = []
    first = HostBudget({"example.org": 30.0}, state_dir=tmp_path, sleep=waited.append)
    second = HostBudget({"example.org": 30.0}, state_dir=tmp_path, sleep=waited.append)

    first.take("https://example.org/a")
    second.take("https://example.org/b")
    assert waited and 25.0 < waited[-1] <= 30.5, "the second budget waited for the first process's request"

    elsewhere = HostBudget({"example.org": 30.0}, state_dir=None, sleep=waited.append)
    before = len(waited)
    elsewhere.take("https://example.org/c")
    assert len(waited) == before, "a budget with no shared state waits for nothing but itself"


def test_an_intermittent_refusal_is_asked_again_and_a_permanent_one_is_not() -> None:
    """arXiv's edge refuses weft intermittently rather than deterministically (record 2026-09-18), so a 406 is worth another ask; a 400 is the request's own fault and is not."""
    from weft.crawl.net import Service, ServiceError

    def flaky(codes: list[int]) -> Transport:
        def transport(url: str, headers: dict[str, str]) -> bytes:
            if codes:
                raise ServiceError(f"{url}: HTTP {codes[0]}", codes.pop(0))
            return b"ok"

        return transport

    service = Service("arxiv", None, flaky([406, 406]), budget=budget())
    assert service.get("https://export.arxiv.org/x") == b"ok"
    assert service.requests == 3 and service.failures == 2

    refused = Service("arxiv", None, flaky([400]), budget=budget())
    with pytest.raises(ServiceError):
        refused.get("https://export.arxiv.org/y")

    forever = Service("arxiv", None, flaky([406, 406, 406, 406]), budget=budget())
    with pytest.raises(ServiceError):
        forever.get("https://export.arxiv.org/z")
    assert forever.requests == 3, "three attempts and no more"


def test_the_transport_advertises_alpn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Python's urllib sends no ALPN extension and arXiv's edge answers such a handshake with 406 (record 2026-09-18), so every request weft makes goes through the opener carrying `net.CONTEXT`."""
    import ssl

    assert isinstance(net.CONTEXT, ssl.SSLContext)

    class FakeResponse:
        status = 200

        def read(self) -> bytes:
            return b"through the opener"

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    used: list[str] = []

    class FakeOpener:
        def open(self, req: object, timeout: int = 0) -> FakeResponse:
            used.append(getattr(req, "full_url", ""))
            return FakeResponse()

    monkeypatch.setattr(net, "OPENER", FakeOpener())
    assert net.http("https://example.org/x", {}) == b"through the opener"
    assert used == ["https://example.org/x"], "the metadata path uses the ALPN opener, not a bare urlopen"

    monkeypatch.setattr(download, "OPENER", FakeOpener())
    assert download.get("https://example.org/y", budget=budget()) == b"through the opener"
