"""Getting the bytes: an arXiv e-print or an open PDF, and unpacking what arrives.

Downloads pass the same host budget as every metadata request, so a fetch and a plan running together cannot make arXiv throttle weft's client. A 406 or a 429 under load is retried after a pause, since arXiv answers a burst that way and the work is still there a moment later.
"""

from __future__ import annotations

import gzip
import io
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from weft.crawl.net import BUDGET, USER_AGENT, HostBudget

# HTTP codes that mean "too fast" or "try again", as opposed to "no such thing"
# 500s and 429 are worth another ask; a 406 from arXiv means it is throttling this client, and asking again sooner only earns another.
_RETRY = (429, 500, 502, 503)
# Seconds between bulk downloads of one host, beyond what its metadata queries take: arXiv refuses e-prints asked for every three seconds.
BULK_SPACING = 15.0


class DownloadRefused(Exception):
    """The bytes could not be had: a refusal, a timeout, or an archive weft will not unpack."""


def get(url: str, attempts: int = 3, *, budget: HostBudget | None = None) -> bytes:
    """The bytes at `url`, with weft's User-Agent.

    Parameters
    ----------
    url : str
        What to download.
    attempts : int, default 3
        How many times to ask; a retryable refusal pauses three seconds longer each time.

    Returns
    -------
    bytes
        The whole body.

    Raises
    ------
    DownloadRefused
        The last refusal, named with the URL.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    where = budget if budget is not None else BUDGET
    last: Exception | None = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(3.0 * attempt)
        where.take(url, BULK_SPACING)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
                return bytes(resp.read())
        except urllib.error.HTTPError as exc:
            last = DownloadRefused(f"{url}: HTTP {exc.code} {exc.reason}")
            if exc.code not in _RETRY:
                break
        except urllib.error.URLError as exc:
            last = DownloadRefused(f"{url}: {exc.reason}")
    raise last if last is not None else DownloadRefused(f"{url}: no attempt was made")


def unpack(data: bytes, dest: Path) -> list[Path]:
    """Unpack an arXiv e-print under `dest`, refusing paths that escape it.

    Parameters
    ----------
    data : bytes
        A gzipped tar, a gzipped single file, or a PDF, which is what arXiv's e-print endpoint answers with.
    dest : Path
        The directory to write into; created if absent.

    Returns
    -------
    list of Path
        The files written. A symlink, a hard link or a member whose path leaves `dest` is skipped, because a corpus unpacks other people's archives.
    """
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if data[:4] == b"%PDF":
        p = dest / "paper.pdf"
        p.write_bytes(data)
        return [p]
    try:
        raw = gzip.decompress(data)
    except OSError:
        raw = data
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
            for member in tar.getmembers():
                target = (dest / member.name).resolve()
                if not str(target).startswith(str(dest.resolve())) or member.issym() or member.islnk():
                    continue
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    f = tar.extractfile(member)
                    if f is not None:
                        target.write_bytes(f.read())
                        written.append(target)
        return written
    except tarfile.TarError:
        pass
    p = dest / "main.tex"
    p.write_bytes(raw)
    return [p]
