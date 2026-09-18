"""The commands of M1's store half, through click's runner. Nothing here touches the network: `init` writes files and the index commands read the corpus."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from weft.cli import main

# `weft bib` needs the BibTeX writer, which is another part of M1; the assertion over it is skipped rather than guessed at when it is not there yet.
HAS_BIBTEX = importlib.util.find_spec("weft.bibtex") is not None

SYNTHETIC = {"works": 3, "versions": 4, "results": 0, "edges": 0, "references": 4, "same_as": 0}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_init_writes_a_corpus_skeleton(runner: CliRunner, tmp_path: Path) -> None:
    fresh = tmp_path / "fresh"
    result = runner.invoke(main, ["init", str(fresh)])
    assert result.exit_code == 0, result.output
    assert (fresh / "weft.toml").is_file()
    for d in ("works", "cache", "crawl"):
        assert (fresh / d).is_dir()
    assert "weft.toml" in result.output

    again = runner.invoke(main, ["init", str(fresh)])
    assert again.exit_code == 2
    assert "exists" in again.output


def test_a_command_outside_a_corpus_says_so(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(main, ["index", "counts", "--corpus", str(tmp_path)])
    assert result.exit_code == 2
    assert "weft init" in result.output


def test_index_rebuild_then_counts(runner: CliRunner, synthetic: Path) -> None:
    rebuilt = runner.invoke(main, ["index", "rebuild", "--json", "--corpus", str(synthetic)])
    assert rebuilt.exit_code == 0, rebuilt.output
    assert json.loads(rebuilt.stdout) == SYNTHETIC
    assert (synthetic / "index.sqlite").is_file()

    counted = runner.invoke(main, ["index", "counts", "--json", "--corpus", str(synthetic)])
    assert counted.exit_code == 0, counted.output
    assert json.loads(counted.stdout) == SYNTHETIC

    plain = runner.invoke(main, ["index", "counts", "--corpus", str(synthetic)])
    assert plain.exit_code == 0
    assert "3 works" in plain.stdout and "4 references" in plain.stdout


def test_index_rebuild_found_by_walking_up(runner: CliRunner, synthetic: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(synthetic / "works" / "arxiv" / "2401.00001" / "v1" / "src")
    result = runner.invoke(main, ["index", "rebuild", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == SYNTHETIC


def test_bib_over_the_synthetic_corpus(runner: CliRunner, synthetic: Path) -> None:
    assert runner.invoke(main, ["index", "rebuild", "--corpus", str(synthetic)]).exit_code == 0
    if not HAS_BIBTEX:
        pytest.skip("weft.bibtex is not written yet; `weft bib` cannot be exercised")
    result = runner.invoke(main, ["bib", "arxiv:2401.00001", "--corpus", str(synthetic)])
    assert result.exit_code == 0, result.output
    assert "Tropical cycles" in result.output
    assert "2401.00001" in result.output


def test_bib_refuses_an_identifier_the_corpus_does_not_hold(runner: CliRunner, synthetic: Path) -> None:
    assert runner.invoke(main, ["index", "rebuild", "--corpus", str(synthetic)]).exit_code == 0
    if not HAS_BIBTEX:
        pytest.skip("weft.bibtex is not written yet; `weft bib` cannot be exercised")
    result = runner.invoke(main, ["bib", "arxiv:9999.99999", "--corpus", str(synthetic)])
    assert result.exit_code == 1
    assert "not a work of this corpus" in result.output


def test_extract_reports_what_it_found(runner: CliRunner, synthetic: Path) -> None:
    made = runner.invoke(main, ["extract", "--json", "--corpus", str(synthetic)])
    assert made.exit_code == 0, made.output
    report = json.loads(made.stdout)
    assert (report["extracted"], report["results"], report["proofs"]) == (3, 7, "verbatim")
    assert report["proofs_kept"] == 7
    assert {o["numbering"] for o in report["outcomes"]} == {"emulated"}

    again = runner.invoke(main, ["extract", "--corpus", str(synthetic)])
    assert again.exit_code == 0
    assert "already extracted" in again.stdout

    redone = runner.invoke(main, ["extract", "--all", "--json", "--corpus", str(synthetic)])
    assert json.loads(redone.stdout)["extracted"] == 3


def test_extract_one_work_without_its_proofs(runner: CliRunner, synthetic: Path) -> None:
    made = runner.invoke(
        main, ["extract", "arxiv:2401.00002", "--proofs", "none", "--json", "--corpus", str(synthetic)]
    )
    assert made.exit_code == 0, made.output
    report = json.loads(made.stdout)
    assert [o["version"] for o in report["outcomes"]] == ["arxiv:2401.00002v1"]
    assert report["proofs_kept"] == 0
    assert "\\begin{proof}" not in (synthetic / "works/arxiv/2401.00002/v1/digest.tex").read_text(encoding="utf-8")


def test_extract_then_rebuild_indexes_the_results(runner: CliRunner, synthetic: Path) -> None:
    runner.invoke(main, ["extract", "--corpus", str(synthetic)])
    counted = runner.invoke(main, ["index", "rebuild", "--json", "--corpus", str(synthetic)])
    assert json.loads(counted.stdout) == {**SYNTHETIC, "results": 7}


def test_extract_says_so_when_a_corpus_has_nothing_to_read(runner: CliRunner, tmp_path: Path) -> None:
    fresh = tmp_path / "empty"
    runner.invoke(main, ["init", str(fresh)])
    (fresh / "weft.toml").write_text(
        (fresh / "weft.toml").read_text(encoding="utf-8").replace("works = []", 'works = ["arxiv:1"]'), encoding="utf-8"
    )
    made = runner.invoke(main, ["extract", "--corpus", str(fresh)])
    assert made.exit_code == 0
    assert "Nothing to extract" in made.stdout
