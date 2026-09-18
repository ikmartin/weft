"""The crawl: formatted bibliographies, subjects, the record, the three services as recorded, the plan on a synthetic citation graph, binding, the capped fetch, and the fingerprint."""

from __future__ import annotations

import gzip
import json
from dataclasses import replace
from pathlib import Path

import pytest

from support import CRAWL, budget, corpus, seed_file
from weft.config import Settings
from weft.crawl import msc as M
from weft.crawl import net
from weft.crawl.arxiv import Arxiv
from weft.crawl.fetch import Downloaders, fetch, status
from weft.crawl.openalex import OaRecord, OpenAlex
from weft.crawl.plan import Clients, PlanRefused, fingerprint, load_plan, plan, seed_texts, seeds, survey
from weft.crawl.work import Record, Reference, Version, load, load_all, norm, ranked, save
from weft.crawl.zbmath import Zbmath, ZbRecord
from weft.lookup import Candidate, Query

# --- formatted bibliographies -------------------------------------------------------------------------

SOURCE = r"""
\begin{thebibliography}{99}
\bibitem[GP]{GraberPandharipande} T.~Graber, R.~Pandharipande, \textit{Localization of virtual classes}. Invent.~Math.~{\bf{135}} (1999), no.~2, 487--518.
\bibitem{AHR21} {\sc Jarod Alper, Jack Hall, David Rydh}, {\it The \'etale local structure of algebraic stacks}, \url{https://arxiv.org/abs/1912.06162}, 2021.
%\bibitem{Gone} {\sc Nobody}, {\it Commented out}, 2020.
\bibitem{Joyce} D.~Joyce, \textit{Enumerative invariants}. \arXiv{2111.04694} (2021).
\bibitem{Doi} A.~Author, \textit{A title}, J. Something 1 (2000), doi:10.1000/xyz.1.
\end{thebibliography}
Text after the bibliography.
"""


def test_bibitems_are_read_wherever_they_are_and_commented_ones_are_not() -> None:
    from weft.crawl import bibitem as B

    items = B.entries(SOURCE)
    assert [i.key for i in items] == ["GraberPandharipande", "AHR21", "Joyce", "Doi"]
    assert items[1].arxiv == "1912.06162" and items[2].arxiv == "2111.04694" and items[3].doi == "10.1000/xyz.1"
    assert items[0].arxiv is None and items[0].doi is None
    assert "Text after" not in items[-1].text


def test_a_formatted_entry_becomes_a_lookup_with_title_surnames_and_the_right_year() -> None:
    from weft.crawl import bibitem as B

    gp, ahr = B.entries(SOURCE)[:2]
    q = B.query(gp)
    assert (q.title, q.surnames, q.year) == ("Localization of virtual classes", ("Graber", "Pandharipande"), "1999")
    q = B.query(ahr)
    assert q.surnames == ("Alper", "Hall", "Rydh")  # first names first, surnames still found
    assert q.year == "2021"  # not 1912, which is the arXiv number


def test_bibitems_come_from_every_file_of_a_source_once(tmp_path: Path) -> None:
    from weft.crawl import bibitem as B

    (tmp_path / "a.tex").write_text(SOURCE)
    (tmp_path / "b.bbl").write_text(SOURCE)
    assert len(B.from_source(tmp_path)) == 4


# --- subjects --------------------------------------------------------------------------------------------


def test_subjects_judge_works_with_codes_and_categories_works_without() -> None:
    assert M.family("14N35") == "14N" and M.family("14-02") == "14-" and M.family("55") == "55-"
    assert M.families(["14N35", "14N10", "14D23"]) == ["14D", "14N"]
    assert M.passes(["55N91", "14C17"], "", ["14C"], []) is True  # any code of the work
    assert M.passes(["55N91"], "math.AG", ["14C"], ["math.AG"]) is False  # codes decide when there are any
    assert M.passes([], "math.AG", ["14C"], ["math.AG"]) is True
    assert M.passes([], "math.AG", ["14C"], []) is False  # weft supplies no categories of its own
    assert M.passes([], "", ["14C"], ["math.AG"]) is None


