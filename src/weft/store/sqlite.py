"""SQLite behind the `Store` protocol: one file, no SQL visible to anything that imports it.

The index is derived and disposable — every row here can be replayed from `works/` by `weft.store.rebuild`, so nothing is written with care for durability and `clear()` simply drops the schema. Writes are upserts keyed on the domain's own identifiers, which is what makes a replay idempotent.

Full-text search is used when the interpreter's sqlite was built with FTS5 and a LIKE scan stands in when it was not; which one is in force is decided by trying to create the table, never assumed from a version number.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from weft.model import Edge, Reference, Result, SameAs, Version, Work

# `references` is reserved in SQL and `left`/`right` read badly in a join, so the storage names differ from the domain's.
_TABLE_SQL: dict[str, str] = {
    "works": """
        CREATE TABLE IF NOT EXISTS works (
            key TEXT PRIMARY KEY,
            ids TEXT NOT NULL DEFAULT '[]',
            title TEXT NOT NULL DEFAULT '',
            authors TEXT NOT NULL DEFAULT '[]',
            year TEXT NOT NULL DEFAULT '',
            msc TEXT NOT NULL DEFAULT '[]',
            arxiv_category TEXT NOT NULL DEFAULT '',
            licence TEXT NOT NULL DEFAULT '',
            depth INTEGER NOT NULL DEFAULT 0,
            reached_from TEXT NOT NULL DEFAULT '[]',
            reached_by TEXT NOT NULL DEFAULT '',
            provenance TEXT NOT NULL DEFAULT 'declared',
            citekeys TEXT NOT NULL DEFAULT '[]'
        )""",
    "work_ids": """
        CREATE TABLE IF NOT EXISTS work_ids (
            id TEXT PRIMARY KEY,
            work TEXT NOT NULL
        )""",
    "versions": """
        CREATE TABLE IF NOT EXISTS versions (
            id TEXT PRIMARY KEY,
            work TEXT NOT NULL,
            has_source INTEGER NOT NULL DEFAULT 0,
            has_pdf INTEGER NOT NULL DEFAULT 0,
            method TEXT NOT NULL DEFAULT '',
            numbering TEXT NOT NULL DEFAULT '',
            extracted_at TEXT NOT NULL DEFAULT ''
        )""",
    "results": """
        CREATE TABLE IF NOT EXISTS results (
            key TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            local TEXT NOT NULL,
            taxon TEXT NOT NULL DEFAULT '',
            number TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            statement TEXT NOT NULL DEFAULT '',
            proof TEXT NOT NULL DEFAULT '',
            aliases TEXT NOT NULL DEFAULT '[]',
            page TEXT NOT NULL DEFAULT ''
        )""",
    "edges": """
        CREATE TABLE IF NOT EXISTS edges (
            src TEXT NOT NULL,
            dst TEXT NOT NULL,
            origin TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            evidence TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (src, dst, origin)
        )""",
    "refs": """
        CREATE TABLE IF NOT EXISTS refs (
            version TEXT NOT NULL,
            work TEXT NOT NULL DEFAULT '',
            citekey TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL DEFAULT '',
            identified_by TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (version, citekey, text)
        )""",
    "same_as": """
        CREATE TABLE IF NOT EXISTS same_as (
            lhs TEXT NOT NULL,
            rhs TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            evidence TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (lhs, rhs)
        )""",
}

_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS work_ids_work ON work_ids(work)",
    "CREATE INDEX IF NOT EXISTS versions_work ON versions(work)",
    "CREATE INDEX IF NOT EXISTS results_version ON results(version)",
    "CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst)",
    "CREATE INDEX IF NOT EXISTS refs_work ON refs(work)",
    "CREATE INDEX IF NOT EXISTS same_as_rhs ON same_as(rhs)",
)

_FTS_SQL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS works_fts USING fts5(work UNINDEXED, title, authors, tokenize='unicode61')"
)

# The storage table behind each name `counts()` reports.
_COUNT_OF = {
    "works": "works",
    "versions": "versions",
    "results": "results",
    "edges": "edges",
    "references": "refs",
    "same_as": "same_as",
}


def _dump(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _load(text: str) -> list[str]:
    """A JSON list column, tolerant of a row written by hand or by an older schema."""
    try:
        parsed = json.loads(text or "[]")
    except json.JSONDecodeError:
        return []
    return [str(v) for v in parsed] if isinstance(parsed, list) else []


def _terms(text: str) -> list[str]:
    """The searchable words of a query: everything that is not a letter or a digit separates, so no FTS or LIKE syntax survives."""
    out: list[str] = []
    current: list[str] = []
    for ch in text.casefold():
        if ch.isalnum():
            current.append(ch)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


class SqliteStore:
    """The `Store` protocol over one sqlite file, creating it and its schema on first use.

    Parameters
    ----------
    path : Path
        The index file; parent directories are created, and `:memory:` is honoured as sqlite understands it.
    fts : bool, optional
        Force full-text search on or off; default is to detect FTS5 by trying to create the table. Passing False exercises the LIKE fallback.
    """

    def __init__(self, path: Path, *, fts: bool | None = None) -> None:
        self.path = path
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._fts_wanted = fts
        self._fts = False
        self._create()

    # -- schema -------------------------------------------------------------

    def _create(self) -> None:
        with self._conn:
            for sql in _TABLE_SQL.values():
                self._conn.execute(sql)
            for sql in _INDEX_SQL:
                self._conn.execute(sql)
        self._fts = self._make_fts()

    def _make_fts(self) -> bool:
        """True when a `works_fts` table exists to search; False when this sqlite has no FTS5 or the caller asked for the LIKE path."""
        if self._fts_wanted is False:
            return False
        try:
            with self._conn:
                self._conn.execute(_FTS_SQL)
        except sqlite3.Error:
            if self._fts_wanted is True:
                raise
            return False
        return True

    def clear(self) -> None:
        """Drop every table and recreate the schema: the index holds nothing the files cannot say again."""
        with self._conn:
            for name in (*_TABLE_SQL, "works_fts"):
                self._conn.execute(f"DROP TABLE IF EXISTS {name}")
        self._create()

    def close(self) -> None:
        self._conn.close()

    # -- writes -------------------------------------------------------------

    def upsert_works(self, works: Iterable[Work]) -> int:
        rows = list(works)
        if not rows:
            return 0
        with self._conn:
            for w in rows:
                ids = _unique([w.key, *w.ids])
                self._conn.execute(
                    """INSERT INTO works (key, ids, title, authors, year, msc, arxiv_category, licence, depth, reached_from, reached_by, provenance, citekeys)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(key) DO UPDATE SET ids=excluded.ids, title=excluded.title, authors=excluded.authors, year=excluded.year,
                           msc=excluded.msc, arxiv_category=excluded.arxiv_category, licence=excluded.licence, depth=excluded.depth,
                           reached_from=excluded.reached_from, reached_by=excluded.reached_by, provenance=excluded.provenance, citekeys=excluded.citekeys""",
                    (
                        w.key,
                        _dump(ids),
                        w.title,
                        _dump(w.authors),
                        w.year,
                        _dump(w.msc),
                        w.arxiv_category,
                        w.licence,
                        w.depth,
                        _dump(w.reached_from),
                        w.reached_by,
                        w.provenance,
                        _dump(w.citekeys),
                    ),
                )
                self._conn.execute("DELETE FROM work_ids WHERE work = ?", (w.key,))
                self._conn.executemany(
                    "INSERT OR REPLACE INTO work_ids (id, work) VALUES (?,?)", [(i, w.key) for i in ids]
                )
                if self._fts:
                    self._conn.execute("DELETE FROM works_fts WHERE work = ?", (w.key,))
                    self._conn.execute(
                        "INSERT INTO works_fts (work, title, authors) VALUES (?,?,?)",
                        (w.key, w.title, " ; ".join(w.authors)),
                    )
        return len(rows)

    def upsert_versions(self, versions: Iterable[Version]) -> int:
        rows = list(versions)
        with self._conn:
            self._conn.executemany(
                """INSERT INTO versions (id, work, has_source, has_pdf, method, numbering, extracted_at) VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET work=excluded.work, has_source=excluded.has_source, has_pdf=excluded.has_pdf,
                       method=excluded.method, numbering=excluded.numbering, extracted_at=excluded.extracted_at""",
                [
                    (v.id, v.work, int(v.has_source), int(v.has_pdf), v.method, v.numbering, v.extracted_at)
                    for v in rows
                ],
            )
        return len(rows)

    def upsert_results(self, results: Iterable[Result]) -> int:
        rows = list(results)
        with self._conn:
            self._conn.executemany(
                """INSERT INTO results (key, version, local, taxon, number, title, statement, proof, aliases, page) VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET version=excluded.version, local=excluded.local, taxon=excluded.taxon, number=excluded.number,
                       title=excluded.title, statement=excluded.statement, proof=excluded.proof, aliases=excluded.aliases, page=excluded.page""",
                [
                    (
                        str(r.key),
                        r.version,
                        r.local,
                        r.taxon,
                        r.number,
                        r.title,
                        r.statement,
                        r.proof,
                        _dump(r.aliases),
                        r.page,
                    )
                    for r in rows
                ],
            )
        return len(rows)

    def upsert_edges(self, edges: Iterable[Edge]) -> int:
        rows = list(edges)
        with self._conn:
            self._conn.executemany(
                """INSERT INTO edges (src, dst, origin, confidence, evidence) VALUES (?,?,?,?,?)
                   ON CONFLICT(src, dst, origin) DO UPDATE SET confidence=excluded.confidence, evidence=excluded.evidence""",
                [(e.src, e.to, e.origin, e.confidence, e.evidence) for e in rows],
            )
        return len(rows)

    def upsert_references(self, references: Iterable[Reference]) -> int:
        rows = list(references)
        with self._conn:
            self._conn.executemany(
                """INSERT INTO refs (version, work, citekey, text, identified_by) VALUES (?,?,?,?,?)
                   ON CONFLICT(version, citekey, text) DO UPDATE SET work=excluded.work, identified_by=excluded.identified_by""",
                [(r.version, r.work, r.citekey, r.text, r.identified_by) for r in rows],
            )
        return len(rows)

    def upsert_same_as(self, pairs: Iterable[SameAs]) -> int:
        rows = list(pairs)
        with self._conn:
            self._conn.executemany(
                """INSERT INTO same_as (lhs, rhs, confidence, evidence) VALUES (?,?,?,?)
                   ON CONFLICT(lhs, rhs) DO UPDATE SET confidence=excluded.confidence, evidence=excluded.evidence""",
                [(p.left, p.right, p.confidence, p.evidence) for p in rows],
            )
        return len(rows)

    # -- reads --------------------------------------------------------------

    def work(self, key: str) -> Work | None:
        """The work under any identifier it has, because sources add identifiers as a walk proceeds and a caller may hold an older one."""
        row = self._conn.execute("SELECT * FROM works WHERE key = ?", (key,)).fetchone()
        if row is None:
            alias = self._conn.execute("SELECT work FROM work_ids WHERE id = ?", (key,)).fetchone()
            if alias is None:
                return None
            row = self._conn.execute("SELECT * FROM works WHERE key = ?", (alias["work"],)).fetchone()
        return _work(row) if row is not None else None

    def works(self, *, depth: int | None = None) -> Iterator[Work]:
        if depth is None:
            rows = self._conn.execute("SELECT * FROM works ORDER BY key").fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM works WHERE depth = ? ORDER BY key", (depth,)).fetchall()
        return iter([_work(r) for r in rows])

    def versions_of(self, work: str) -> Iterator[Version]:
        found = self.work(work)
        key = found.key if found is not None else work
        rows = self._conn.execute("SELECT * FROM versions WHERE work = ? ORDER BY id", (key,)).fetchall()
        return iter([_version(r) for r in rows])

    def result(self, key: str) -> Result | None:
        row = self._conn.execute("SELECT * FROM results WHERE key = ?", (key,)).fetchone()
        return _result(row) if row is not None else None

    def results_of(self, version: str) -> Iterator[Result]:
        rows = self._conn.execute("SELECT * FROM results WHERE version = ? ORDER BY key", (version,)).fetchall()
        return iter([_result(r) for r in rows])

    def edges_from(self, key: str) -> Iterator[Edge]:
        rows = self._conn.execute("SELECT * FROM edges WHERE src = ? ORDER BY dst, origin", (key,)).fetchall()
        return iter([_edge(r) for r in rows])

    def edges_to(self, key: str) -> Iterator[Edge]:
        rows = self._conn.execute("SELECT * FROM edges WHERE dst = ? ORDER BY src, origin", (key,)).fetchall()
        return iter([_edge(r) for r in rows])

    def references_of(self, version: str) -> Iterator[Reference]:
        rows = self._conn.execute("SELECT * FROM refs WHERE version = ? ORDER BY citekey, text", (version,)).fetchall()
        return iter([_reference(r) for r in rows])

    def search_works(self, text: str, *, limit: int = 50) -> Iterator[Work]:
        """Works whose title or authors hold every word of `text`.

        Parameters
        ----------
        text : str
            Free words; punctuation separates and nothing in it is read as query syntax.
        limit : int, default 50
            The most rows to return.

        Returns
        -------
        Iterator[Work]
        """
        terms = _terms(text)
        if not terms or limit <= 0:
            return iter([])
        if self._fts:
            match = " AND ".join(f'"{t}"' for t in terms)
            rows = self._conn.execute(
                "SELECT w.* FROM works_fts f JOIN works w ON w.key = f.work WHERE works_fts MATCH ? ORDER BY bm25(works_fts), w.key LIMIT ?",
                (match, limit),
            ).fetchall()
        else:
            where = " AND ".join("(lower(title) LIKE ? OR lower(authors) LIKE ?)" for _ in terms)
            params: list[Any] = []
            for t in terms:
                params += [f"%{t}%", f"%{t}%"]
            params.append(limit)
            rows = self._conn.execute(f"SELECT * FROM works WHERE {where} ORDER BY key LIMIT ?", params).fetchall()
        return iter([_work(r) for r in rows])

    def counts(self) -> dict[str, int]:
        """Row counts under the domain's names for the tables, so a rebuild can be checked against what it says it wrote."""
        out: dict[str, int] = {}
        for name, table in _COUNT_OF.items():
            row = self._conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()
            out[name] = int(row["n"])
        return out


