"""Fetching a planned crawl under its cap, and saying what is on disk.

Works are taken in the plan's order -- shallowest first, then most cited -- and downloaded until the cap is reached: an arXiv source where the work has an arXiv number, otherwise the open copy's PDF. Every work already downloaded counts against the cap before anything is fetched, so running fetch again never exceeds it, and a failure retried on a later run takes a place only if one is free. Each result is written into the work's record at once, so an interrupted fetch resumes by skipping what is on disk; a failure is recorded and reported, and does not stop the crawl unless arXiv refuses several downloads in a row, when every later request would be refused too. A downloaded source's `\\bibitem`s are read into its record, so a later plan knows its references.

A download produces a version: sources unpack to `works/<home>/<version-local>/src/` and PDFs to `works/<home>/<version-local>/paper.pdf`, where the version is the arXiv id with its `vN` or, for a work fetched as a PDF, the work key.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from weft.config import Settings
from weft.crawl.arxiv import eprint_url
from weft.crawl.bibitem import from_source
from weft.crawl.download import DownloadRefused, get, unpack
from weft.crawl.net import Service, ServiceError, transport_for
from weft.crawl.plan import Plan, load_plan
from weft.crawl.work import Record, Reference, load_all, version_dir
from weft.crawl.work import load as load_record
from weft.crawl.work import save as save_record

Download = Callable[[str], bytes]
# arXiv refuses every request for a while once it refuses one this way; going on would only record a failure for every work
STOP_AFTER = 3


def _via_download(url: str, headers: dict[str, str]) -> bytes:
    """The retrying downloader as a service transport, so downloads pass the same host budget as metadata requests."""
    try:
        return get(url)
    except DownloadRefused as exc:
        raise ServiceError(str(exc)) from exc


@dataclass
class Downloaders:
    """Where the bytes come from: arXiv, and anywhere else. Tests pass functions of their own."""

    arxiv: Download
    web: Download


def default_downloaders() -> Downloaders:
    """Downloads through the host budget, uncached, since the bytes are kept in the work's own directory."""
    arxiv = Service("arxiv-downloads", None, transport_for("arxiv-downloads", _via_download))
    web = Service("web-downloads", None, transport_for("web-downloads", _via_download))
    return Downloaders(arxiv=arxiv.get, web=web.get)


@dataclass
class FetchReport:
    """What one fetch did."""

    cap: int = 0
    fetched: int = 0
    already: int = 0
    failed: int = 0
    left_out: int = 0
    bytes: int = 0
    errors: list[str] = field(default_factory=list)
    stopped: str = ""  # why the fetch ended before the plan did: arXiv refusing, or an interruption

    def payload(self) -> dict[str, Any]:
        return {
            "cap": self.cap,
            "fetched": self.fetched,
            "already": self.already,
            "failed": self.failed,
            "left_out": self.left_out,
            "bytes": self.bytes,
            "errors": self.errors,
            "stopped": self.stopped,
        }

    def summary(self) -> str:
        lines = [
            f"fetched {self.fetched} ({self.bytes / 1e6:.1f} MB) · {self.already} already on disk · {self.failed} failed · {self.left_out} left out by the cap of {self.cap}"
        ]
        lines += [f"  {e}" for e in self.errors[:10]]
        if self.stopped:
            lines.append(f"stopped: {self.stopped}")
        return "\n".join(lines)