def test_a_tally_counts_primary_families_any_family_categories_and_neither() -> None:
    t = M.tally([(["14N35", "14L30"], "math.AG"), (["14L24"], ""), ([], "math.AT"), ([], "")])
    assert t["primary"] == {"14N": 1, "14L": 1} and t["any"] == {"14N": 1, "14L": 2}
    assert t["categories"] == {"math.AT": 1} and t["neither"] == {"works": 1}


# --- the record ------------------------------------------------------------------------------------------

CONTRACT = {
    "record",
    "key",
    "arxiv_version",
    "ids",
    "title",
    "authors",
    "year",
    "msc",
    "arxiv_category",
    "licence",
    "depth",
    "reached_from",
    "reached_by",
    "provenance",
    "citekeys",
    "references_known",
    "references",
    "versions",
    "download",
    "open_pdf",
    "home",
}


def test_identifiers_have_one_spelling_and_a_rank() -> None:
    assert norm("DOI:10.1007/S002220050293") == "doi:10.1007/s002220050293"
    assert norm("arXiv:2207.01652v2") == "arxiv:2207.01652"
    assert norm("doi:10.48550/arXiv.2207.01652") == "arxiv:2207.01652"
    assert ranked(
        ["zbl:0953.14035", "arxiv:alg-geom/9708001", "doi:10.1007/s002220050293", "arXiv:alg-geom/9708001v2"]
    ) == ["doi:10.1007/s002220050293", "arxiv:alg-geom/9708001", "zbl:0953.14035"]


def test_a_record_merges_sources_keeps_its_versions_and_round_trips(tmp_path: Path) -> None:
    w = Record(ids=["doi:10.1/a"], depth=1, year="2020")
    w.add_ids(["zbl:1234.56789", "arxiv:2101.00001v2"])
    w.add_references([Reference(work="doi:10.1/x", identified_by="index"), Reference(text="Some book, 1970")])
    w.add_references([Reference(work="DOI:10.1/X"), Reference(text="Some book, 1970"), Reference(work="doi:10.1/y")])
    assert [r.work for r in w.references] == ["doi:10.1/x", "", "doi:10.1/y"]
    assert w.references_known and w.downloadable == "source"
    version = w.version_for("source")
    # an arXiv artifact of a work homed by its DOI keeps its own name, and a version of the work itself would be `v2`
    assert (version.id, version.local) == ("arxiv:2101.00001v2", "arxiv-2101.00001v2")
    w.add_version(version)
    w.add_version(Version(id="arxiv:2101.00001v2", has_pdf=True))
    assert len(w.versions) == 1 and w.versions[0].has_source and w.versions[0].has_pdf
    path = save(tmp_path, w)
    assert path == tmp_path / "doi" / "10.1_a" / "work.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == CONTRACT and data["record"] == 1 and data["key"] == "doi:10.1/a"
    assert data["versions"] == [
        {
            "id": "arxiv:2101.00001v2",
            "has_source": True,
            "has_pdf": True,
            "method": "",
            "numbering": "",
            "extracted_at": "",
        }
    ]
    assert data["references"][0] == {
        "work": "doi:10.1/x",
        "citekey": "",
        "text": "",
        "identified_by": "index",
    }
    back = load(path)
    assert back is not None and back.ids == w.ids and back.versions == w.versions
    assert back.references[1].text == "Some book, 1970" and back.year == "2020"
    assert set(load_all(tmp_path)) == {"doi:10.1/a"}


def test_a_work_fetched_as_a_pdf_gets_a_version_named_by_its_key() -> None:
    w = Record(ids=["doi:10.1090/x"], open_pdf="https://journal.example/x.pdf")
    version = w.version_for("pdf")
    assert (version.id, version.local, version.has_pdf) == (
        "doi:10.1090/x",
        "main",
        True,
    )  # the home already names the work


# --- the services, as recorded ---------------------------------------------------------------------------


def replay(url: str, headers: dict[str, str]) -> bytes:
    if url not in CRAWL:
        raise net.NotFound(url)
    return str(CRAWL[url]).encode("utf-8")


