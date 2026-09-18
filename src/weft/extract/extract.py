"""Reading one paper's LaTeX source into results: statements, their proofs, and the digest file that holds them.

The paper's closure is read with the LaTeX layer (preamble, macros, environments, sections, inclusion expansion); results are numbered from the paper's `.aux` where there is one and from the amsthm counter emulation otherwise; every theorem-like environment becomes a node with a slugged id, a locator title carrying the citation, its statement with the paper's simple macros expanded and its labels prefixed, its proof where the corpus keeps proofs, and a `\\uses` line naming the results its proof refers to. What cannot be expanded goes in the macro block.

This is the other implementation of docs/specs/digest.md, loom's `digest extract` being the first. Where the two disagree, one of them has a bug; the numbered statements of the spec are what both are tested against. The differences that are by design are two: weft keeps proofs, because a library that cannot show why a theorem is true cannot answer whether an argument transfers, and weft writes no placeholder node -- no overview, no standing-assumptions node -- because §4.6 forbids a digest node from carrying a proof obligation and a corpus has no author to hand one to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from weft.extract.counters import Numbering
from weft.tex.aux import AuxNumber
from weft.tex.digests import ALWAYS_LOADED, loaded_packages
from weft.tex.directives import parse_directives
from weft.tex.envtree import FileEnvs, labels_in, norm_label, scan_environments
from weft.tex.expand import Expansion, expand_master
from weft.tex.macros import expand as expand_macro
from weft.tex.macros import expand_definition_aliases
from weft.tex.model import Env, Macro, SourceFile, Taxon
from weft.tex.preamble import PreambleClosure, build_closure, document_start
from weft.tex.sections import SectionUnit, find_sections
from weft.tex.source import TEXT_EXTS, closure_of, read_source
from weft.tex.tokenize import match_group, read_args

# docs/specs/digest.md §3.2: the fixed abbreviation map. An environment outside it contributes its own slugged name, or `res`.
ABBREV = {
    "theorem": "thm",
    "lemma": "lem",
    "proposition": "prop",
    "corollary": "cor",
    "definition": "def",
    "remark": "rem",
    "example": "ex",
    "construction": "constr",
    "conjecture": "conj",
}
PROOF_MODES = ("verbatim", "none")

_CMD = re.compile(r"\\([A-Za-z@]+)")
_REF = re.compile(r"\\(ref|eqref|cref|Cref|autoref|vref)\s*\{([^}]*)\}")
_LABEL = re.compile(r"\\label\s*\{([^}]*)\}")
_DOCUMENTCLASS = re.compile(r"\\document(?:class|style)\s*(?:\[[^\]]*\])?\s*\{")
_DOCUMENT = re.compile(r"\\begin\s*\{document\}")
_UNSAFE_PREFIX = re.compile(r"[^A-Za-z0-9.-]+")

# Packages about the page, the fonts or the bibliography, which a statement never needs; the rest of the paper's \usepackage lines become `requires:` (§2.8).
PRESENTATION = {
    "inputenc",
    "fontenc",
    "lmodern",
    "textcomp",
    "geometry",
    "hyperref",
    "microtype",
    "xcolor",
    "color",
    "graphicx",
    "graphics",
    "url",
    "cleveref",
    "enumitem",
    "setspace",
    "titlesec",
    "fancyhdr",
    "appendix",
    "natbib",
    "biblatex",
    "babel",
    "csquotes",
    "booktabs",
    "caption",
    "subcaption",
    "float",
    "times",
    "mathptmx",
    "fullpage",
    "titling",
    "tocloft",
    "todonotes",
    "showkeys",
    "lineno",
    "epstopdf",
    "xspace",
    "etoolbox",
    "parskip",
    "indentfirst",
    "amsrefs",
    "cite",
    "authblk",
    "datetime",
    "lastpage",
    "afterpage",
    "pdfsync",
    "placeins",
    "framed",
    "mdframed",
    "tcolorbox",
    "comment",
    "verbatim",
    "listings",
    "environ",
    "ifthen",
    "calc",
    "kvoptions",
    "xkeyval",
}


class Refused(Exception):
    """Something about the source means weft will not guess: no main file, or several that could each be one."""


@dataclass(frozen=True)
class Provenance:
    """What a digest's header will say (docs/specs/digest.md §2), decided by the caller from the corpus's record."""

    digest: str  # the citekey, or the work's global identifier where the corpus has no citekey (§2.1)
    prefix: str  # the slug every id in the file carries (§2.2)
    extracted_from: str  # the artifact the statements were read from (§2.3)
    published_as: str = ""  # what a bibliography cites, when that differs (§2.4)
    proofs: str = "verbatim"  # §2.6
    created: str = ""  # ISO 8601 (§2.7)
    tool: str = ""  # the extractor and its version; an unknown directive a reader ignores (§2.10)


@dataclass
class Proof:
    """One `proof` environment attached to a statement: its optional argument and its body, both verbatim."""

    optarg: str = ""
    body: str = ""


@dataclass
class Statement:
    """One extracted result: what `results.json` records, plus what the digest file needs to write it."""

    local: str  # "thm-4.1", the paper-local part of the key (§3.1)
    taxon: str  # the display name: "Theorem"
    env: str  # the paper's own environment name
    number: str = ""
    title: str = ""  # the paper's own optional-argument title, where it gave one
    statement: str = ""
    aliases: list[str] = field(default_factory=list)  # the paper's own labels, as the paper wrote them (§3.5)
    page: str = ""
    proofs: list[Proof] = field(default_factory=list)
    uses: list[str] = field(default_factory=list)  # digest ids, from the references in the proof (§4.5)
    file: str = ""
    order: float = 0.0

    @property
    def proof_text(self) -> str:
        """Every attached proof's body, in document order; '' under `proofs: none` or when the paper proves nothing here."""
        return "\n\n".join(p.body for p in self.proofs if p.body)


