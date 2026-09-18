"""The digest contract, statement by numbered statement (docs/specs/digest.md).

A digest written by weft must be readable by loom and the other way round, so these tests name the statements they pin rather than the code they exercise: where weft and loom disagree, one of them has a bug, and the disagreement should be a failing test here rather than a discovery months later in somebody's bundle.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from support import PROV, extracted
from weft.config import load
from weft.crawl.work import Record, Version
from weft.extract import extract_corpus, provenance_for
from weft.extract.extract import extract, read_paper
from weft.extract.write import result_payload
from weft.tex.aux import AuxNumber
from weft.tex.digests import header, is_digest, macro_block

SIMPLE = r"""\documentclass{article}
\usepackage{amsmath}
\usepackage{tikz-cd}
\newtheorem{theorem}{Theorem}[section]
\newtheorem{lemma}[theorem]{Lemma}
\newcommand{\cX}{\mathcal{X}}
\newcommand{\hard}[1]{\operatorname{H}^{#1}(\cX)}
\newenvironment{myclaim}{\par\textbf{Claim.}}{\par}
\begin{document}
\section{One}
\label{sec:one}

\begin{theorem}[Main theorem]\label{thm:main}\label{thm:alias}
Every $\cX$ is $\hard{2}$-finite.
\end{theorem}

\begin{proof}
By \cite[Theorem 9.4]{other} and Lemma~\ref{lem:small}, using \begin{myclaim}nothing\end{myclaim}.
\end{proof}

\begin{lemma}\label{lem:small}
Small things are small.
\end{lemma}

\end{document}
"""


def digest_of(tmp_path: Path, text: str = SIMPLE, **kwargs: object) -> str:
    return extracted(tmp_path / "src", text, **kwargs).digest  # type: ignore[arg-type]


def test_1_2_a_file_is_a_digest_by_its_first_directive(tmp_path: Path) -> None:
    text = digest_of(tmp_path)
    assert is_digest(text)
    assert text.splitlines()[0] == "% !LOOM digest: arxiv:0000.00000"


def test_2_the_header_is_the_contracts_directives_in_the_contracts_order(tmp_path: Path) -> None:
    got = header(digest_of(tmp_path))
    # §2.1 digest, 2.2 prefix, 2.3 extracted-from, 2.5 method, 2.6 proofs, 2.7 created, 2.8 requires, 2.9 numbering; `tool` is weft's own and rides at the end, where 2.10 lets a reader ignore it
    assert list(got) == [
        "digest",
        "prefix",
        "extracted-from",
        "method",
        "proofs",
        "created",
        "requires",
        "numbering",
        "tool",
    ]
    assert got["digest"] == "arxiv:0000.00000"
    assert got["prefix"] == "arxiv-0000.00000v1"
    assert got["extracted-from"] == "arxiv:0000.00000v1"
    assert got["method"] == "extract"
    assert got["proofs"] == "verbatim"
    assert got["created"] == "2026-09-18"
    assert got["numbering"] == "emulated"
    # §2.8: packages a statement needs, beyond the three always loaded and the ones about the page
    assert got["requires"] == "tikz-cd"


def test_2_4_published_as_is_the_other_artifact_and_never_the_same_one(synthetic: Path) -> None:
    settings = load(synthetic)
    preprint = Record(ids=["doi:10.1112/S0010437X20007393", "arxiv:1709.09864"], home="doi/10.1112_x")
    version = Version(id="arxiv:1709.09864v2", work=preprint.key)
    assert (
        provenance_for(settings, preprint, version, proofs="verbatim").published_as == "doi:10.1112/S0010437X20007393"
    )

    # an arXiv DOI names the preprint itself, so it is the same artifact under another spelling and is not a second fact
    same = Record(ids=["arxiv:2401.00001", "doi:10.48550/arxiv.2401.00001"], home="arxiv/2401.00001")
    got = provenance_for(settings, same, Version(id="arxiv:2401.00001v1", work=same.key), proofs="verbatim")
    assert got.published_as == ""


def test_2_6_the_header_says_what_the_file_contains(tmp_path: Path) -> None:
    assert header(digest_of(tmp_path, proofs="verbatim"))["proofs"] == "verbatim"
    assert header(digest_of(tmp_path, proofs="none"))["proofs"] == "none"


def test_2_9_numbering_says_emulated_only_when_it_was_counted(tmp_path: Path) -> None:
    assert header(digest_of(tmp_path))["numbering"] == "emulated"
    extracted(tmp_path / "src", SIMPLE)
    compiled = extract(read_paper(tmp_path / "src"), PROV, aux={"thm:main": AuxNumber("4.1", 9)})
    assert "numbering" not in header(compiled.digest)


def test_3_1_and_3_2_ids_are_the_prefix_the_abbreviation_and_the_number(tmp_path: Path) -> None:
    made = extracted(tmp_path / "src", SIMPLE)
    assert [s.local for s in made.statements] == ["thm-1.1", "lem-1.2"]
    for s in made.statements:
        ident = f"{PROV.prefix}-{s.local}"
        assert re.fullmatch(r"[A-Za-z0-9.-]+", ident), ident  # §3.1: letters, digits, dots and hyphens; dots are legal
        assert f"\\label{{{ident}}}" in made.digest


def test_3_2_an_environment_outside_the_map_contributes_its_own_name(tmp_path: Path) -> None:
    made = extracted(
        tmp_path / "src",
        "\\documentclass{article}\n\\newtheorem{observation}{Observation}\n"
        "\\begin{document}\n\\begin{observation}\nSo it is.\n\\end{observation}\n\\end{document}\n",
    )
    assert [s.local for s in made.statements] == ["observation-1"]


def test_3_3_a_sectioning_unit_is_prefix_sec_number(tmp_path: Path) -> None:
    assert f"\\section{{One}}\\label{{{PROV.prefix}-sec-1}}" in digest_of(tmp_path)


def test_3_5_the_first_label_is_the_id_and_the_rest_are_aliases(tmp_path: Path) -> None:
    made = extracted(tmp_path / "src", SIMPLE)
    theorem = made.statements[0]
    assert theorem.aliases == ["thm:main", "thm:alias"]  # the paper's own labels, as the paper wrote them
    body = made.digest[made.digest.index("\\begin{theorem}") :]
    # in the file the id comes first and every label of the paper follows it, prefixed, so two papers' labels cannot collide
    assert body.index(f"\\label{{{PROV.prefix}-thm-1.1}}") < body.index(f"\\label{{{PROV.prefix}-thm:main}}")
    assert f"\\label{{{PROV.prefix}-thm:alias}}" in body


def test_4_1_a_result_is_an_environment_alone_on_its_lines(tmp_path: Path) -> None:
    for line in digest_of(tmp_path).splitlines():
        if line.startswith("\\begin{theorem}") or line.startswith("\\end{theorem}"):
            assert line.strip() == line
    assert "\\end{theorem}\n" in digest_of(tmp_path)


def test_4_2_the_title_carries_the_citation_with_a_locator(tmp_path: Path) -> None:
    text = digest_of(tmp_path)
    assert f"\\begin{{theorem}}[{{\\cite[Theorem 1.1 (Main theorem)]{{{PROV.digest}}}}}]" in text
    assert f"\\begin{{lemma}}[{{\\cite[Lemma 1.2]{{{PROV.digest}}}}}]" in text


def test_4_2_a_page_is_part_of_the_locator_when_a_compile_gave_one(tmp_path: Path) -> None:
    extracted(tmp_path / "src", SIMPLE)
    made = extract(read_paper(tmp_path / "src"), PROV, aux={"thm:main": AuxNumber("4.1", 9)})
    assert "\\cite[Theorem 4.1 (Main theorem), p.~9]" in made.digest


def test_4_3_statements_are_verbatim(tmp_path: Path) -> None:
    made = extracted(tmp_path / "src", SIMPLE)
    # the paper's own macros are expanded, and nothing else about the sentence changes; the labels come out of the indexed form, where they are the `aliases` field instead
    assert result_payload(made.statements[1])["statement"] == "Small things are small."
    assert "Every $\\mathcal{X}$ is $\\operatorname{H}^{2}(\\mathcal{X})$-finite." in made.statements[0].statement


def test_4_4_a_proof_follows_its_statement_under_verbatim_and_is_absent_under_none(tmp_path: Path) -> None:
    kept = digest_of(tmp_path, proofs="verbatim")
    assert kept.index("\\begin{proof}") > kept.index("\\end{theorem}")
    assert "\\begin{proof}" not in digest_of(tmp_path, proofs="none")


def test_4_5_uses_records_what_the_proof_referred_to(tmp_path: Path) -> None:
    made = extracted(tmp_path / "src", SIMPLE)
    assert made.statements[0].uses == [f"{PROV.prefix}-lem-1.2"]
    assert f"\\uses{{{PROV.prefix}-lem-1.2}}" in made.digest


def test_4_6_a_digest_node_carries_no_proof_obligation(tmp_path: Path) -> None:
    text = digest_of(tmp_path)
    assert "\\incomplete" not in text and "\\needs" not in text


def test_5_the_macro_block_is_wrapped_and_undefines_before_it_defines(tmp_path: Path) -> None:
    text = digest_of(tmp_path)
    block = macro_block(text)
    assert block.startswith("\\begingroup") and block.endswith("\\endgroup")
    # \cX and \hard were expanded into the statements, so nothing of them is left to define; \myclaim survives into a proof and cannot be expanded
    assert "\\let\\myclaim\\undefined" not in block
    assert "\\newenvironment{myclaim}" in block  # §5.3: an environment the statements use belongs in the block
    assert text.index("% !LOOM end macros") < text.index(
        "\\section{One}"
    )  # §5.2: the reader's view starts after the block


def test_5_1_a_macro_that_cannot_be_expanded_is_undefined_before_it_is_defined(tmp_path: Path) -> None:
    text = digest_of(
        tmp_path,
        text="\\documentclass{article}\n\\newtheorem{theorem}{Theorem}\n\\def\\weird#1{\\mathbb{#1}}\n"
        "\\begin{document}\n\\begin{theorem}\nBounded, in the sense of \\weird\n\\end{theorem}\n\\end{document}\n",
    )
    block = macro_block(text)
    assert "\\let\\weird\\undefined" in block
    assert block.index("\\let\\weird\\undefined") < block.index("\\def\\weird#1")


def test_7_1_no_proof_under_proofs_none_anywhere(synthetic: Path) -> None:
    extract_corpus(load(synthetic), proofs="none")
    for path in sorted((synthetic / "works").rglob("digest.tex")):
        text = path.read_text(encoding="utf-8")
        assert header(text)["proofs"] == "none"
        assert "\\begin{proof}" not in text


def test_8_2_the_json_carries_the_same_results_as_the_digest(tmp_path: Path) -> None:
    made = extracted(tmp_path / "src", SIMPLE)
    for s in made.statements:
        assert f"\\label{{{PROV.prefix}-{s.local}}}" in made.digest
        assert s.taxon and s.number
    assert len(made.statements) == made.digest.count("\\begin{theorem}[") + made.digest.count("\\begin{lemma}[")


def test_a_proofs_policy_outside_the_contract_is_refused(tmp_path: Path) -> None:
    from support import paper

    paper(tmp_path / "src", SIMPLE)
    with pytest.raises(ValueError, match="proofs must be one of"):
        extract(read_paper(tmp_path / "src"), replace(PROV, proofs="summary"))