def service(name: str, cache: Path | None = None) -> net.Service:
    return net.Service(name, cache, replay, budget=budget())


def test_zbmath_gives_identifiers_subjects_and_resolved_references() -> None:
    zb = Zbmath(service("zbmath"))
    gp = zb.by_id("doi:10.1007/s002220050293")
    assert gp is not None and gp.msc == ["14N35", "14L30", "14N10"] and not gp.references
    assert set(gp.ids) == {"zbl:0953.14035", "doi:10.1007/s002220050293", "arxiv:alg-geom/9708001"}
    ar = zb.by_id("arxiv:2207.01652")
    assert ar is not None and len(ar.references) == 46 and "doi:10.1016/j.aim.2025.110434" in ar.ids
    doc = zb.by_document(1112315)
    assert doc is not None and doc.title.startswith("Equivariant Chow groups") and len(doc.references) == 41
    assert zb.by_id("doi:10.9999/nothing") is None


def test_openalex_gives_reference_lists_and_open_copies() -> None:
    oa = OpenAlex(service("openalex"))
    gp = oa.by_id("doi:10.1007/s002220050293")
    assert gp is not None and len(gp.references) == 19 and gp.openalex == "W2034404907"
    listed = oa.batch(gp.references)
    assert len(listed) == 18 and sum(1 for r in listed if r.open_pdf) == 5
    pre = oa.by_id("arxiv:2207.01652")
    assert pre is not None and pre.ids == ["arxiv:2207.01652"] and not pre.references


def test_openalex_sends_its_key_as_a_header_never_in_the_url() -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    def capture(url: str, headers: dict[str, str]) -> bytes:
        seen.append((url, headers))
        return replay(url, headers)

    OpenAlex(net.Service("openalex", None, capture, budget=budget()), key="secret").by_id("doi:10.1007/s002220050293")
    assert seen[0][1] == {"Authorization": "Bearer secret"} and "secret" not in seen[0][0]


def test_arxiv_gives_primary_categories_in_one_request() -> None:
    assert Arxiv(service("arxiv")).categories(["2207.01652", "2205.11114", "alg-geom/9708001"]) == {
        "2207.01652": "math.AG",
        "2205.11114": "math.AG",
        "alg-geom/9708001": "math.AG",
    }


def test_zbmath_by_title_needs_an_author_and_a_strong_match() -> None:
    body = json.dumps(
        {
            "result": [
                {
                    "id": 1,
                    "identifier": "0541.14005",
                    "title": {"title": "Intersection theory"},
                    "year": "1984",
                    "contributors": {"authors": [{"name": "Fulton, William"}]},
                    "msc": [{"code": "14C17"}],
                }
            ]
        }
    )
    asked: list[str] = []

    def transport(url: str, headers: dict[str, str]) -> bytes:
        asked.append(url)
        return body.encode()

    zb = Zbmath(net.Service("zbmath", None, transport, budget=budget()))
    assert zb.by_title("Intersection Theory", [], 1998) is None and not asked
    found = zb.by_title("Intersection Theory: 2nd ed.", ["William Fulton"], 1984)
    assert found is not None and found.msc == ["14C17"]
    assert "ti%3AIntersection+Theory+2nd+ed+%26+au%3Afulton" in asked[0]
    # an exact title and author, any edition
    assert zb.by_title("Intersection Theory", ["William Fulton"], 1998) is not None
    assert zb.by_title("Enumerative geometry", ["William Fulton"], 1984) is None
    body = json.dumps(
        {
            "result": [
                {
                    "id": 2,
                    "title": {"title": "Algebraic stacks", "original": "Champs algébriques"},
                    "year": "2000",
                    "contributors": {"authors": [{"name": "Laumon, Gérard"}]},
                    "msc": [{"code": "14A20"}],
                }
            ]
        }
    )
    # zbMATH's English title is not the one cited
    assert zb.by_title("Champs algébriques", ["Gérard Laumon"], 2000) is not None


# --- the plan, on a synthetic citation graph -------------------------------------------------------------