@dataclass
class Report:
    """What one extraction did, for the command line and for the record."""

    main: str = ""
    numbering: str = "emulated"
    proofs: str = "verbatim"
    by_taxon: dict[str, int] = field(default_factory=dict)
    sections: int = 0
    proofs_kept: int = 0
    uses: int = 0
    expanded: set[str] = field(default_factory=set)
    block: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    taxa: dict[str, str] = field(default_factory=dict)  # environment name -> display name, for a consuming document
    skipped: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.by_taxon.values())

    def summary(self) -> str:
        by = ", ".join(f"{n} {t}" for t, n in sorted(self.by_taxon.items(), key=lambda x: (-x[1], x[0])))
        lines = [f"{self.total} results ({by or 'none'}), {self.sections} sections, numbering {self.numbering}"]
        lines.append(f"Proofs: {self.proofs}, {self.proofs_kept} kept; \\uses recorded: {self.uses}")
        lines.append(
            f"Macros expanded: {len(self.expanded)}; macro block: {len(self.block)} definition(s)"
            + (f" ({', '.join(self.block)})" if self.block else "")
        )
        lines.append(
            "Packages required: " + (", ".join(self.requires) if self.requires else "none beyond amsmath, amsthm")
        )
        lines.extend(f"Skipped: {s}" for s in self.skipped)
        return "\n".join(lines)


@dataclass
class Extraction:
    """One version's extraction: the digest file's text, the results as data, and the report."""

    digest: str
    statements: list[Statement]
    report: Report


@dataclass
class Paper:
    """One paper's source as the extractor reads it: its files, its main file, and everything derived from them."""

    dir: Path
    main: str
    files: dict[str, SourceFile]
    closure: PreambleClosure
    exp: Expansion
    units: list[SectionUnit]
    envs: dict[str, FileEnvs]

    @property
    def taxa(self) -> dict[str, Taxon]:
        return self.closure.taxa


