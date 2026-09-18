"""The preamble closure of a paper's main file, and the theorem environments it declares.

The closure is the main file's text before `\\begin{document}` plus every local file it loads, transitively: `\\input`, `\\usepackage` and `\\RequirePackage` lists (one `\\usepackage` may name several packages, over several lines), and a local class file. Packages of the TeX distribution are never read, because they are not in the e-print and their definitions are not the paper's. Taxa come from `\\newtheorem`, `\\newtheorem*` and thmtools' `\\declaretheorem`; the style in force at the declaration decides the class.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from weft.tex.macros import expand, parse_macros
from weft.tex.model import Directive, Location, Macro, Problem, SourceFile, Taxon
from weft.tex.source import read_source
from weft.tex.tokenize import match_group, read_args, tokenize

STANDARD_STYLES = {"plain", "definition", "remark"}


@dataclass
class Fragment:
    """One stretch of one file that belongs to the closure."""

    file: str
    start: int
    end: int
    src: SourceFile


@dataclass
class PreambleClosure:
    """What the paper declares before its body: its theorem environments, its macros, and the engine it asks for."""

    master: str
    fragments: list[Fragment] = field(default_factory=list)
    taxa: dict[str, Taxon] = field(default_factory=dict)
    macros: dict[str, Macro] = field(default_factory=dict)
    engine: str | None = None
    custom_styles: set[str] = field(default_factory=set)
    problems: list[Problem] = field(default_factory=list)

    @property
    def files(self) -> list[str]:
        return [f.file for f in self.fragments]

    def clean_text(self) -> str:
        return "\n".join(f.src.clean[f.start : f.end] for f in self.fragments)

    def raw_text(self) -> str:
        return "\n".join(f.src.text[f.start : f.end] for f in self.fragments)


def document_start(src: SourceFile) -> int | None:
    """The offset of `\\begin{document}`, or None when the file has none."""
    m = re.search(r"\\begin\s*\{document\}", src.clean)
    return m.start() if m else None


def _local(root: Path, name: str, exts: tuple[str, ...]) -> str | None:
    name = name.strip()
    if not name or (name.startswith("/") or ".." in Path(name).parts):
        return None
    for ext in exts:
        cand = name if name.endswith(ext) else name + ext
        if (root / cand).is_file():
            return Path(cand).as_posix()
    return None


def _load(root: Path, rel: str, files: dict[str, SourceFile]) -> SourceFile:
    """A file from the table, or one read on demand; a style or class file is not part of the paper's prose and is never added to the table."""
    if rel in files:
        return files[rel]
    return read_source(root, rel)


def build_closure(
    master: SourceFile, root: Path, files: dict[str, SourceFile], directives: list[Directive]
) -> PreambleClosure:
    """Collect the closure, then read taxa and macros over it in inclusion order.

    Parameters
    ----------
    master : SourceFile
        The paper's main file.
    root : Path
        The paper's directory.
    files : dict[str, SourceFile]
        Files already read, by paper-relative path.
    directives : list of Directive
        The main file's directives; `% !TEX program` names the engine.

    Returns
    -------
    PreambleClosure
        Its taxa keyed by environment name, its macros keyed by macro name.
    """
    closure = PreambleClosure(master=master.path)
    seen: set[str] = set()
    doc = document_start(master)
    _collect(master, 0, doc if doc is not None else len(master.clean), root, files, closure, seen)
    closure.macros = parse_macros(closure.clean_text())
    for d in directives:
        if d.form == "tex" and d.key == "program" and d.file == master.path:
            closure.engine = d.value
    _parse_taxa(closure)
    _wrapped_taxa(closure)
    return closure


def _collect(
    src: SourceFile,
    start: int,
    end: int,
    root: Path,
    files: dict[str, SourceFile],
    closure: PreambleClosure,
    seen: set[str],
) -> None:
    key = f"{src.path}:{start}"
    if key in seen:
        return
    seen.add(key)
    closure.fragments.append(Fragment(src.path, start, end, src))
    text = src.clean
    for t in tokenize(text[start:end]):
        if t.kind != "cmd":
            continue
        pos = start + t.end
        if t.value in ("usepackage", "RequirePackage"):
            (_, names), _, _ = read_args(text, pos, "om")
            for pkg in (names or "").split(","):
                rel = _local(root, pkg, (".sty",))
                if rel:
                    child = _load(root, rel, files)
                    _collect(child, 0, len(child.clean), root, files, closure, seen)
        elif t.value in ("documentclass", "documentstyle", "LoadClass"):
            (_, name), _, _ = read_args(text, pos, "om")
            rel = _local(root, name or "", (".cls",))
            if rel:
                child = _load(root, rel, files)
                _collect(child, 0, len(child.clean), root, files, closure, seen)
        elif t.value in ("input", "include"):
            (name,), _, _ = read_args(text, pos, "m")
            if name is None:
                continue
            rel = _local(root, name, ("", ".tex"))
            if rel:
                child = _load(root, rel, files)
                if child.path == src.path:
                    continue
                _collect(child, 0, len(child.clean), root, files, closure, seen)


