"""What a citation names, and what a result answers to: §6 of the digest contract."""

from __future__ import annotations

from weft.locators import forms_for, locator_of, match, normalize, parts


def test_normalising_a_locator_drops_what_is_not_the_name(  # §6.1
) -> None:
    assert normalize("Theorem~9.4") == "theorem 9.4"
    assert normalize("see Prop. 3.2 (ii), p.~9") == "proposition 3.2"
    assert normalize("\\S 2") == "section 2"
    assert normalize("§2.3") == "section 2.3"
    assert normalize("Theorem II") == "theorem 2"
    assert normalize("pp.~12--14") == ""
    assert normalize("Lemma a.31") == "lemma a.31", "the dot inside a number is not an abbreviation's period"


def test_a_postnote_naming_several_results_splits(  # §6.3
) -> None:
    assert parts("Theorems 1.1 and 2.3; Lemma 4") == ["theorem 1.1", "theorem 2.3", "lemma 4"]
    assert parts("Theorem 2.1, 2.2") == ["theorem 2.1", "theorem 2.2"], "a bare number inherits the taxon before it"
    assert parts("p. 9") == []


def test_a_result_answers_to_its_locator_its_number_and_its_aliases(  # §6.2
) -> None:
    forms = forms_for("thm-4.1", "Theorem", "4.1", ["thm-A.20"], "Theorem 4.1, p.~9")
    assert "theorem 4.1" in forms and "theorem a.20" in forms
    assert "" not in forms
    setup = forms_for("setup", "", "", [], "Standing assumptions")
    assert "standing assumption" in setup or "standing assumptions" in setup


def test_matching_returns_every_candidate_a_postnote_names(  # §6.1, and the ambiguity the caller logs
) -> None:
    a = ("a", forms_for("thm-9.4", "Theorem", "9.4", [], "Theorem 9.4"))
    b = ("b", forms_for("lem-2.1", "Lemma", "2.1", [], "Lemma 2.1"))
    also_94 = ("c", forms_for("thm-9.4", "Theorem", "9.4", [], "Theorem 9.4"))
    assert match("Theorem 9.4", [a, b]) == ["a"]
    assert match("Theorem 9.4", [a, b, also_94]) == ["a", "c"], "several matches is an ambiguity, not a choice"
    assert match("Theorem 9.4 and Lemma 2.1", [a, b]) == ["a", "b"]
    assert match("p. 9", [a, b]) == []


def test_a_digest_nodes_title_carries_its_locator(  # §4.2
) -> None:
    assert locator_of("{\\cite[Theorem 4.1]{Man12}}") == "Theorem 4.1"
    assert locator_of("no citation here") is None
    assert locator_of(None) is None
