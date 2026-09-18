"""The BibTeX reader: the entry forms real seed files hold."""

from __future__ import annotations

from weft.bib import match_group, parse_bib

FILE = r"""
@string{im = {Invent. Math.}}
@comment{a comment block, not an entry}

@article{Man12,
  author = {Manolache, Cristina},
  title = {Virtual pull-backs},
  journal = im,
  year = {2012},
  doi = {10.1090/S1056-3911-2011-00606-1},
}

@book(Sil99,
  author = "Silverman, Joseph H.",
  title = {Advanced Topics in the
           Arithmetic of Elliptic Curves},
  year = 1999
)

@misc{Ar22, author = {Aranha, D. and Khan, A.}, title = {Virtual localization revisited}, eprint = {2207.01652}, archiveprefix = {arXiv}, version = {3}}
"""


def test_entries_fields_and_the_forms_real_files_use() -> None:
    entries = parse_bib(FILE)
    assert list(entries) == ["Man12", "Sil99", "Ar22"]
    assert entries["Man12"].type == "article" and entries["Man12"].fields["doi"] == "10.1090/S1056-3911-2011-00606-1"
    # a parenthesised entry, a quoted value, a value split over lines, and a bare number
    assert entries["Sil99"].fields["title"] == "Advanced Topics in the Arithmetic of Elliptic Curves"
    assert entries["Sil99"].fields["author"] == "Silverman, Joseph H." and entries["Sil99"].fields["year"] == "1999"
    assert entries["Ar22"].eprint == "2207.01652" and entries["Ar22"].version == "3"


def test_a_version_is_read_off_the_eprint_when_no_field_names_it() -> None:
    entry = next(iter(parse_bib("@misc{x, eprint = {2207.01652v2}}").values()))
    assert entry.version == "2"


def test_brace_matching_crosses_newlines_and_reports_an_unbalanced_group() -> None:
    assert match_group("{a\nb}c", 0) == 5
    assert match_group("{a {b} c}", 0) == 9
    assert match_group("{a", 0) == -1 and match_group("a}", 0) == -1
