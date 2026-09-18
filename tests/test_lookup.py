"""Identifying a work by title, surnames and year: the scoring, the two services as recorded, and the order they are asked in."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from support import RESOLVE, budget
from weft import lookup as L
from weft.bib import BibEntry
from weft.crawl.net import NotFound, Service, ServiceError

EDIDIN = BibEntry(
    "edidin-graham_LocalizationEquivariantIntersection1998",
    "article",
    {
        "title": "Localization in Equivariant Intersection Theory and the {{Bott}} Residue Formula",
        "author": "Edidin, Dan and Graham, William",
        "year": "1998",
    },
)
SILVERMAN = BibEntry(
    "silverman_AdvancedTopicsArithmetic1999",
    "book",
    {"title": "Advanced Topics in the Arithmetic of Elliptic Curves", "author": "Silverman, Joseph H.", "year": "1999"},
)


class Recorded:
    """An injected transport answering from the recorded responses, counting what it was asked."""

    def __init__(self, zbmath: str | None, crossref: str | None = None, fail: set[str] | None = None) -> None:
        self.answers = {"zbmath": zbmath, "crossref": crossref}
        self.fail = fail or set()
        self.urls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> bytes:
        self.urls.append(url)
        service = "zbmath" if "zbmath" in url else "crossref"
        if service in self.fail:
            raise ServiceError(f"{service}: HTTP 503")
        name = self.answers[service]
        data: dict[str, Any] = (
            RESOLVE[name] if name else ({"result": []} if service == "zbmath" else {"message": {"items": []}})
        )
        return json.dumps(data).encode("utf-8")


def resolver(
    transport: L.Resolver | Any, cache: Path | None = None, contact: str = "", refresh: bool = False
) -> L.Resolver:
    """A resolver whose two services share one budget and one cache, as the real one does."""
    b = budget()
    return L.Resolver(
        Service("zbmath-lookup", cache, transport, refresh, b),
        Service("crossref", cache, transport, refresh, b),
        contact=contact,
    )


def test_a_query_is_the_entry_without_its_markup() -> None:
    q = L.query_for(EDIDIN)
    assert q.title == "Localization in Equivariant Intersection Theory and the Bott Residue Formula"
    assert q.surnames == ("Edidin", "Graham") and q.year == "1998"
    assert L.query_for(
        BibEntry("x", "misc", {"title": "Sch\\'emas en groupes", "author": "Demazure, M. and others"})
    ).surnames == ("Demazure",)


def test_biblatex_dates_count_as_years() -> None:
    assert L.query_for(BibEntry("x", "article", {"title": "T", "date": "1998-06"})).year == "1998"


def test_scoring_is_by_title_then_author_then_year() -> None:
    q = L.query_for(EDIDIN)
    exact = L.score(
        q, "Localization in equivariant intersection theory and the Bott residue formula", ["Edidin, Dan"], "1998"
    )
    assert exact == 1.0
    # a record that drops the subtitle still matches strongly
    assert L.score(q, "Localization in equivariant intersection theory", ["Dan Edidin"], "1998") >= L.STRONG
    # the right title alone is only possible: a different book can share a title
    assert (
        L.POSSIBLE
        <= L.score(q, "Localization in equivariant intersection theory and the Bott residue formula", [], "")
        < L.STRONG
    )
    assert L.score(q, "Equivariant intersection theory", ["Edidin, Dan"], "1998") < L.POSSIBLE


def test_a_formatted_reference_is_scored_by_what_it_contains() -> None:
    text = "A. Arabia, Cycles de Schubert et cohomologie equivariante de K/T, Invent. Math. 85 (1986), 39-52."
    q = L.Query(text, (), "1986", text)
    assert L.score(q, "Cycles de Schubert et cohomologie équivariante de K/T", ["Arabia, Alberto"], "1986") == 1.0
    assert L.score(q, "Equivariant cohomology", ["Brion, M."], "1986") < L.POSSIBLE


def test_zbmath_answers_with_a_doi_and_the_preprint_it_knows() -> None:
    http = Recorded("zbmath_edidin_graham")
    found = resolver(http).candidates(L.query_for(EDIDIN))
    assert [c.id for c in found] == ["doi:10.1353/ajm.1998.0020"]
    # the fetchable preprint before the review number
    assert found[0].also == ["arxiv:alg-geom/9508001", "zbl:0980.14004"]
    assert found[0].strength == "strong" and found[0].source == "zbMATH Open"
    # a strong match with a DOI needs nothing from Crossref
    assert len(http.urls) == 1 and "ti%3ALocalization" in http.urls[0]
    assert found[0].evidence()["confidence"] == found[0].confidence


def test_crossref_is_asked_for_a_doi_when_zbmath_has_none_and_picks_the_book_not_its_chapters() -> None:
    http = Recorded("zbmath_silverman", "crossref_silverman")
    found = resolver(http).candidates(L.query_for(SILVERMAN))
    # the book; its chapters rank above it at Crossref and are discarded here
    assert [c.id for c in found] == ["doi:10.1007/978-1-4612-0851-8"]
    assert found[0].also == ["zbl:0911.14015"]  # zbMATH's record of the same book, pooled into one candidate
    assert found[0].source == "zbMATH Open, Crossref"
    assert len(http.urls) == 2


def test_a_404_is_no_match_rather_than_a_failure() -> None:
    def transport(url: str, headers: dict[str, str]) -> bytes:
        if "zbmath" in url:
            raise NotFound(url)
        return json.dumps({"message": {"items": []}}).encode("utf-8")

    assert resolver(transport).candidates(L.Query("Stacks Project", ("The Stacks project authors",))) == []


def test_one_service_failing_is_not_a_failed_lookup_but_both_are() -> None:
    found = resolver(Recorded("zbmath_silverman", "crossref_silverman", fail={"zbmath"})).candidates(
        L.query_for(SILVERMAN)
    )
    assert found and found[0].source == "Crossref"
    with pytest.raises(L.LookupRefused):
        resolver(Recorded(None, None, fail={"zbmath", "crossref"})).candidates(L.query_for(SILVERMAN))


def test_a_query_with_no_title_is_refused_rather_than_sent() -> None:
    http = Recorded("zbmath_edidin_graham")
    with pytest.raises(L.LookupRefused, match="no title"):
        resolver(http).candidates(L.Query(""))
    assert not http.urls


def test_an_answer_is_cached_and_not_asked_for_twice(tmp_path: Path) -> None:
    http = Recorded("zbmath_edidin_graham")
    resolver(http, cache=tmp_path).candidates(L.query_for(EDIDIN))
    again = resolver(http, cache=tmp_path)
    again.candidates(L.query_for(EDIDIN))
    assert len(http.urls) == 1 and again.requests == 0
    resolver(http, cache=tmp_path, refresh=True).candidates(L.query_for(EDIDIN))
    assert len(http.urls) == 2


def test_contact_goes_to_crossref_only_when_set() -> None:
    http = Recorded("zbmath_silverman", "crossref_silverman")
    resolver(http, contact="author@example.org").candidates(L.query_for(SILVERMAN))
    assert "mailto=author%40example.org" in http.urls[1] and "mailto" not in http.urls[0]
    plain = Recorded("zbmath_silverman", "crossref_silverman")
    resolver(plain).candidates(L.query_for(SILVERMAN))
    assert all("mailto" not in u for u in plain.urls)


def test_a_candidate_becomes_a_resolved_identifier() -> None:
    found = resolver(Recorded("zbmath_edidin_graham")).candidates(L.query_for(EDIDIN))
    assert L.as_workid(found[0]).provenance == "resolved" and L.as_workid(found[0]).scheme == "doi"
