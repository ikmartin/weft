"""Per-file environment trees, and the attachment of a proof to the statement it proves.

Every environment in a file is nested by the tokenizer; theorem-like ones and proofs are flagged by name. A proof attaches by the `\\ref` in its optional argument, by adjacency to the preceding sibling statement (or to a proof already attached by adjacency to it), or by enclosure when it sits directly inside a theorem-like node with no statement before it; anything else is unattached, and its text is not written under anybody's statement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from weft.tex.model import Env, SourceFile
from weft.tex.tokenize import EnvNode, env_tree

REF_IN_OPT = re.compile(r"\\(?:ref|cref|Cref|autoref|eqref)\s*\{([^}]*)\}")
_LABEL = re.compile(r"\\label\s*\{([^}]*)\}")


@dataclass
class Attachment:
    """One proof and the statement it was read as proving, with how that was decided."""

    proof: Env
    statement: Env | None
    via: str  # ref | adjacent | enclosure | none
    ref_labels: list[str] = field(default_factory=list)
    fallback: Attachment | None = None  # the positional attachment used when every ref label is unknown


@dataclass
class FileEnvs:
    """One file's environments: the tree, the theorem-like nodes and proofs found in it, and each proof's attachment."""

    file: str
    roots: list[Env] = field(default_factory=list)
    theorem_envs: list[Env] = field(default_factory=list)
    proofs: list[Env] = field(default_factory=list)
    attachments: dict[int, Attachment] = field(default_factory=dict)  # keyed by proof start offset
    problems: list[tuple[str, int, str]] = field(default_factory=list)

    def all_envs(self) -> list[Env]:
        out: list[Env] = []

        def walk(e: Env) -> None:
            out.append(e)
            for c in e.children:
                walk(c)

        for r in self.roots:
            walk(r)
        return out


def _convert(node: EnvNode, parent: Env | None, theorem_names: set[str]) -> Env:
    env = Env(
        name=node.name,
        start=node.start,
        end=node.end,
        body_start=node.body_start,
        body_end=node.body_end,
        optarg=node.optarg,
        optarg_span=node.optarg_span,
        parent=parent,
        theorem_like=node.name in theorem_names,
        is_proof=node.name == "proof",
    )
    env.children = [_convert(c, env, theorem_names) for c in node.children]
    return env


def scan_environments(src: SourceFile, theorem_names: set[str], body_start: int = 0) -> FileEnvs:
    """Build the environment tree of one file and attach every proof.

    Parameters
    ----------
    src : SourceFile
        The file to read.
    theorem_names : set of str
        Environment names the paper declared as theorem-like.
    body_start : int, default 0
        Where the document body begins, so a main file's preamble is not scanned for environments.

    Returns
    -------
    FileEnvs
        The tree, the theorem-like nodes, the proofs and their attachments.
    """
    text = src.clean
    roots_raw, problems = env_tree(text[body_start:] if body_start else text)
    fe = FileEnvs(file=src.path, problems=[(k, o + body_start, e) for k, o, e in problems])
    for r in roots_raw:
        _shift(r, body_start)
    fe.roots = [_convert(r, None, theorem_names) for r in roots_raw]
    for env in fe.all_envs():
        if env.theorem_like:
            fe.theorem_envs.append(env)
        elif env.is_proof:
            fe.proofs.append(env)
    for proof in fe.proofs:
        fe.attachments[proof.start] = _attach(proof, fe, text)
    return fe


def _shift(node: EnvNode, by: int) -> None:
    if not by:
        return
    node.start += by
    node.end += by
    node.body_start += by
    node.body_end += by
    if node.optarg_span:
        node.optarg_span = (node.optarg_span[0] + by, node.optarg_span[1] + by)
    for c in node.children:
        _shift(c, by)


def _siblings(env: Env, fe: FileEnvs) -> list[Env]:
    return env.parent.children if env.parent is not None else fe.roots


def _gap_is_blank(text: str, a: int, b: int) -> bool:
    return text[a:b].strip() == ""


def _attach(proof: Env, fe: FileEnvs, text: str) -> Attachment:
    positional = _attach_positional(proof, fe, text)
    if proof.optarg:
        labels = REF_IN_OPT.findall(proof.optarg)
        if labels:
            return Attachment(proof, None, "ref", [norm_label(x) for x in labels], fallback=positional)
    return positional


def _attach_positional(proof: Env, fe: FileEnvs, text: str) -> Attachment:
    sibs = _siblings(proof, fe)
    idx = sibs.index(proof)
    j = idx - 1
    while j >= 0:
        prev = sibs[j]
        if not _gap_is_blank(text, prev.end, sibs[j + 1].start):
            break
        if prev.theorem_like:
            return Attachment(proof, prev, "adjacent")
        if prev.is_proof:
            earlier = fe.attachments.get(prev.start)
            if earlier is not None and earlier.via == "adjacent" and earlier.statement is not None:
                return Attachment(proof, earlier.statement, "adjacent")
            break
        break
    if proof.parent is not None and proof.parent.theorem_like and not any(s.theorem_like for s in sibs[:idx]):
        return Attachment(proof, proof.parent, "enclosure")
    return Attachment(proof, None, "none")


def labels_in(text: str, ranges: list[tuple[int, int]]) -> list[tuple[str, int]]:
    """(label, offset) for every `\\label` inside the given own-text ranges, in document order."""
    out: list[tuple[str, int]] = []
    for a, b in ranges:
        for m in _LABEL.finditer(text, a, b):
            out.append((norm_label(m.group(1)), m.start()))
    return out


def norm_label(label: str) -> str:
    """Labels are read as TeX reads them: runs of whitespace, including line breaks, collapse to one space."""
    return re.sub(r"\s+", " ", label).strip()