class FakeZb:
    """zbMATH for a small invented literature."""

    def __init__(self) -> None:
        self.records = {
            "doi:10.1/a": ZbRecord(
                1,
                ["doi:10.1/a", "arxiv:2001.00001"],
                "Paper A",
                ["Alpha, A."],
                2020,
                ["14N35", "55N91"],
                [
                    Reference(work="doi:10.1/x", identified_by="index", msc=["14N35"]),
                    Reference(work="doi:10.1/y", identified_by="index", msc=["55N91"]),
                    Reference(text="Z. Zeta, The Zeta paper, 2021."),
                    Reference(text="P. Pi, Pi, 2019.", zbmath=77),
                ],
            ),
            "doi:10.1/b": ZbRecord(
                2,
                ["doi:10.1/b"],
                "Paper B",
                ["Beta, B."],
                2019,
                ["14D20"],
                [
                    Reference(work="doi:10.1/x", identified_by="index"),
                    Reference(work="doi:10.1/w", identified_by="index"),
                ],
            ),
            "doi:10.1/x": ZbRecord(
                3,
                ["doi:10.1/x", "arxiv:1901.00001"],
                "Paper X",
                ["Xi, X."],
                2019,
                ["14N35"],
                [Reference(work="doi:10.1/deep", identified_by="index")],
            ),
        }
        self.documents = {77: ZbRecord(77, ["doi:10.1/p"], "Paper P", ["Pi, P."], 2019, ["14D23"], [])}

    def by_id(self, ident: str) -> ZbRecord | None:
        return self.records.get(norm(ident))

    def by_document(self, n: int) -> ZbRecord | None:
        return self.documents.get(n)

    def by_title(self, title: str, authors: list[str], year: int | None) -> ZbRecord | None:
        return None


class FakeOa:
    def by_id(self, ident: str) -> OaRecord | None:
        if norm(ident) == "doi:10.1/p":
            return OaRecord("W1", ["doi:10.1/p"], "Paper P", [], 2019, [], "https://journal.example/p.pdf")
        return None

    def batch(self, ids: list[str]) -> list[OaRecord]:
        return []


class FakeArxiv:
    def metadata(self, ids: list[str]) -> dict[str, tuple[str, str]]:
        return {"2101.00009": ("math.AG", "v3")}

    def categories(self, ids: list[str]) -> dict[str, str]:
        return {ident: cat for ident, (cat, _v) in self.metadata(ids).items() if cat}


class FakeResolver:
    def candidates(self, q: Query) -> list[Candidate]:
        text = q.text or q.title
        if "Zeta" in text:
            return [Candidate("arxiv:2101.00009", "Crossref", 0.95, "The Zeta paper")]
        if "Paper B" in text:
            return [Candidate("doi:10.1/b", "zbMATH Open", 1.0, "Paper B")]
        if "Weakly" in text:
            return [Candidate("doi:10.1/weak", "Crossref", 0.81, "Weakly similar paper")]
        return []


def fakes(zb: object | None = None, oa: object | None = None) -> Clients:
    return Clients(zb or FakeZb(), oa or FakeOa(), FakeArxiv(), FakeResolver())


BIB = """@article{A20, title = {Paper A}, author = {Alpha, A.}, doi = {10.1/a}}
@article{B19, title = {Paper B}, author = {Beta, B.}, year = {2019}}
@misc{C00, title = {Unfindable}, author = {Gamma, C.}}
"""


def keeping(root: Path, *, bib: str = BIB, **kw: object) -> Settings:
    """A corpus seeded from `bib`, depth 2, keeping 14D and 14N, and math.AG for works with no MSC code."""
    settings = corpus(root, depth=2, subjects=["14D", "14N"], categories=["math.AG"], **kw)
    return replace(settings, bib=[seed_file(root, bib)])


