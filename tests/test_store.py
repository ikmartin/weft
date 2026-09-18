"""The index behind the `Store` protocol: upserts that a replay can repeat, every accessor, and search on both the FTS5 and the LIKE path."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from weft.config import Settings
from weft.model import Edge, Reference, Result, SameAs, Version, Work
from weft.store import Store, open_store
from weft.store.sqlite import SqliteStore

WORK_A = Work(
    key="arxiv:2401.00001",
    ids=["arxiv:2401.00001", "doi:10.48550/arxiv.2401.00001"],
    title="Tropical cycles on fans of valuated matroids",
    authors=["Aurelio, Bram", "Cerny, Dagna"],
    year="2024",
    msc=["14N35", "14T15"],
    arxiv_category="math.AG",
    depth=1,
    reached_by="declared",
    citekeys=["other"],
)
WORK_B = Work(
    key="doi:10.4171/synth.0003",
    ids=["doi:10.4171/synth.0003"],
    title="Foundations of the synthetic period map",
    authors=["Ibarra, Juno"],
    year="1998",
    depth=2,
    reached_from=["arxiv:2401.00001"],
    reached_by="lookup",
    provenance="resolved",
)
VERSIONS = [
    Version(id="arxiv:2401.00001v1", work=WORK_A.key, has_source=True),
    Version(id="arxiv:2401.00001v2", work=WORK_A.key, has_source=True, method="latex", numbering="compiled"),
    Version(id="doi:10.4171/synth.0003", work=WORK_B.key),
]
RESULTS = [
    Result(
        version="arxiv:2401.00001v2",
        local="thm-1.1",
        taxon="Theorem",
        number="1.1",
        statement="Balanced.",
        proof="A wall.",
        aliases=["thm:main"],
    ),
    Result(version="arxiv:2401.00001v2", local="prop-2.1", taxon="Proposition", number="2.1", statement="The degree."),
]
EDGES = [
    Edge(src="arxiv:2401.00001v2#thm-1.1", to="arxiv:2401.00002v1#thm-2.1", origin="locator", evidence="Theorem 2.1"),
    Edge(src="arxiv:2401.00001v2#thm-1.1", to="doi:10.4171/synth.0003", origin="unspecified", confidence=0.5),
]
REFERENCES = [
    Reference(
        version="arxiv:2401.00001v2",
        work="arxiv:2401.00002",
        citekey="other",
        text="F. Ekstrom, ...",
        identified_by="declared",
    ),
    Reference(
        version="arxiv:2401.00001v2",
        work="doi:10.4171/synth.0003",
        citekey="third",
        text="J. Ibarra, ...",
        identified_by="lookup",
    ),
]
SAME_AS = [
    SameAs(
        left="arxiv:2401.00001v1#thm-1.1",
        right="arxiv:2401.00001v2#thm-1.1",
        confidence=0.9,
        evidence="identical statement",
    )
]

FILLED = {"works": 2, "versions": 3, "results": 2, "edges": 2, "references": 2, "same_as": 1}


def fill(store: Store) -> None:
    store.upsert_works([WORK_A, WORK_B])
    store.upsert_versions(VERSIONS)
    store.upsert_results(RESULTS)
    store.upsert_edges(EDGES)
    store.upsert_references(REFERENCES)
    store.upsert_same_as(SAME_AS)


@pytest.fixture(params=[None, False], ids=["detected", "like"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[SqliteStore]:
    """The store twice: once with FTS5 if this sqlite has it, once forced onto the LIKE fallback, because which one is in force is a runtime fact."""
    made = SqliteStore(tmp_path / "nested" / "index.sqlite", fts=request.param)
    yield made
    made.close()


def test_creates_its_file_and_parents(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "a" / "b" / "index.sqlite")
    try:
        assert (tmp_path / "a" / "b" / "index.sqlite").is_file()
        assert store.counts() == dict.fromkeys(FILLED, 0)
    finally:
        store.close()


def test_upserts_are_idempotent(store: SqliteStore) -> None:
    fill(store)
    assert store.counts() == FILLED
    fill(store)
    assert store.counts() == FILLED


def test_an_upsert_updates_rather_than_duplicates(store: SqliteStore) -> None:
    fill(store)
    store.upsert_works([Work(key=WORK_A.key, ids=WORK_A.ids, title="A new title", depth=1)])
    again = store.work(WORK_A.key)
    assert again is not None and again.title == "A new title"
    assert store.counts()["works"] == 2


def test_upsert_of_nothing_writes_nothing(store: SqliteStore) -> None:
    assert store.upsert_works([]) == 0
    assert store.upsert_versions([]) == 0
    assert store.counts() == dict.fromkeys(FILLED, 0)


def test_work_by_key_and_by_any_other_identifier(store: SqliteStore) -> None:
    fill(store)
    found = store.work(WORK_A.key)
    assert found is not None
    assert (found.title, found.authors, found.msc, found.depth) == (WORK_A.title, WORK_A.authors, WORK_A.msc, 1)
    assert found.arxiv_category == "math.AG" and found.citekeys == ["other"]
    alias = store.work("doi:10.48550/arxiv.2401.00001")
    assert alias is not None and alias.key == WORK_A.key
    assert store.work("arxiv:9999.99999") is None


def test_works_all_and_by_depth(store: SqliteStore) -> None:
    fill(store)
    assert [w.key for w in store.works()] == sorted([WORK_A.key, WORK_B.key])
    assert [w.key for w in store.works(depth=1)] == [WORK_A.key]
    assert [w.key for w in store.works(depth=2)] == [WORK_B.key]
    assert list(store.works(depth=7)) == []


def test_versions_of_a_work_by_key_or_alias(store: SqliteStore) -> None:
    fill(store)
    assert [v.id for v in store.versions_of(WORK_A.key)] == ["arxiv:2401.00001v1", "arxiv:2401.00001v2"]
    assert [v.id for v in store.versions_of("doi:10.48550/arxiv.2401.00001")] == [
        "arxiv:2401.00001v1",
        "arxiv:2401.00001v2",
    ]
    latest = list(store.versions_of(WORK_A.key))[-1]
    assert (latest.has_source, latest.has_pdf, latest.method, latest.numbering) == (True, False, "latex", "compiled")
    assert list(store.versions_of("arxiv:9999.99999")) == []


def test_result_by_key_and_by_version(store: SqliteStore) -> None:
    fill(store)
    found = store.result("arxiv:2401.00001v2#thm-1.1")
    assert found is not None
    assert (found.taxon, found.number, found.statement, found.proof, found.aliases) == (
        "Theorem",
        "1.1",
        "Balanced.",
        "A wall.",
        ["thm:main"],
    )
    assert str(found.key) == "arxiv:2401.00001v2#thm-1.1"
    assert [r.local for r in store.results_of("arxiv:2401.00001v2")] == ["prop-2.1", "thm-1.1"]
    assert store.result("arxiv:2401.00001v2#nope") is None
    assert list(store.results_of("arxiv:2401.00001v1")) == []


def test_edges_in_both_directions_keep_origin_and_confidence(store: SqliteStore) -> None:
    fill(store)
    out = list(store.edges_from("arxiv:2401.00001v2#thm-1.1"))
    assert [(e.to, e.origin, e.confidence) for e in out] == [
        ("arxiv:2401.00002v1#thm-2.1", "locator", 1.0),
        ("doi:10.4171/synth.0003", "unspecified", 0.5),
    ]
    assert out[0].evidence == "Theorem 2.1"
    back = list(store.edges_to("doi:10.4171/synth.0003"))
    assert [e.src for e in back] == ["arxiv:2401.00001v2#thm-1.1"]
    assert list(store.edges_from("nothing")) == []


def test_references_of_a_version(store: SqliteStore) -> None:
    fill(store)
    refs = list(store.references_of("arxiv:2401.00001v2"))
    assert [(r.citekey, r.work, r.identified_by) for r in refs] == [
        ("other", "arxiv:2401.00002", "declared"),
        ("third", "doi:10.4171/synth.0003", "lookup"),
    ]
    assert list(store.references_of("arxiv:2401.00001v1")) == []


def test_same_as_is_stored_with_its_evidence(store: SqliteStore) -> None:
    fill(store)
    assert store.counts()["same_as"] == 1
    store.upsert_same_as([SameAs(left=SAME_AS[0].left, right=SAME_AS[0].right, confidence=0.4, evidence="renumbered")])
    assert store.counts()["same_as"] == 1


def test_search_by_title_and_by_author(store: SqliteStore) -> None:
    fill(store)
    assert [w.key for w in store.search_works("tropical")] == [WORK_A.key]
    assert [w.key for w in store.search_works("valuated matroids")] == [WORK_A.key]
    assert [w.key for w in store.search_works("Aurelio")] == [WORK_A.key]
    assert [w.key for w in store.search_works("ibarra")] == [WORK_B.key]
    assert [w.key for w in store.search_works("period map")] == [WORK_B.key]
    assert list(store.search_works("wildly unrelated")) == []


def test_search_reads_no_query_syntax_and_honours_limit(store: SqliteStore) -> None:
    fill(store)
    assert [w.key for w in store.search_works('"tropical"')] == [WORK_A.key]
    assert [w.key for w in store.search_works("tropical*")] == [WORK_A.key]
    assert [w.key for w in store.search_works("matroids -fans")] == [WORK_A.key]
    assert list(store.search_works("%")) == []
    assert list(store.search_works("")) == []
    assert list(store.search_works("tropical", limit=0)) == []
    assert len(list(store.search_works("of", limit=1))) <= 1


def test_search_finds_a_title_updated_in_place(store: SqliteStore) -> None:
    fill(store)
    store.upsert_works([Work(key=WORK_A.key, ids=WORK_A.ids, title="Quite another subject", depth=1)])
    assert list(store.search_works("tropical")) == []
    assert [w.key for w in store.search_works("another subject")] == [WORK_A.key]


def test_clear_empties_and_leaves_a_usable_store(store: SqliteStore) -> None:
    fill(store)
    store.clear()
    assert store.counts() == dict.fromkeys(FILLED, 0)
    assert store.work(WORK_A.key) is None
    assert list(store.search_works("tropical")) == []
    fill(store)
    assert store.counts() == FILLED


def test_reopening_the_file_sees_what_was_written(tmp_path: Path) -> None:
    path = tmp_path / "index.sqlite"
    first = SqliteStore(path)
    fill(first)
    first.close()
    second = SqliteStore(path)
    try:
        assert second.counts() == FILLED
        assert second.work(WORK_A.key) is not None
    finally:
        second.close()


def test_open_store_uses_the_dsn_and_the_corpus_root(tmp_path: Path) -> None:
    store = open_store(Settings(root=tmp_path, dsn="sqlite:var/index.sqlite"))
    try:
        assert (tmp_path / "var" / "index.sqlite").is_file()
    finally:
        store.close()


def test_open_store_refuses_a_postgres_dsn_with_a_reason(tmp_path: Path) -> None:
    settings = Settings(root=tmp_path, dsn="postgresql://weft@localhost/weft")
    with pytest.raises(NotImplementedError) as raised:
        open_store(settings)
    message = str(raised.value)
    assert "postgresql://weft@localhost/weft" in message
    assert "sqlite:" in message