def slug_prefix(text: str) -> str:
    """The id prefix a version identifier gives: `arxiv:1709.09864v2` becomes `arxiv-1709.09864v2`.

    Letters, digits, dots and hyphens survive, which is exactly the id grammar of §3.1, and anything else becomes one hyphen. A dot is kept rather than folded because a version's number is easier to recognise with it and the grammar allows it.
    """
    return _UNSAFE_PREFIX.sub("-", text.strip()).strip("-.") or "work"


def find_main(paper_dir: Path) -> str:
    """The paper's main file, as a path relative to `paper_dir`.

    Parameters
    ----------
    paper_dir : Path
        An unpacked e-print: a directory, because that is what an arXiv source is.

    Returns
    -------
    str
        The `.tex` file that declares the document class, preferring one that also opens the document body.

    Raises
    ------
    Refused
        When no file declares a document class, or when several do and nothing chooses between them; the message names the candidates, because guessing one would attribute a paper's results to the wrong artifact.
    """
    if not paper_dir.is_dir():
        raise Refused(f"{paper_dir} is not a directory")
    candidates: list[tuple[str, bool]] = []
    for path in sorted(paper_dir.rglob("*.tex")):
        rel = path.relative_to(paper_dir).as_posix()
        try:
            head = path.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        if _DOCUMENTCLASS.search(head):
            candidates.append((rel, bool(_DOCUMENT.search(head))))
    if not candidates:
        raise Refused("no .tex file declares \\documentclass")
    with_body = [rel for rel, body in candidates if body]
    chosen = with_body or [rel for rel, _ in candidates]
    if len(chosen) > 1:
        raise Refused("several files could be the main file: " + ", ".join(sorted(chosen)))
    return chosen[0]


def read_paper(paper_dir: Path, main_rel: str | None = None) -> Paper:
    """Read a paper's source: its files, its preamble closure, its expansion, its sections and its environments.

    Parameters
    ----------
    paper_dir : Path
        The unpacked source directory.
    main_rel : str, optional
        The main file; found with `find_main` when not given.

    Returns
    -------
    Paper
        Everything the extractor needs, read once.

    See Also
    --------
    find_main : how the main file is chosen, and when that is refused.
    """
    main_rel = main_rel or find_main(paper_dir)
    main_path = (paper_dir / main_rel).resolve()
    found, _outside = closure_of(paper_dir, main_path)
    files: dict[str, SourceFile] = {}
    for rel, path in found.items():
        if path.suffix.lower() in TEXT_EXTS:
            files[rel] = read_source(paper_dir, rel)
    if main_rel not in files:
        files[main_rel] = read_source(paper_dir, main_rel)
    master = files[main_rel]
    closure = build_closure(master, paper_dir, files, parse_directives(master))
    exp = expand_master(master, paper_dir, files)
    units = find_sections(exp, files)
    theorem_names = set(closure.taxa)
    envs: dict[str, FileEnvs] = {}
    for rel in [main_rel, *[f for f in exp.reached if f != main_rel]]:
        if rel not in files:
            continue
        src = files[rel]
        body = document_start(src) if rel == main_rel else None
        envs[rel] = scan_environments(src, theorem_names, body or 0)
    return Paper(dir=paper_dir, main=main_rel, files=files, closure=closure, exp=exp, units=units, envs=envs)