def test_the_plan_follows_references_within_the_subjects_and_orders_by_depth_then_citations(tmp_path: Path) -> None:
    settings = keeping(tmp_path)
    made = plan(settings, clients=fakes())
    assert made.subjects == ["14D", "14N"] and made.categories == ["math.AG"]
    assert made.order[:2] == ["doi:10.1/a", "doi:10.1/b"]
    assert made.order[2] == "doi:10.1/x"  # cited by both A and B
    assert set(made.order) == {"doi:10.1/a", "doi:10.1/b", "doi:10.1/x", "doi:10.1/p", "arxiv:2101.00009"}
    excluded = {e["id"]: e["why"] for e in made.excluded}
    assert excluded == {"doi:10.1/y": "outside the subjects", "doi:10.1/w": "no MSC code and no arXiv category"}
    assert [u["citekey"] for u in made.unidentified] == ["C00"]
    c = made.counts
    assert (c["works"], c["excluded"], c["from_arxiv"], c["open_copies"], c["metadata_only"]) == (5, 2, 3, 1, 1)
    assert c["bound"] == 2  # B by its entry, Z by its text
    records = load_all(settings.works_dir)
    assert records["doi:10.1/x"].reached_from == ["doi:10.1/a", "doi:10.1/b"]
    assert records["arxiv:2101.00009"].arxiv_category == "math.AG"  # no MSC code, kept by its category
    assert records["doi:10.1/p"].downloadable == "pdf" and records["doi:10.1/p"].reached_by == "index"
    assert records["doi:10.1/a"].citekeys == ["A20"] and records["doi:10.1/a"].home == "doi/10.1_a"
    assert not any("deep" in k for k in records)  # depth 2 stops there
    assert load_plan(settings) is not None and made.payload() == load_plan(settings).payload()


def test_a_strong_match_is_bound_as_the_works_identity_and_a_weak_one_is_not(tmp_path: Path) -> None:
    settings = keeping(tmp_path)
    made = plan(settings, clients=fakes())
    records = load_all(settings.works_dir)
    b = records["doi:10.1/b"]  # its entry declares nothing; a lookup bound it
    assert (b.reached_by, b.provenance, b.citekeys) == ("lookup", "resolved", ["B19"])
    a = records["doi:10.1/a"]  # its entry declares a DOI
    assert (a.reached_by, a.provenance) == ("declared", "declared")
    bound = {x["id"]: x for x in made.bound}
    assert bound["doi:10.1/b"]["citekey"] == "B19" and bound["doi:10.1/b"]["confidence"] == 1.0
    assert bound["doi:10.1/b"]["source"] == "zbMATH Open" and bound["doi:10.1/b"]["title"] == "Paper B"

    weak = keeping(tmp_path / "weak", bib="@misc{W, title = {Weakly matched}, author = {Delta, D.}}\n")
    made = plan(weak, clients=fakes())
    assert made.order == [] and made.counts["unidentified"] == 1 and made.counts["bound"] == 0
    left = made.unidentified[0]
    assert left["why"] == "no strong match" and left["candidate"] == "doi:10.1/weak" and left["confidence"] == 0.81


def test_a_seed_named_by_its_identifier_needs_no_bibliography(tmp_path: Path) -> None:
    settings = corpus(tmp_path, works=["arxiv:2001.00001"], depth=1)
    made = plan(settings, clients=fakes(LinkingZb()))
    assert made.order == ["doi:10.1/a"]  # zbMATH linked the preprint to the published DOI
    record = load_all(settings.works_dir)["doi:10.1/a"]
    assert record.home == "arxiv/2001.00001" and record.reached_by == "declared" and not record.citekeys
    with pytest.raises(PlanRefused, match="not a scheme:value identifier"):
        seeds(corpus(tmp_path / "bad", works=["1709.09864"]))


def test_depth_one_needs_no_subjects_and_other_subjects_keep_other_works(tmp_path: Path) -> None:
    one = plan(replace(keeping(tmp_path), depth=1, subjects=[], categories=[]), clients=fakes())
    assert set(one.order) == {"doi:10.1/a", "doi:10.1/b"} and not one.excluded
    other = plan(replace(keeping(tmp_path / "o"), subjects=["55N91"], categories=[]), clients=fakes())
    assert other.subjects == ["55N"] and other.categories == []
    assert "doi:10.1/y" in other.order and "doi:10.1/x" not in other.order
    why = {e["id"]: e["why"] for e in other.excluded}
    assert why["arxiv:2101.00009"] == "arXiv category not in categories"
    assert "excluded, no MSC code and a category not listed: math.AG 1" in other.summary()


