"""Writing a file whole or not at all.

A crawl writes a record after every download, so a fetch killed mid-write must not leave a record that no longer loads: the bytes go to a temporary file beside the target and are renamed over it, which is atomic on every filesystem weft runs on.
"""

from __future__ import annotations

import os
from pathlib import Path


def write_atomic(path: Path, data: str | bytes) -> None:
    """Write `data` to `path` by write-then-rename, creating the parent directories.

    Parameters
    ----------
    path : Path
        The file to write. A sibling `<name>.tmp` exists while the write is in progress.
    data : str or bytes
        Text is encoded as UTF-8.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if isinstance(data, str):
        tmp.write_text(data, encoding="utf-8")
    else:
        tmp.write_bytes(data)
    os.replace(tmp, path)