def fetch(settings: Settings, plan: Plan, *, downloaders: Downloaders | None = None) -> FetchReport:
    """Download what the plan selected, under `[crawl] cap`, resuming what is already on disk.

    Parameters
    ----------
    settings : Settings
        The corpus's settings; the cap and `works/` come from it.
    plan : Plan
        A plan made from these settings. The caller checks `plan.current(settings)` first.
    downloaders : Downloaders, optional
        Where the bytes come from; default the real ones. Tests pass their own, and no test touches the network.

    Returns
    -------
    FetchReport
        Each work's record is written as it is fetched, so an interrupted run resumes from what is on disk.

    See Also
    --------
    status : what is on disk after the fact.
    """
    works = settings.works_dir
    cap = max(0, settings.cap)
    where = downloaders if downloaders is not None else default_downloaders()
    report = FetchReport(cap=cap)
    loaded = [load_record(works / plan.homes.get(key, "") / "work.json") for key in plan.order]
    pending = [w for w in loaded if w is not None and w.downloadable]
    report.already = sum(1 for w in pending if w.downloaded)
    used = report.already
    refused = 0
    try:
        for record in pending:
            if refused >= STOP_AFTER:
                report.stopped = f"arXiv refused {refused} downloads in a row; run fetch again later to resume"
                break
            if record.downloaded:
                continue
            if used >= cap:
                report.left_out += 1
                continue
            kind = record.downloadable
            url = eprint_url(record.arxiv or "") if kind == "source" else record.open_pdf
            version = record.version_for(kind)
            dest = version_dir(works, record, version)
            try:
                if kind == "source":
                    data = where.arxiv(url)
                    unpack(data, dest / "src")
                    record.add_references(
                        [
                            Reference(
                                work=f"arxiv:{i.arxiv}" if i.arxiv else f"doi:{i.doi}" if i.doi else "",
                                citekey=i.key,
                                text=i.text,
                                identified_by="declared" if (i.arxiv or i.doi) else "",
                            )
                            for i in from_source(dest / "src")
                        ]
                    )
                else:
                    data = where.web(url)
                    if not data.startswith(b"%PDF"):
                        raise ServiceError(f"{url}: not a PDF")
                    dest.mkdir(parents=True, exist_ok=True)
                    (dest / "paper.pdf").write_bytes(data)
            except (ServiceError, OSError) as exc:
                record.download = {
                    "kind": kind,
                    "from": url,
                    "at": "",
                    "error": str(exc),
                    "tried": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                save_record(works, record)
                report.failed += 1
                report.errors.append(f"{record.ids[0]}: {exc}")
                refused = refused + 1 if kind == "source" else refused
                continue
            record.add_version(version)
            record.download = {
                "kind": kind,
                "from": url,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "bytes": len(data),
            }
            save_record(works, record)
            used += 1
            refused = 0 if kind == "source" else refused
            report.fetched += 1
            report.bytes += len(data)
    except KeyboardInterrupt:
        report.stopped = "interrupted; what was fetched is kept, and fetch resumes from there"
    return report


@dataclass
class Status:
    """What the corpus holds against its plan."""

    plan: dict[str, Any] | None
    works: int
    downloaded: int
    failed: int
    to_fetch: int
    beyond_cap: int
    metadata_only: int
    outside_plan: int

    def payload(self) -> dict[str, Any]:
        return {
            "plan": self.plan,
            "works": self.works,
            "downloaded": self.downloaded,
            "failed": self.failed,
            "to_fetch": self.to_fetch,
            "beyond_cap": self.beyond_cap,
            "metadata_only": self.metadata_only,
            "outside_plan": self.outside_plan,
        }

    def summary(self) -> str:
        lines = []
        if self.plan is None:
            lines.append("no crawl plan yet")
        else:
            stale = "" if self.plan["current"] else " · out of date: the settings or a seed bibliography changed"
            s = self.plan["settings"]
            lines.append(
                f"plan made {self.plan['made']} · depth {s['depth']} · subjects {' '.join(s['subjects'])} · cap {s['cap']}{stale}"
            )
        lines.append(
            f"{self.works} works · {self.downloaded} downloaded · {self.failed} failed · {self.to_fetch} to fetch under the cap, {self.beyond_cap} beyond it · {self.metadata_only} metadata only"
        )
        if self.outside_plan:
            lines.append(f"{self.outside_plan} recorded works are not in the plan (from an earlier plan)")
        return "\n".join(lines)


def status(settings: Settings) -> Status:
    """What is downloaded, failed, still to fetch under the cap, beyond it, metadata-only, and outside the plan.

    Parameters
    ----------
    settings : Settings
        The corpus's settings.

    Returns
    -------
    Status
        Reads `works/` and `crawl/plan.json` and nothing else; the network is not touched.
    """
    made = load_plan(settings)
    records = load_all(settings.works_dir)
    planned: list[Record] = [records[k] for k in made.order if k in records] if made else list(records.values())
    downloaded = sum(1 for w in planned if w.downloaded)
    failed = sum(1 for w in planned if w.download.get("error"))
    waiting = sum(1 for w in planned if w.downloadable and not w.downloaded)
    cap = max(0, settings.cap)
    to_fetch = min(waiting, max(0, cap - downloaded))
    return Status(
        plan={"made": made.made, "settings": made.settings, "current": made.current(settings)} if made else None,
        works=len(planned),
        downloaded=downloaded,
        failed=failed,
        to_fetch=to_fetch,
        beyond_cap=waiting - to_fetch,
        metadata_only=sum(1 for w in planned if not w.downloadable),
        outside_plan=len(records) - len(planned),
    )