def test_a_plan_needs_subjects_to_go_deeper(tmp_path: Path) -> None:
    with pytest.raises(PlanRefused, match="set subjects"):
        plan(replace(keeping(tmp_path), subjects=[]), clients=fakes())
    with pytest.raises(PlanRefused, match="at least 1"):
        plan(replace(keeping(tmp_path / "z"), depth=0), clients=fakes())


class LinkingZb(FakeZb):
    """zbMATH that also finds A and X by their arXiv numbers, and whose B cites both under the other scheme."""

    def __init__(self) -> None:
        super().__init__()
        self.records["arxiv:2001.00001"] = self.records["doi:10.1/a"]
        self.records["arxiv:1901.00001"] = self.records["doi:10.1/x"]
        self.records["doi:10.1/b"].references.extend(
            [
                Reference(work="arxiv:1901.00001", identified_by="index"),
                Reference(work="doi:10.1/a", identified_by="index"),
            ]
        )


def test_one_work_under_two_identifiers_is_one_record(tmp_path: Path) -> None:
    """Keying on the first identifier seen recorded EGA I twice mid-walk, because sources add identifiers as the walk proceeds."""
    bib = BIB.replace(
        "@article{A20, title = {Paper A}, author = {Alpha, A.}, doi = {10.1/a}}",
        "@article{A20, title = {Paper A}, eprint = {2001.00001}, archiveprefix = {arXiv}}",
    )
    settings = keeping(tmp_path, bib=bib)
    made = plan(settings, clients=fakes(LinkingZb()))
    records = load_all(settings.works_dir)
    assert (
        set(records)
        == set(made.order)
        == {
            "doi:10.1/a",
            "doi:10.1/b",
            "doi:10.1/x",
            "doi:10.1/p",
            "arxiv:2101.00009",
        }
    )
    a = records["doi:10.1/a"]  # declared by its arXiv number, keyed by the DOI zbMATH linked it to
    assert a.home == "arxiv/2001.00001" and a.citekeys == ["A20"]
    assert a.reached_from == ["doi:10.1/b"]  # B cites it by DOI
    assert records["doi:10.1/x"].reached_from == ["doi:10.1/a", "doi:10.1/b"]  # by DOI from A, by number from B


class BookZb(FakeZb):
    """zbMATH that knows a book B cites only by title, not by the DOI B cites it under."""

    def __init__(self) -> None:
        super().__init__()
        self.records["doi:10.1/b"].references.append(Reference(work="doi:10.1/book-2nd-ed", identified_by="index"))
        self.book = ZbRecord(
            9, ["zbl:0541.14005"], "Intersection theory", ["Fulton, William"], 1984, ["14C17", "14-02"], []
        )

    def by_title(self, title: str, authors: list[str], year: int | None) -> ZbRecord | None:
        return self.book if title == "Intersection Theory" and authors == ["William Fulton"] else None


class BookOa(FakeOa):
    def by_id(self, ident: str) -> OaRecord | None:
        if norm(ident) == "doi:10.1/book-2nd-ed":
            return OaRecord("W9", ["doi:10.1/book-2nd-ed"], "Intersection Theory", ["William Fulton"], 1998, [], "")
        return super().by_id(ident)


def test_a_work_zbmath_lacks_by_identifier_is_classified_by_title(tmp_path: Path) -> None:
    settings = replace(keeping(tmp_path), subjects=["14N", "14C"], categories=[])
    made = plan(settings, clients=fakes(BookZb(), BookOa()))
    assert "doi:10.1/book-2nd-ed" in made.order
    book = load_all(settings.works_dir)["doi:10.1/book-2nd-ed"]
    assert book.msc == ["14C17", "14-02"] and "zbl:0541.14005" in book.ids and book.title == "Intersection Theory"
    narrow = replace(keeping(tmp_path / "d"), subjects=["14D"], categories=[])
    only_14d = plan(narrow, clients=fakes(BookZb(), BookOa()))
    gone = next(x for x in only_14d.excluded if x["id"] == "doi:10.1/book-2nd-ed")
    assert gone["why"] == "outside the subjects" and gone["msc"] == ["14C17", "14-02"]
    assert "excluded, outside the subjects:" in only_14d.summary() and "14C 1" in only_14d.summary()


