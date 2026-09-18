"""Running latexmk over a paper, for the numbers only.

Extraction does not need a PDF: it needs the `.aux`, because a number a paper prints is the paper's and a number weft counts is weft's guess at it. A corpus is a LaTeX run per work, though, so a compile is opt-in (`weft extract --compile`) and everything here returns a result rather than raising -- latexmk missing, a paper that does not build, a run that never ends -- so that one unbuildable paper costs its numbering and not the extraction.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ENGINE_FLAGS = {
    "pdflatex": ["-pdf"],
    "lualatex": ["-lualatex"],
    "xelatex": ["-xelatex"],
    "latex": ["-dvi"],
}


@dataclass
class CompileResult:
    """What a latexmk run produced, including when it produced nothing."""

    ok: bool
    engine: str
    outdir: Path
    returncode: int
    stdout: str = ""
    errors: list[str] = field(default_factory=list)
    aux: Path | None = None
    log: Path | None = None

    @property
    def first_error(self) -> str:
        return self.errors[0] if self.errors else (self.stdout.strip().splitlines() or ["latexmk failed"])[-1]


def which_latexmk() -> str | None:
    return shutil.which("latexmk")


def normalise_engine(engine: str | None, default: str = "pdflatex") -> str:
    """One of the four engines latexmk is driven with; anything else becomes the default."""
    e = (engine or default).strip().lower()
    return e if e in ENGINE_FLAGS else default


def compile_tex(root: Path, tex_rel: str, outdir: Path, engine: str = "pdflatex", timeout: int = 600) -> CompileResult:
    """Compile `tex_rel` (relative to `root`) with latexmk into `outdir`.

    Parameters
    ----------
    root : Path
        The paper's directory, which is also the working directory of the run, so the paper's own styles are found.
    tex_rel : str
        The main file, relative to `root`.
    outdir : Path
        Where latexmk writes; nothing is written into the paper's directory.
    engine : str, default 'pdflatex'
        pdflatex, lualatex, xelatex or latex.
    timeout : int, default 600
        Seconds before the run is abandoned.

    Returns
    -------
    CompileResult
        With `aux` set when an `.aux` was produced, which is the only thing extraction wants; a paper that errors out may still have one, so the run does not halt on the first error.
    """
    engine = normalise_engine(engine)
    exe = which_latexmk()
    outdir.mkdir(parents=True, exist_ok=True)
    if exe is None:
        return CompileResult(False, engine, outdir, 127, errors=["latexmk is not installed"])
    cmd = [exe, *ENGINE_FLAGS[engine], "-interaction=nonstopmode", f"-outdir={outdir}", tex_rel]
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CompileResult(False, engine, outdir, 124, errors=[f"latexmk did not run: {exc}"])
    stem = Path(tex_rel).stem
    log = outdir / f"{stem}.log"
    errors = re.findall(r"^! .*$", log.read_text(encoding="utf-8", errors="replace"), re.M) if log.exists() else []
    aux = outdir / f"{stem}.aux"
    return CompileResult(
        proc.returncode == 0,
        engine,
        outdir,
        proc.returncode,
        proc.stdout + proc.stderr,
        errors,
        aux if aux.exists() else None,
        log if log.exists() else None,
    )