def _body_text(env: Env, clean: str) -> str:
    """An environment's own text: its body minus any theorem-like environment or proof nested in it, which are results of their own."""
    pieces: list[str] = []
    pos = env.body_start
    for child in env.children:
        if child.theorem_like or child.is_proof:
            if child.start > pos:
                pieces.append(clean[pos : child.start])
            pos = child.end
    if env.body_end > pos:
        pieces.append(clean[pos : env.body_end])
    text = "".join(pieces)
    lines = [ln.rstrip() for ln in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def expand_macros(text: str, macros: dict[str, Macro], max_passes: int = 8) -> tuple[str, set[str]]:
    """Textually expand the paper's own macros in `text`; returns the text and the names that were expanded."""
    expanded: set[str] = set()
    for _ in range(max_passes):
        out: list[str] = []
        pos = 0
        changed = False
        while True:
            m = _CMD.search(text, pos)
            if m is None:
                out.append(text[pos:])
                break
            mac = macros.get(m.group(1))
            if mac is None:
                out.append(text[pos : m.end()])
                pos = m.end()
                continue
            has_default = mac.default is not None
            spec = ("o" if has_default else "") + "m" * max(mac.args - (1 if has_default else 0), 0)
            vals, _spans, after = read_args(text, m.end(), spec) if spec else ([], [], m.end())
            args: list[str] = []
            if has_default:
                args.append(vals[0] if vals and vals[0] is not None else (mac.default or ""))
                vals = vals[1:]
            if any(v is None for v in vals):
                out.append(text[pos : m.end()])
                pos = m.end()
                continue
            args.extend(v or "" for v in vals)
            # \xspace is a no-op in mathematics and harmful before ^ or _, so it goes rather than travelling into a statement
            body = re.sub(r"\\xspace(?![A-Za-z@])", "", expand_macro(mac, args))
            out.append(text[pos : m.start()])
            out.append(body)
            if body and body[-1].isalpha() and after < len(text) and text[after].isalpha():
                out.append(" ")
            pos = after
            changed = True
            expanded.add(m.group(1))
        text = "".join(out)
        if not changed:
            break
    return text, expanded


def _definitions(raw: str) -> dict[str, str]:
    """Raw definition text per macro name in a preamble closure, for the macro block; the last definition of a name wins."""
    raw = expand_definition_aliases(raw)
    defs: dict[str, str] = {}
    for m in re.finditer(r"\\(?:new|renew|provide)command\*?\s*\{?\\([A-Za-z@]+)\}?", raw):
        pos = m.end()
        while True:
            _v, _s, after = read_args(raw, pos, "o")
            if after == pos:
                break
            pos = after
        p = raw.find("{", pos)
        if p < 0:
            continue
        end = match_group(raw, p)
        if end > 0:
            defs[m.group(1)] = raw[m.start() : end]
    for m in re.finditer(r"\\def\s*\\([A-Za-z@]+)", raw):
        p = raw.find("{", m.end())
        if p < 0:
            continue
        end = match_group(raw, p)
        if end > 0:
            defs[m.group(1)] = raw[m.start() : end]
    for m in re.finditer(r"\\DeclareMathOperator(\*?)\s*\{\\([A-Za-z@]+)\}\s*\{", raw):
        end = match_group(raw, m.end() - 1)
        if end > 0:
            body = raw[m.end() : end - 1]
            defs[m.group(2)] = f"\\newcommand{{\\{m.group(2)}}}{{\\operatorname{m.group(1)}{{{body}}}}}"
    for m in re.finditer(r"\\let\s*\\([A-Za-z@]+)\s*=?\s*\\[A-Za-z@]+", raw):
        defs[m.group(1)] = m.group(0)
    for m in re.finditer(
        r"\\(?:New|Renew|Provide|Declare)DocumentCommand\s*\{?\\([A-Za-z@]+)\}?\s*\{[^}]*\}\s*\{", raw
    ):
        end = match_group(raw, m.end() - 1)
        if end > 0:
            defs[m.group(1)] = raw[m.start() : end]
    return defs


def _env_definitions(raw: str) -> dict[str, str]:
    """Raw definition text per environment the paper declares with `\\newenvironment` or enumitem's `\\newlist` (with its `\\setlist` lines), keyed by environment name (§5.3)."""
    defs: dict[str, str] = {}
    for m in re.finditer(r"\\(?:new|renew)environment\*?\s*\{([A-Za-z*]+)\}", raw):
        pos = m.end()
        while True:
            _v, _s, after = read_args(raw, pos, "o")
            if after == pos:
                break
            pos = after
        p1 = raw.find("{", pos)
        e1 = match_group(raw, p1) if p1 >= 0 else -1
        p2 = raw.find("{", e1) if e1 > 0 else -1
        e2 = match_group(raw, p2) if p2 >= 0 else -1
        if e2 > 0:
            defs[m.group(1)] = raw[m.start() : e2]
    for m in re.finditer(r"\\newlist\s*\{([A-Za-z*]+)\}\s*\{[^}]*\}\s*\{\d+\}", raw):
        name = m.group(1)
        parts = [m.group(0)]
        for sm in re.finditer(r"\\setlist\s*\[" + re.escape(name) + r"(?:,[^\]]*)?\]\s*\{", raw):
            end = match_group(raw, sm.end() - 1)
            if end > 0:
                parts.append(raw[sm.start() : end])
        defs[name] = "\n".join(parts)
    return defs


def extract(paper: Paper, prov: Provenance, *, aux: dict[str, AuxNumber] | None = None) -> Extraction:
    """Extract one paper: its statements, its proofs where the policy keeps them, and the digest file that holds both.

    Parameters
    ----------
    paper : Paper
        The read source, from `read_paper`.
    prov : Provenance
        What the header will say; `prov.proofs` is the policy, 'verbatim' or 'none'.
    aux : dict[str, AuxNumber], optional
        Numbers from the paper's own compile, by label. Where a result carries a label the `.aux` knows, that number wins and the emulation resynchronises to it; without any, every number is emulated.

    Returns
    -------
    Extraction
        The digest text, the statements as data, and the report.

    See Also
    --------
    read_paper : reading the source this works over.
    weft.extract.write.write_version : writing the result into a corpus.
    """
    if prov.proofs not in PROOF_MODES:
        raise ValueError(f"proofs must be one of {PROOF_MODES}, not {prov.proofs!r}")
    aux = aux or {}
    report = Report(main=paper.main, numbering="compiled" if aux else "emulated", proofs=prov.proofs)
    report.taxa = {t.env: t.name for t in paper.taxa.values()}
    report.problems = [f"{p.code}: {p.message}" for p in (*paper.exp.problems, *paper.closure.problems)]
    exp, files, taxa = paper.exp, paper.files, paper.taxa

    events: list[tuple[float, int, str, object]] = []
    for u in paper.units:
        events.append((float(u.exp_start), 0, "heading", u))
    for m in re.finditer(r"\\appendix\b", exp.text):
        events.append((float(m.start()), 0, "appendix", None))
    for rel, fe in paper.envs.items():
        for env in fe.theorem_envs:
            e = exp.exp_offset(rel, env.start)
            if e is None:
                continue
            events.append((float(e), 1, "env", (rel, env)))
    events.sort(key=lambda x: (x[0], x[1]))

    num = Numbering(taxa)
    unit_numbers: dict[int, str | None] = {}
    found: list[tuple[Statement, str, Env]] = []  # the statement, its file, and the environment it came from
    label_to_id: dict[str, str] = {}
    starred = 0
    for off, _p, kind, payload in events:
        if kind == "appendix":
            num.mark_appendix()
            continue
        if kind == "heading":
            unit = payload
            assert isinstance(unit, SectionUnit)
            n = num.heading(unit.name, unit.starred)
            if unit.labels and unit.labels[0] in aux and aux[unit.labels[0]].number:
                n = aux[unit.labels[0]].number
            unit_numbers[id(unit)] = n
            continue
        assert isinstance(payload, tuple)
        rel, env = payload
        taxon = taxa[env.name]
        n = num.theorem(taxon)
        clean = files[rel].clean
        labels = [lab for lab, _ in labels_in(clean, env.own_ranges())]
        page: int | None = None
        for lab in labels:
            an = aux.get(lab)
            if an is not None and an.number and n is not None:
                n = an.number
                num.resync(taxon, n)
                page = an.page
                break
            if an is not None and an.page is not None:
                page = an.page
        abbrev = ABBREV.get(taxon.name.lower(), re.sub(r"[^a-z0-9]", "", taxon.env.lower()) or "res")
        if n is None:
            starred += 1
            local = f"{abbrev}-star-{starred}"
        else:
            local = f"{abbrev}-{n}"
        if any(s.local == local for s, _, _ in found):
            report.skipped.append(f"{taxon.name} {n} at {rel}:{files[rel].line_of(env.start)}: duplicate number {n}")
            continue
        st = Statement(
            local=local,
            taxon=taxon.name,
            env=taxon.env,
            number=n or "",
            aliases=list(labels),
            page=str(page) if page is not None else "",
            file=rel,
            order=off,
        )
        found.append((st, rel, env))
        for lab in labels:
            label_to_id.setdefault(lab, f"{prov.prefix}-{local}")

    units_of: dict[str, SectionUnit | None] = {}
    for st, _rel, _env in found:
        containing = [
            u for u in paper.units if u.level <= 2 and u.exp_start <= st.order < u.exp_end and unit_numbers.get(id(u))
        ]
        units_of[st.local] = max(containing, key=lambda u: u.level) if containing else None

    body_labels: set[str] = set()
    for _st, rel, env in found:
        for m in _LABEL.finditer(_body_text(env, files[rel].clean)):
            body_labels.add(norm_label(m.group(1)))

    def rewrite(text: str) -> str:
        """One statement, proof or title as the digest carries it: the paper's macros expanded, its labels prefixed, its cross-references pointed at digest ids."""
        text, names = expand_macros(text, paper.closure.macros)
        report.expanded.update(names)
        text = _LABEL.sub(lambda m: f"\\label{{{prov.prefix}-{norm_label(m.group(1))}}}", text)

        def ref_repl(m: re.Match[str]) -> str:
            cmd = m.group(1)
            outs: list[str] = []
            for raw_lab in m.group(2).split(","):
                lab = norm_label(raw_lab)
                if not lab:
                    continue
                if lab in label_to_id:
                    outs.append(f"\\ref{{{label_to_id[lab]}}}")
                elif lab in body_labels:
                    outs.append(f"\\{'eqref' if cmd == 'eqref' else 'ref'}{{{prov.prefix}-{lab}}}")
                else:
                    an = aux.get(lab)
                    number = an.number if an is not None and an.number else "??"
                    outs.append(f"({number})" if cmd == "eqref" else number)
            return ", ".join(outs)

        return _REF.sub(ref_repl, text)

    by_env = {(rel, env.start): st for st, rel, env in found}
    env_of = {id(st): env for st, _rel, env in found}
    for rel, fe in paper.envs.items():
        for proof in fe.proofs:
            att = fe.attachments.get(proof.start)
            stmt = att.statement if att is not None else None
            if stmt is None and att is not None and att.fallback is not None:
                stmt = att.fallback.statement
            if stmt is None:
                continue
            hit = by_env.get((rel, stmt.start))
            if hit is None:
                continue
            ptext, _ = expand_macros(files[rel].clean[proof.start : proof.end], paper.closure.macros)
            for m in _REF.finditer(ptext):
                for raw_lab in m.group(2).split(","):
                    lab = norm_label(raw_lab)
                    target = label_to_id.get(lab)
                    if target and target != f"{prov.prefix}-{hit.local}" and target not in hit.uses:
                        hit.uses.append(target)
            if prov.proofs == "verbatim":
                hit.proofs.append(
                    Proof(
                        optarg=rewrite(proof.optarg.strip()) if proof.optarg else "",
                        body=rewrite(_body_text(proof, files[rel].clean)),
                    )
                )
                report.proofs_kept += 1

    used_names: set[str] = set()
    body_lines: list[str] = []
    written_units: set[int] = set()
    statements = [st for st, _, _ in sorted(found, key=lambda x: x[0].order)]
    for st in statements:
        chain: list[SectionUnit] = []
        cur = units_of.get(st.local)
        while cur is not None:
            if unit_numbers.get(id(cur)) and cur.level <= 2:
                chain.append(cur)
            cur = cur.parent
        for su in reversed(chain):
            if id(su) in written_units:
                continue
            written_units.add(id(su))
            cmd = "section" if su.level == 1 else "subsection"
            title = rewrite(su.title.strip())
            body_lines.append(f"\\{cmd}{{{title}}}\\label{{{prov.prefix}-sec-{unit_numbers[id(su)]}}}")
            body_lines.append("")
        env = env_of[id(st)]
        locator = f"{st.taxon} {st.number}" if st.number else f"{st.taxon} (unnumbered)"
        if env.optarg:
            st.title = rewrite(env.optarg.strip())
            locator += f" ({st.title})"
        if st.page:
            locator += f", p.~{st.page}"
        st.statement = rewrite(_body_text(env, files[st.file].clean))
        used_names.update(_CMD.findall(st.statement) + _CMD.findall(locator) + _CMD.findall(st.proof_text))
        body_lines.append(
            f"\\begin{{{st.env}}}[{{\\cite[{locator}]{{{prov.digest}}}}}]\\label{{{prov.prefix}-{st.local}}}"
        )
        if st.uses:
            body_lines.append(f"\\uses{{{', '.join(st.uses)}}}")
            report.uses += len(st.uses)
        if st.statement:
            body_lines.append(st.statement)
        body_lines.append(f"\\end{{{st.env}}}")
        body_lines.append("")
        for p in st.proofs:
            body_lines.append("\\begin{proof}" + (f"[{p.optarg}]" if p.optarg else ""))
            if p.body:
                body_lines.append(p.body)
            body_lines.append("\\end{proof}")
            body_lines.append("")
        report.by_taxon[st.taxon] = report.by_taxon.get(st.taxon, 0) + 1
    report.sections = len(written_units)

    report.requires = sorted(loaded_packages(paper.closure.clean_text()) - ALWAYS_LOADED - PRESENTATION)
    defs = _definitions(paper.closure.raw_text())
    residue = sorted(n for n in used_names if n in defs and n not in report.expanded)
    block: list[str] = []
    for name in residue:
        block.append(f"\\let\\{name}\\undefined")
        block.append(defs[name])
    env_defs = _env_definitions(paper.closure.raw_text())
    used_envs = sorted({m for m in re.findall(r"\\begin\{([A-Za-z*]+)\}", "\n".join(body_lines)) if m in env_defs})
    for name in used_envs:
        block.append(env_defs[name])
        residue.append(f"env:{name}")
        if env_defs[name].startswith("\\newlist") and "enumitem" not in report.requires:
            report.requires.append("enumitem")
    report.block = residue

    out = header_lines(prov, report)
    if block:
        out.append("")
        out.append("% !LOOM begin macros")
        out.append("\\begingroup")
        out.extend(block)
        out.append("\\endgroup")
        out.append("% !LOOM end macros")
    out.append("")
    out.extend(body_lines)
    return Extraction("\n".join(out).rstrip("\n") + "\n", statements, report)


def header_lines(prov: Provenance, report: Report) -> list[str]:
    """The provenance header, one directive per line in the order of docs/specs/digest.md §2."""
    out = [
        f"% !LOOM digest: {prov.digest}",
        f"% !LOOM prefix: {prov.prefix}",
        f"% !LOOM extracted-from: {prov.extracted_from}",
    ]
    if prov.published_as and prov.published_as != prov.extracted_from:
        out.append(f"% !LOOM published-as: {prov.published_as}")
    out.append("% !LOOM method: extract")
    out.append(f"% !LOOM proofs: {prov.proofs}")
    if prov.created:
        out.append(f"% !LOOM created: {prov.created}")
    if report.requires:
        out.append(f"% !LOOM requires: {', '.join(report.requires)}")
    if report.numbering != "compiled":
        out.append("% !LOOM numbering: emulated")
    if prov.tool:
        out.append(f"% !LOOM tool: {prov.tool}")
    return out