_STYLE = re.compile(r"\\(newtheoremstyle|theoremstyle|newtheorem|declaretheorem)(\*?)(?![A-Za-z@])")
_WRAPPER = re.compile(
    r"\\newenvironment\*?\s*\{([A-Za-z][A-Za-z0-9*-]*)\}(?:\s*\[\d+\])?(?:\s*\[[^\]]*\])?\s*(\{)\s*\\begin\s*\{([A-Za-z*]+)\}"
)
_BOLD_NAME = re.compile(r"\\(?:bf|textbf\s*\{|bfseries)\s*([A-Za-z][A-Za-z ]*?)\s*[.:~}]")


def _display_name(raw: str, closure: PreambleClosure, file: str, offset: int, env: str) -> str:
    """The display name of a taxon: the text as written, or a zero-argument macro's expansion, or the environment name capitalised."""
    name = raw.strip()
    if not name.startswith("\\"):
        return re.sub(r"\s+", " ", name)
    m = re.match(r"\\([A-Za-z@]+)\s*$", name)
    macro = closure.macros.get(m.group(1)) if m else None
    if macro is not None and macro.args == 0:
        expanded = expand(macro, []).strip()
        if "\\" not in expanded and "#" not in expanded and expanded:
            return expanded
    closure.problems.append(
        Problem(
            "info",
            "taxon-name-macro",
            f"display name of environment {env} is the macro {name}; using {env.capitalize()}",
            [Location(file, 0)],
        )
    )
    return env.capitalize()


def _parse_taxa(closure: PreambleClosure) -> None:
    style = "plain"
    for frag in closure.fragments:
        text = frag.src.clean
        pos = frag.start
        while True:
            m = _STYLE.search(text, pos, frag.end)
            if not m:
                break
            cmd, starred = m.group(1), bool(m.group(2))
            after = m.end()
            if cmd == "theoremstyle":
                (val,), _, after = read_args(text, after, "m")
                style = (val or "plain").strip()
            elif cmd == "newtheoremstyle":
                (val,), _, after = read_args(text, after, "m")
                if val:
                    closure.custom_styles.add(val.strip())
            elif cmd == "newtheorem":
                (env, counter, name, within), _, after = read_args(text, after, "momo")
                if env and name is not None:
                    env_name = env.strip()
                    disp = _display_name(name, closure, frag.file, m.start(), env_name)
                    closure.taxa[env_name] = Taxon(
                        env_name,
                        disp,
                        _style_class(style),
                        not starred,
                        frag.file,
                        m.start(),
                        counter.strip() if counter else None,
                        within.strip() if within else None,
                    )
            else:  # declaretheorem
                (opts, env), _, after = read_args(text, after, "om")
                if env:
                    env_name = env.strip()
                    kv: dict[str, str] = dict(re.findall(r"(\w+)\s*=\s*([^,]+)", opts or ""))
                    disp = _display_name(kv.get("name", env_name.capitalize()), closure, frag.file, m.start(), env_name)
                    st = kv.get("style", style).strip()
                    numbered = kv.get("numbered", "yes").strip() != "no"
                    parent = (kv.get("parent") or kv.get("within") or "").strip() or None
                    shared = (kv.get("sibling") or kv.get("numberlike") or "").strip() or None
                    closure.taxa[env_name] = Taxon(
                        env_name, disp, _style_class(st), numbered, frag.file, m.start(), shared, parent
                    )
            pos = max(after, m.end())


def _style_class(style: str) -> str:
    return style if style in STANDARD_STYLES else "plain"


def _wrapped_taxa(closure: PreambleClosure) -> None:
    """Register environments a paper defines as a wrapper around a declared theorem environment.

    `\\newenvironment{lemma}{\\begin{counter} {\\bf Lemma.}}{\\end{counter}}` is how a paper written before amsthm was universal declares a lemma: the number comes from a `\\newtheorem` environment shared by everything, and the display name is set in bold by hand. Without this the document's `\\begin{lemma}` is not theorem-like at all and the paper yields nothing. Only a wrapper whose body *opens* with the inner environment counts, so a `proof` environment or a decoration around prose is not mistaken for a result, and the display name is the first bold word of the wrapper, falling back to the environment's own name.
    """
    text = closure.clean_text()
    for m in _WRAPPER.finditer(text):
        env, inner = m.group(1), m.group(3)
        base = closure.taxa.get(inner)
        if base is None or env in closure.taxa or env == "proof":
            continue
        # the display name is looked for inside the wrapper's own begin-code and no further, or the next definition's bold word would name this one
        end = match_group(text, m.start(2))
        bold = _BOLD_NAME.search(text[m.end() : end - 1]) if end > 0 else None
        name = (
            bold.group(1).strip() if bold and bold.group(1).strip() else env.rstrip("*").replace("-", " ").capitalize()
        )
        closure.taxa[env] = Taxon(
            env, name, base.style, base.numbered, base.file, m.start(), base.counter or inner, base.within
        )
