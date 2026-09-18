"""The edges the papers state, and the ambiguities they raise: plan 0.1 §7 and §8.3 of the digest contract."""

from __future__ import annotations

import json
from pathlib import Path

from weft.config import Settings, load
from weft.extract import extract_corpus
from weft.link import Ambiguity, link


def corpus_at(root: Path) -> Settings:
    """A corpus with nothing in it but its directories, for the parts of the linker that read records rather than results."""
    for d in ("works", "cache", "crawl"):
        (root / d).mkdir(parents=True, exist_ok=True)
    return Settings(root=root)


def _linked(corpus: Path, log: Path) -> tuple[object, dict[str, list[dict[str, str]]]]:
    extract_corpus(load(corpus))
    report = link(load(corpus), log=log)
    edges = {
        json.loads(p.read_text(encoding="utf-8"))["version"]: json.loads(p.read_text(encoding="utf-8"))["edges"]
        for p in corpus.rglob("results.json")
    }
    return report, edges


def test_the_two_stated_cases_and_the_papers_own_references(synthetic: Path, tmp_path: Path) -> None:
    report, edges = _linked(synthetic, tmp_path / "record.md")

    every = [e for version in edges.values() for e in version]
    origins = {e["origin"] for e in every}
    assert origins <= {"internal", "locator", "unspecified"}, "nothing is inferred beyond what a paper states"

    by_locator = [e for e in every if e["origin"] == "locator"]
    assert by_locator, "a \\cite[Theorem 2.1]{other} names a result of the cited work"
    for edge in by_locator:
        assert "#" in edge["to"], "a locator edge points at a result, not a work"
        assert edge["evidence"], "an edge carries the locator as the paper printed it"

    unspecified = [e for e in every if e["origin"] == "unspecified"]
    assert unspecified, "a \\cite{third} with no locator names a work and no result"
    for edge in unspecified:
        assert "#" not in edge["to"], "an unspecified edge points at a work"

    assert report.locator == len(by_locator) and report.unspecified == len(unspecified)
    assert report.versions == len(edges)


def test_linking_twice_leaves_the_same_edges(synthetic: Path, tmp_path: Path) -> None:
    first, edges = _linked(synthetic, tmp_path / "record.md")
    second = link(load(synthetic), log=tmp_path / "record.md")
    after = {
        json.loads(p.read_text(encoding="utf-8"))["version"]: json.loads(p.read_text(encoding="utf-8"))["edges"]
        for p in synthetic.rglob("results.json")
    }
    assert after == edges and second.payload() == first.payload()


def test_an_ambiguous_locator_records_no_edge_and_is_logged(tmp_path: Path) -> None:
    """Several different results answering one locator is the case we do not yet know how to decide (docs/multi-match-record.md)."""
    record = tmp_path / "record.md"
    record.write_text("# Ambiguous locator matches\n\n_None yet: the linker lands in M3._\n", encoding="utf-8")
    from weft import link as module

    module._log(
        load_settings := None, [Ambiguity("v#thm-1", "doi:10.1/x", "Theorem 1", ["a#thm-1", "b#lem-1"])], record
    )  # type: ignore[arg-type]
    assert load_settings is None
    text = record.read_text(encoding="utf-8")
    assert "| when |" in text and "`Theorem 1`" in text and "`a#thm-1`" in text and "several" in text
    assert "_None yet" not in text


def test_a_result_answering_in_two_versions_of_one_work_is_not_ambiguous() -> None:
    """One theorem under two numberings is one result; the latest version answers, and nothing is logged."""
    from weft.link import _resolve, _Version
    from weft.locators import forms_for

    def version(ident: str) -> _Version:
        v = _Version(ident=ident, work="arxiv:2401.00001", path=Path("."), data={})
        v.forms = [(f"{ident}#thm-1", forms_for("thm-1", "Theorem", "1", [], ""))]
        return v

    drawn, troubles, missed = _resolve(
        "x#lem-2", "arxiv:2401.00001", "Theorem 1", [version("arxiv:2401.00001v1"), version("arxiv:2401.00001v2")]
    )
    assert not troubles and not missed
    assert [e.to for e in drawn] == ["arxiv:2401.00001v2#thm-1"]


def test_a_postnote_naming_two_results_draws_two_edges() -> None:
    """`Theorems 1.1 and 2.3` names two results, which is not an ambiguity."""
    from weft.link import _resolve, _Version
    from weft.locators import forms_for

    v = _Version(ident="arxiv:x", work="arxiv:x", path=Path("."), data={})
    v.forms = [
        ("arxiv:x#thm-1.1", forms_for("thm-1.1", "Theorem", "1.1", [], "")),
        ("arxiv:x#thm-2.3", forms_for("thm-2.3", "Theorem", "2.3", [], "")),
    ]
    drawn, troubles, missed = _resolve("y#lem-1", "arxiv:x", "Theorems 1.1 and 2.3", [v])
    assert [e.to for e in drawn] == ["arxiv:x#thm-1.1", "arxiv:x#thm-2.3"]
    assert not troubles and not missed


def test_a_citation_naming_the_preprint_finds_the_work_filed_under_its_doi(tmp_path: Path) -> None:
    """A paper cites whichever artifact its author had in hand; a corpus files a work under whichever identifier ranked first. Measured on demos/acgs: 26 of 135 cited works were held under a second identifier, and every one of them drew no edge until this resolved."""
    from weft.crawl.work import Record, Reference, save
    from weft.link import _citekeys

    corpus = corpus_at(tmp_path)
    save(
        corpus.works_dir,
        Record(
            ids=["doi:10.2140/gt.2019.23.1621", "arxiv:0902.0087"],
            title="The cited work, published",
        ),
    )
    save(
        corpus.works_dir,
        Record(
            ids=["arxiv:2401.00009"],
            title="The citing paper",
            references=[Reference(work="arxiv:0902.0087v1", citekey="Cited", text="A. Author, The cited work")],
        ),
    )

    found = _citekeys(corpus)
    assert found["arxiv:2401.00009"]["Cited"] == "doi:10.2140/gt.2019.23.1621", (
        "the citekey resolves to the record that holds the work, not to the identifier the citation used"
    )
