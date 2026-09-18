"""The handoff to a paper's own tool: an entry carrying every identifier, in the form loom's reader accepts."""

from __future__ import annotations

from weft.bib import parse_bib
from weft.bibtex import citekey, entry_for
from weft.identity import declared, identify
from weft.model import Work

PAPER = Work(
    key="arxiv:1709.09864",
    ids=["doi:10.1090/x", "arxiv:1709.09864v3", "mr:1234567", "zbl:0953.14035"],
    title="Localization of virtual classes",
    authors=["Surname, Given", "Other, A. B."],
    year="2017",
)


def test_an_entry_names_every_identifier_in_the_fields_a_reader_keys_on() -> None:
    text = entry_for(PAPER)
    assert text.startswith("@article{doi101090x,") and text.endswith("}\n")
    entry = parse_bib(text)["doi101090x"]
    # the field names loom's identity reader looks at, and nothing else
    assert set(entry.fields) == {"title", "author", "year", "doi", "eprint", "eprinttype", "mrnumber", "zbl"}
    assert entry.fields["doi"] == "10.1090/x"
    assert entry.fields["eprint"] == "1709.09864v3" and entry.fields["eprinttype"] == "arXiv"
    assert entry.fields["mrnumber"] == "1234567" and entry.fields["zbl"] == "0953.14035"
    assert entry.fields["author"] == "Surname, Given and Other, A. B."
    assert entry.fields["title"] == "Localization of virtual classes" and entry.fields["year"] == "2017"
    # read back, the entry states the same four identifiers, DOI first, and the eprint keeps its version
    assert [str(w) for w in declared(entry)] == [
        "doi:10.1090/x",
        "arXiv:1709.09864v3",
        "MR:1234567",
        "Zbl:0953.14035",
    ]


def test_a_work_with_no_year_is_a_misc_and_a_work_with_no_identifier_keeps_its_synthetic_key() -> None:
    book = Work(key="work:ab12cd34", ids=["work:ab12cd34"], title="A book", authors=["Nobody, N."])
    entry = entry_for(book)
    assert entry.startswith("@misc{workab12cd34,")
    parsed = parse_bib(entry)["workab12cd34"]
    assert "year" not in parsed.fields and not declared(parsed)
    # nothing is declared, so a reader gives it a synthetic identity of its own rather than inventing one
    assert identify(parsed)[0].scheme == "work"


def test_the_key_is_the_ranked_first_identifier_stripped_of_punctuation() -> None:
    assert citekey("arxiv:math/0605234v2") == "arxivmath0605234v2"
    preprint = Work(key="arxiv:1709.09864", ids=["arxiv:1709.09864", "zbl:0953.14035"], title="T", year="2017")
    assert entry_for(preprint).startswith("@article{arxiv170909864,")  # a preprint outranks a review number


def test_an_arxiv_doi_is_written_as_the_preprint_it_names() -> None:
    """arXiv mints DOIs under 10.48550, so such a DOI names the preprint: one artifact, one field, and no `doi` a reader would have to normalise back."""
    preprint = Work(
        key="arxiv:2401.00001",
        ids=["arxiv:2401.00001", "doi:10.48550/arxiv.2401.00001"],
        title="Tropical cycles",
        year="2024",
    )
    text = entry_for(preprint)
    assert text.startswith("@article{arxiv240100001,")
    entry = parse_bib(text)["arxiv240100001"]
    assert "doi" not in entry.fields and entry.fields["eprint"] == "2401.00001"
    assert [str(w) for w in declared(entry)] == ["arXiv:2401.00001"]