def test_a_survey_counts_what_the_seeds_cite_and_keeps_nothing(tmp_path: Path) -> None:
    settings = replace(keeping(tmp_path), subjects=[])
    found = survey(settings, clients=fakes())
    assert found.cited["primary"] == {"14N": 1, "14D": 1}
    refs = found.references
    # A cites X (14N), Y (55N), Z (a math.AG preprint, found by its text) and P (14D, by zbMATH's number); B cites X again and W
    assert refs["primary"] == {"14N": 1, "55N": 1, "14D": 1}
    assert refs["categories"] == {"math.AG": 1} and refs["neither"] == {"works": 1}
    assert (found.counts["cited"], found.counts["references"], found.counts["unidentified"]) == (2, 5, 1)
    assert "the 5 works they cite, by primary MSC family: 14N 1 · 55N 1 · 14D 1" in found.summary()
    assert load_all(settings.works_dir) == {} and load_plan(settings) is None


# --- the fingerprint -------------------------------------------------------------------------------------


def test_the_fingerprint_refuses_a_plan_the_settings_or_the_seeds_have_outgrown(tmp_path: Path) -> None:
    settings = keeping(tmp_path)
    made = plan(settings, clients=fakes())
    assert made.current(settings) and load_plan(settings).current(settings)
    assert made.fingerprint == fingerprint(settings, seed_texts(settings))
    # the cap is not part of it: it decides how much to fetch, not what the walk found
    assert made.current(replace(settings, cap=1))
    for other in (
        replace(settings, depth=3),
        replace(settings, subjects=["14N"]),
        replace(settings, categories=[]),
        replace(settings, works=["arxiv:2001.00001"]),
    ):
        assert not made.current(other)
    (tmp_path / "seeds.bib").write_text(BIB + "@misc{D, title = {Another}}\n", encoding="utf-8")
    assert not made.current(settings)


# --- fetching --------------------------------------------------------------------------------------------


def eprint(text: str) -> bytes:
    return gzip.compress(text.encode("utf-8"))


def downloaders(arxiv_get: object, web_get: object) -> Downloaders:
    return Downloaders(arxiv=arxiv_get, web=web_get)  # type: ignore[arg-type]


def test_fetch_downloads_in_order_under_the_cap_resumes_and_records_failures(tmp_path: Path) -> None:
    settings = replace(keeping(tmp_path), cap=3)
    made = plan(settings, clients=fakes())
    got: list[str] = []

    def arxiv_get(url: str) -> bytes:
        got.append(url)
        if "1901.00001" in url:
            raise net.ServiceError("arXiv: HTTP 503")
        return eprint(SOURCE)

    def web_get(url: str) -> bytes:
        got.append(url)
        return b"%PDF-1.4 fake"

    report = fetch(settings, made, downloaders=downloaders(arxiv_get, web_get))
    # X fails and takes no place under the cap, so P, next in order, is fetched instead
    assert (report.fetched, report.failed, report.left_out) == (3, 1, 0)
    assert got == [
        "https://arxiv.org/e-print/2001.00001",
        "https://arxiv.org/e-print/1901.00001",
        "https://arxiv.org/e-print/2101.00009",
        "https://journal.example/p.pdf",
    ]
    records = load_all(settings.works_dir)
    a = records["doi:10.1/a"]
    assert a.downloaded and a.download["bytes"] == len(eprint(SOURCE)) and a.download["at"].endswith("Z")
    assert [v.id for v in a.versions] == ["arxiv:2001.00001"] and a.versions[0].has_source
    assert (settings.works_dir / a.home / "arxiv-2001.00001" / "src" / "main.tex").is_file()
    assert any(r.work == "arxiv:1912.06162" for r in a.references)  # its bibliography was read
    assert "HTTP 503" in records["doi:10.1/x"].download["error"] and not records["doi:10.1/x"].downloaded
    p = records["doi:10.1/p"]
    assert (settings.works_dir / p.home / "main" / "paper.pdf").read_bytes().startswith(b"%PDF")
    assert [v.has_pdf for v in p.versions] == [True]
    # a second run counts what is on disk first: the cap is full, so the failure waits
    again = fetch(settings, load_plan(settings) or made, downloaders=downloaders(lambda u: eprint(SOURCE), web_get))
    assert (again.already, again.fetched, again.left_out) == (3, 0, 1)
    more = fetch(replace(settings, cap=4), made, downloaders=downloaders(lambda u: eprint(SOURCE), web_get))
    assert (more.already, more.fetched, more.left_out) == (3, 1, 0)
    where = status(settings)
    assert (where.works, where.downloaded, where.failed, where.metadata_only) == (5, 4, 0, 1)
    assert where.plan is not None and where.plan["current"] is True and "4 downloaded" in where.summary()


