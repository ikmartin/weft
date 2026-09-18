"""`weft index rebuild`: the index is a replay of `works/`, twice over gives the same thing, and one bad file costs only that file."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from weft.config import load
from weft.store.rebuild import rebuild
from weft.store.sqlite import SqliteStore

# What the synthetic corpus holds: three works, four versions (two of them the same work's), the two seeds' bibliographies, and nothing extracted yet.
SYNTHETIC = {"works": 3, "versions": 4, "results": 0, "edges": 0, "references": 4, "same_as": 0}

RESULTS_JSON = {
    "version": "arxiv:2401.00001v2",
    "method": "latex",
    "numbering": "compiled",
    "results": [
        {
            "local": "thm-1.1",
            "taxon": "Theorem",
            "number": "1.1",
            "title": "",
            "statement": "Balanced.",
            "proof": "One wall.",
            "aliases": ["thm:main"],
            "page": "1",
        },
        {
            "local": "prop-2.1",
            "taxon": "Proposition",
            "number": "2.1",
            "title": "",
            "statement": "The degree.",
            "proof": "",
            "aliases": ["prop:degree"],
            "page": "3",
        },
    ],
    "edges": [
        {
            "src": "arxiv:2401.00001v2#thm-1.1",
            "to": "arxiv:2401.00002v1#thm-1.1",
            "origin": "locator",
            "confidence": 1.0,
            "evidence": "Theorem 2.1",
        },
        {
            "src": "arxiv:2401.00001v2#thm-1.1",
            "to": "doi:10.4171/synth.0003",
            "origin": "unspecified",
            "confidence": 1.0,
            "evidence": "\\cite{third}",
        },
    ],
}


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SqliteStore]:
    made = SqliteStore(tmp_path / "index.sqlite")
    yield made
    made.close()


def test_rebuild_replays_the_synthetic_corpus(synthetic: Path, store: SqliteStore) -> None:
    settings = load(synthetic)
    assert rebuild(settings, store) == SYNTHETIC
    assert store.counts() == SYNTHETIC

    work = store.work("arxiv:2401.00001")
    assert work is not None
    assert work.title == "Tropical cycles on fans of valuated matroids"
    assert work.authors == ["Aurelio, Bram", "Cerny, Dagna"]
    assert work.depth == 1 and work.provenance == "declared"
    # Every identifier is indexed, so the work is one record under the arXiv DOI too.
    alias = store.work("doi:10.48550/arxiv.2401.00001")
    assert alias is not None and alias.key == work.key

    # The two versions differing by a dropped result are two rows of one work.
    assert [v.id for v in store.versions_of("arxiv:2401.00001")] == ["arxiv:2401.00001v1", "arxiv:2401.00001v2"]

    # The metadata-only work is in the citation graph, at depth 2, with no source anywhere.
    metadata_only = store.work("doi:10.4171/synth.0003")
    assert metadata_only is not None and metadata_only.depth == 2
    assert metadata_only.reached_from == ["arxiv:2401.00001", "arxiv:2401.00002"]
    assert [v.has_source or v.has_pdf for v in store.versions_of(metadata_only.key)] == [False]

    # A work-level bibliography is attributed to the version whose source was read.
    refs = list(store.references_of("arxiv:2401.00001v2"))
    assert [(r.citekey, r.work, r.identified_by) for r in refs] == [
        ("other", "arxiv:2401.00002", "declared"),
        ("third", "doi:10.4171/synth.0003", "lookup"),
    ]
    assert list(store.references_of("arxiv:2401.00001v1")) == []


def test_rebuild_is_idempotent(synthetic: Path, store: SqliteStore) -> None:
    settings = load(synthetic)
    first = rebuild(settings, store)
    second = rebuild(settings, store)
    assert first == second == SYNTHETIC
    assert store.counts() == SYNTHETIC


def test_rebuild_drops_rows_no_file_accounts_for(synthetic: Path, store: SqliteStore) -> None:
    settings = load(synthetic)
    rebuild(settings, store)
    (synthetic / "works" / "arxiv" / "2401.00002" / "work.json").unlink()
    counts = rebuild(settings, store)
    assert counts["works"] == 2
    assert store.work("arxiv:2401.00002") is None


def test_a_malformed_record_is_reported_and_skipped(
    synthetic: Path, store: SqliteStore, caplog: pytest.LogCaptureFixture
) -> None:
    settings = load(synthetic)
    broken = synthetic / "works" / "arxiv" / "2401.00002" / "work.json"
    broken.write_text("{not json at all", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="weft.store.rebuild"):
        counts = rebuild(settings, store)
    assert counts["works"] == 2
    assert store.work("arxiv:2401.00001") is not None
    assert store.work("arxiv:2401.00002") is None
    assert any("2401.00002" in r.getMessage() and "not JSON" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("[]", "not a JSON object"),
        ('{"key": "arxiv:2401.00002"}', "record version"),
        ('{"record": 2, "key": "arxiv:2401.00002"}', "record version"),
        ('{"record": 1, "ids": []}', "no key"),
    ],
)
def test_every_kind_of_unusable_record_is_skipped_with_its_reason(
    synthetic: Path, store: SqliteStore, caplog: pytest.LogCaptureFixture, body: str, reason: str
) -> None:
    settings = load(synthetic)
    (synthetic / "works" / "arxiv" / "2401.00002" / "work.json").write_text(body, encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="weft.store.rebuild"):
        counts = rebuild(settings, store)
    assert counts["works"] == 2
    assert any(reason in r.getMessage() for r in caplog.records)


def test_results_json_is_counted_when_it_is_there(synthetic: Path, store: SqliteStore) -> None:
    settings = load(synthetic)
    path = synthetic / "works" / "arxiv" / "2401.00001" / "v2" / "results.json"
    path.write_text(json.dumps(RESULTS_JSON), encoding="utf-8")
    counts = rebuild(settings, store)
    assert counts == {**SYNTHETIC, "results": 2, "edges": 2}
    assert store.counts() == counts

    found = store.result("arxiv:2401.00001v2#thm-1.1")
    assert found is not None
    assert (found.taxon, found.number, found.page, found.aliases) == ("Theorem", "1.1", "1", ["thm:main"])
    assert found.proof == "One wall."
    assert [r.local for r in store.results_of("arxiv:2401.00001v2")] == ["prop-2.1", "thm-1.1"]
    assert [(e.to, e.origin) for e in store.edges_from("arxiv:2401.00001v2#thm-1.1")] == [
        ("arxiv:2401.00002v1#thm-1.1", "locator"),
        ("doi:10.4171/synth.0003", "unspecified"),
    ]
    assert rebuild(settings, store) == counts


def test_same_as_is_read_from_a_work_level_file(synthetic: Path, store: SqliteStore) -> None:
    settings = load(synthetic)
    home = synthetic / "works" / "arxiv" / "2401.00001"
    (home / "same_as.json").write_text(
        json.dumps(
            {
                "same_as": [
                    {
                        "left": "arxiv:2401.00001v1#thm-1.1",
                        "right": "arxiv:2401.00001v2#thm-1.1",
                        "confidence": 0.9,
                        "evidence": "identical statement",
                    },
                    {
                        "left": "arxiv:2401.00001v1#prop-2.2",
                        "right": "arxiv:2401.00001v2#prop-2.1",
                        "confidence": 0.6,
                        "evidence": "renumbered",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    assert rebuild(settings, store) == {**SYNTHETIC, "same_as": 2}


def test_a_malformed_results_file_costs_only_itself(
    synthetic: Path, store: SqliteStore, caplog: pytest.LogCaptureFixture
) -> None:
    settings = load(synthetic)
    (synthetic / "works" / "arxiv" / "2401.00001" / "v1" / "results.json").write_text(
        '{"method": "latex"}', encoding="utf-8"
    )
    (synthetic / "works" / "arxiv" / "2401.00001" / "v2" / "results.json").write_text(
        json.dumps(RESULTS_JSON), encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING, logger="weft.store.rebuild"):
        counts = rebuild(settings, store)
    assert counts == {**SYNTHETIC, "results": 2, "edges": 2}
    assert any("no version" in r.getMessage() for r in caplog.records)


def test_an_entry_that_cannot_be_used_is_dropped_without_the_record(
    synthetic: Path, store: SqliteStore, caplog: pytest.LogCaptureFixture
) -> None:
    settings = load(synthetic)
    path = synthetic / "works" / "arxiv" / "2401.00002" / "work.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["versions"].append({"has_source": True})
    record["references"].append({"work": "arxiv:2401.00001"})
    path.write_text(json.dumps(record), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="weft.store.rebuild"):
        counts = rebuild(settings, store)
    assert counts == SYNTHETIC
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "a version with no id" in messages and "neither citekey nor text" in messages


def test_rebuild_over_a_corpus_with_no_works_directory(
    tmp_path: Path, store: SqliteStore, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "weft.toml").write_text('[seeds]\nworks = ["arxiv:2401.00001"]\n', encoding="utf-8")
    settings = load(tmp_path)
    with caplog.at_level(logging.WARNING, logger="weft.store.rebuild"):
        counts = rebuild(settings, store)
    assert counts == dict.fromkeys(SYNTHETIC, 0)
    assert any("no works/" in r.getMessage() for r in caplog.records)
