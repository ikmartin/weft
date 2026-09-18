"""Reading a paper's files: decoding, comment blanking, and the closure of files a main file reaches.

An e-print unpacks to a directory of somebody else's files, so decoding tries UTF-8, then Mac Roman, then Latin-1 and never fails: a 1990s source with one high byte in an author's name is still read. Comments are blanked to spaces rather than removed, so every later stage sees the same offsets as the raw text and a statement can be sliced out of the file it was written in.
"""

from __future__ import annotations

import re
from pathlib import Path

from weft.tex.model import SourceFile
from weft.tex.tokenize import read_args, tokenize

TEXT_EXTS = (".tex", ".sty", ".cls", ".ltx", ".def", ".clo")
GRAPHIC_EXTS = (".pdf", ".eps", ".ps", ".png", ".jpg", ".jpeg", ".gif", ".bst", ".bbl")
_VERB_RE = re.compile(r"\\verb\*?(\S)(.*?)\1")
_VERBATIM_RE = re.compile(r"\\begin\{(verbatim\*?|lstlisting|comment|filecontents\*?)\}.*?\\end\{\1\}", re.S)


def decode(data: bytes) -> tuple[str, str]:
    """The text and the encoding it was read as. UTF-8 first; Mac Roman then Latin-1 accept every byte, so the first fallback always wins."""
    for enc in ("utf-8", "mac_roman", "latin-1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace"), "latin-1"


def _protected_ranges(text: str) -> list[tuple[int, int]]:
    ranges = [(m.start(), m.end()) for m in _VERBATIM_RE.finditer(text)]
    ranges += [(m.start(), m.end()) for m in _VERB_RE.finditer(text)]
    return sorted(ranges)


def blank_comments(text: str) -> str:
    """Replace every comment (from an unescaped % to end of line) with spaces, leaving verbatim regions untouched."""
    protected = _protected_ranges(text)
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "%":
            if any(a <= i < b for a, b in protected):
                i += 1
                continue
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def line_starts(text: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def read_source(root: Path, rel: str) -> SourceFile:
    """One file of a paper as the reader sees it.

    Parameters
    ----------
    root : Path
        The paper's directory; `rel` is taken against it.
    rel : str
        The file, as a posix path relative to `root`.

    Returns
    -------
    SourceFile
        Decoded text with CRLF normalised, its comment-blanked twin, and the line index.
    """
    abspath = root / rel
    text, enc = decode(abspath.read_bytes())
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return SourceFile(
        path=rel,
        abspath=abspath,
        text=text,
        clean=blank_comments(text),
        encoding=enc,
        line_starts=line_starts(text),
    )


def _resolve(root: Path, name: str, exts: tuple[str, ...]) -> Path | None:
    """A path the paper names, resolved inside the paper's own directory; None for an absolute path, an escape, or a name only the TeX distribution has."""
    name = name.strip()
    if not name or name.startswith("/") or ".." in Path(name).parts:
        return None
    for cand in (name, *(name + e for e in exts)):
        p = root / cand
        if p.is_file():
            return p
    return None


def closure_of(paper_dir: Path, main: Path) -> tuple[dict[str, Path], list[str]]:
    """Every file the main file reaches by \\input, \\usepackage or \\documentclass, keyed by paper-relative posix path.

    Parameters
    ----------
    paper_dir : Path
        The unpacked source directory; nothing outside it is followed.
    main : Path
        The file to start from.

    Returns
    -------
    tuple
        The files found, and the names that resolved outside `paper_dir` (which are reported and not read).

    See Also
    --------
    weft.tex.expand.expand_master : the same traversal, producing one text with a span map.
    """
    found: dict[str, Path] = {}
    outside: list[str] = []
    queue = [main]
    while queue:
        p = queue.pop()
        try:
            rel = p.resolve().relative_to(paper_dir.resolve()).as_posix()
        except ValueError:
            outside.append(str(p))
            continue
        if rel in found:
            continue
        found[rel] = p
        if p.suffix.lower() in GRAPHIC_EXTS:
            continue
        text = blank_comments(decode(p.read_bytes())[0])
        for t in tokenize(text):
            if t.kind != "cmd":
                continue
            if t.value in ("input", "include", "nest"):
                (arg,), _, _ = read_args(text, t.end, "m")
                if arg is None:
                    continue
                arg = arg.strip()
                if not arg:
                    m = re.match(r"\s*([^\s{}\\]+)", text[t.end :])
                    arg = m.group(1) if m else ""
                target = _resolve(paper_dir, arg, (".tex",))
                if target:
                    queue.append(target)
            elif t.value in ("usepackage", "RequirePackage"):
                (_, names), _, _ = read_args(text, t.end, "om")
                for n in (names or "").split(","):
                    target = _resolve(paper_dir, n, (".sty",))
                    if target:
                        queue.append(target)
            elif t.value in ("documentclass", "documentstyle", "LoadClass"):
                (_, name), _, _ = read_args(text, t.end, "om")
                target = _resolve(paper_dir, name or "", (".cls",))
                if target:
                    queue.append(target)
    return found, outside
