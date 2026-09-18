# demos/synthetic

A fabricated corpus, written by `scripts/make_synthetic.py` and committed. **Nothing in it is real**: the authors, titles, identifiers, URLs and mathematics are invented, so no third party's text is carried here and the whole thing can live in the repository. Regenerate it with

    uv run python scripts/make_synthetic.py

The script is deterministic and idempotent -- fixed dates, no network, no randomness -- so a regeneration that changes a byte is a change in the generator, and `git status` says so.

## What is in it, and what each piece is for

- **`weft.toml`** -- two seed works, `depth = 2`, `subjects = ["14N"]`, `cap = 5`. Exercises settings loading and a depth greater than one with the subjects actually stated.
- **`arxiv:2401.00001`, two versions.** v1 states a theorem, a lemma and a proposition; v2 states the theorem and the proposition and **drops the lemma**, which renumbers the proposition. This is the case the whole per-version data model exists for: results belong to a version, and "the same result in two versions" is a mapping and not an identity.
- **`arxiv:2401.00002`, one version.** The second seed, cited by the first and citing it back, so the citation graph has a cycle and a walk has to cope with one.
- **`doi:10.4171/synth.0003`, metadata-only.** Depth 2, no source and no PDF, reached from both seeds by lookup rather than by a printed identifier. It is the node that is in the citation graph and absent from the result graph, and its key has a slash in the value, which a home sanitises away so one identifier stays one directory.
- **Each version with a source: `works/<home>/<version-local>/src/main.tex`.** `\newtheorem` declarations to read numbering off, labelled statements, and in every proof one `\cite[Theorem 1.1]{other}` (a locator citation, §7's first case) and one bare `\cite{third}` (an unspecified citation, §7's second case).
- **An inlined `\begin{thebibliography}` in every source**, one `\bibitem` printing an arXiv id and one printing nothing identifying at all. Both real seed papers inlined their bibliography and 9% of their entries carried a usable identifier; this is that situation in miniature, and it is what the `\bibitem` parser and the lookup path are tested against.
- **No `results.json` and no PDFs.** Extraction is M2's, so nothing here claims to be extraction output; `rebuild` reads `results.json` when it is there and the tests write one by hand to check that it does.
