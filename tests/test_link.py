"""The edges the papers state, and the ambiguities they raise: plan 0.1 §7 and §8.3 of the digest contract."""

from __future__ import annotations

import json
from pathlib import Path

from weft.config import load
from weft.extract import extract_corpus
from weft.link import Ambiguity, link


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