def _unique(values: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for v in values:
        if v:
            seen.setdefault(v, None)
    return list(seen)


def _work(row: sqlite3.Row) -> Work:
    return Work(
        key=row["key"],
        ids=_load(row["ids"]),
        title=row["title"],
        authors=_load(row["authors"]),
        year=row["year"],
        msc=_load(row["msc"]),
        arxiv_category=row["arxiv_category"],
        licence=row["licence"],
        depth=int(row["depth"]),
        reached_from=_load(row["reached_from"]),
        reached_by=row["reached_by"],
        provenance=row["provenance"],
        citekeys=_load(row["citekeys"]),
    )


def _version(row: sqlite3.Row) -> Version:
    return Version(
        id=row["id"],
        work=row["work"],
        has_source=bool(row["has_source"]),
        has_pdf=bool(row["has_pdf"]),
        method=row["method"],
        numbering=row["numbering"],
        extracted_at=row["extracted_at"],
    )


def _result(row: sqlite3.Row) -> Result:
    return Result(
        version=row["version"],
        local=row["local"],
        taxon=row["taxon"],
        number=row["number"],
        title=row["title"],
        statement=row["statement"],
        proof=row["proof"],
        aliases=_load(row["aliases"]),
        page=row["page"],
    )


def _edge(row: sqlite3.Row) -> Edge:
    return Edge(
        src=row["src"],
        to=row["dst"],
        origin=row["origin"],
        confidence=float(row["confidence"]),
        evidence=row["evidence"],
    )


def _reference(row: sqlite3.Row) -> Reference:
    return Reference(
        version=row["version"],
        work=row["work"],
        citekey=row["citekey"],
        text=row["text"],
        identified_by=row["identified_by"],
    )