def test_a_replan_keeps_what_was_fetched_and_estimates_from_it(tmp_path: Path) -> None:
    settings = replace(keeping(tmp_path), cap=10)
    made = plan(settings, clients=fakes())
    assert made.estimate["bytes"] == 3 * 3_000_000 + 1_000_000  # nothing fetched yet: the assumed sizes
    fetch(replace(settings, cap=1), made, downloaders=downloaders(lambda u: eprint(SOURCE), lambda u: b"%PDF-1.4"))
    again = plan(settings, clients=fakes())
    assert again.estimate["bytes"] == 2 * len(eprint(SOURCE)) + 1_000_000
    assert again.counts["already_fetched"] == 1
    kept = load_all(settings.works_dir)["doi:10.1/a"]
    assert kept.downloaded and [v.id for v in kept.versions] == ["arxiv:2001.00001"]


def test_a_source_already_unpacked_counts_against_the_cap_and_gets_a_version(tmp_path: Path) -> None:
    settings = keeping(tmp_path)
    (settings.works_dir / "doi" / "10.1_x" / "arxiv-1901.00001" / "src").mkdir(parents=True)
    made = plan(settings, clients=fakes())
    x = load_all(settings.works_dir)["doi:10.1/x"]
    assert x.downloaded and x.download["kind"] == "source" and made.counts["already_fetched"] == 1
    assert [v.id for v in x.versions] == ["arxiv:1901.00001"] and x.versions[0].has_source


def test_fetch_stops_when_arxiv_keeps_refusing_and_an_interruption_keeps_what_was_fetched(tmp_path: Path) -> None:
    settings = keeping(tmp_path)
    made = plan(settings, clients=fakes())
    asked: list[str] = []

    def refuse(url: str) -> bytes:
        asked.append(url)
        raise net.ServiceError(f"{url}: HTTP 406 Not Acceptable")

    report = fetch(settings, made, downloaders=downloaders(refuse, lambda u: b"%PDF-1.4"))
    assert len(asked) == 3 and report.failed == 3 and "refused 3 downloads in a row" in report.stopped
    calls = 0

    def interrupted_on_the_second(url: str) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return eprint(SOURCE)

    report = fetch(settings, made, downloaders=downloaders(interrupted_on_the_second, lambda u: b"%PDF-1.4"))
    assert report.fetched == 1 and report.stopped.startswith("interrupted")
    again = fetch(settings, made, downloaders=downloaders(lambda u: eprint(SOURCE), lambda u: b"%PDF-1.4"))
    assert (again.already, again.fetched, again.stopped) == (1, 3, "")


def test_a_download_that_is_not_a_pdf_is_a_failure(tmp_path: Path) -> None:
    settings = keeping(tmp_path)
    made = plan(settings, clients=fakes())
    report = fetch(settings, made, downloaders=downloaders(lambda u: eprint(SOURCE), lambda u: b"<html>paywall</html>"))
    assert report.failed == 1 and "not a PDF" in report.errors[0]
    p = load_all(settings.works_dir)["doi:10.1/p"]
    assert not (settings.works_dir / p.home / "main" / "paper.pdf").exists()
