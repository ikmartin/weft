# The digest contract

A digest is a LaTeX file holding another paper's results as external nodes, obeying loom's source contract. Two independent implementations produce them — loom's `digest extract`, for the papers an author cites, and weft's extraction, for a corpus — and a digest written by either is readable by both. This file is what they must agree on; where they disagree, one of them has a bug.

Normative statements are numbered. Everything else is explanation. The conformance fixture under `tests/responses` and `demos/synthetic` exercises the numbered statements; a divergence should be a failing test rather than a discovery.

## 1. The file

1.1. One digest describes one work, in one file: `digests/<citekey>.tex` in a quilt, `works/<home>/<version>/digest.tex` in a corpus. Nothing else in either layout is a digest.

1.2. A file is a digest when its first twenty lines contain a `% !LOOM digest: <CITEKEY>` directive. A corpus with no citekeys writes the work's global identifier there.

1.3. A digest is never compiled as a document of its own. It is `\input` by a bundle, or by a fallback document a tool writes around it.

## 2. The provenance header

Directives, one per line, in this order, before any content:

2.1. `digest:` — required. The citekey, or a global identifier in a corpus.

2.2. `prefix:` — the slug every id in this file carries. Declared rather than derived, because a citekey is not a stable name for a work.

2.3. `extracted-from:` — the artifact the statements were read from, as `<scheme>:<value>` (`arxiv:1709.09864v2`), or `local:<filename>` when it was a file on disk. Required when `method:` is `extract`.

2.4. `published-as:` — the artifact a bibliography cites, when that differs from 2.3. These are two facts, not two spellings of one: a preprint and its journal version carry different page numbers, so a locator naming one is wrong about the other.

2.5. `method:` — `extract` (read from a source by a tool), `manual` (written by a person), or `pdf` (read from a PDF; a corpus records the extractor and its version in `tool:`).

2.6. `proofs:` — `none` or `verbatim`. **`none` is the default and is what a paper's own quilt writes**: a digest there is an index, and a proof of someone else's theorem is not what an author is keeping. A corpus writes `verbatim` where the work's licence allows it, because a library that cannot show why a theorem is true cannot answer whether an argument transfers. A digest says on its face what it contains, so a corpus can be audited by reading headers.

2.7. `created:` — ISO 8601, when the file was written.

2.8. `requires:` — packages beyond `amsmath`, `amsthm` and `loom` that the statements need. Packages cannot be scoped, so a consumer loads these or reports `loom:missing-package`.

2.9. `numbering: emulated` — present when the numbers come from counting rather than from a compile's `.aux`.

2.10. Unknown directives are kept and ignored. A reader must not fail on a directive it does not know.

## 3. Ids

3.1. A result's id is `<prefix>-<paperlocal>`, where `paperlocal` is letters, digits, dots and hyphens. Dots are legal.

3.2. Extraction names a numbered result `<prefix>-<abbrev>-<number>`, with `abbrev` from a fixed map: `thm, lem, prop, cor, def, rem, ex, constr, conj`; an environment outside the map contributes its own slugged name, or `res`. An unnumbered result is `<prefix>-<abbrev>-star-<n>`, `n` counting from 1 in document order.

3.3. A sectioning unit is `<prefix>-sec-<number>`.

3.4. Standing assumptions and conventions go in one `<prefix>-setup` node.

3.5. The **first** `\label` inside a node is its id. Every later label is an alias, and the paper's own labels are kept as aliases, prefixed, so two papers' `eq:main` can sit in one bundle. An id-shaped alias lets one node answer another version's numbering.

3.6. Two works whose prefixes collide is an error the tools report, never a silent merge.

## 4. What a node is

4.1. A result is a theorem-like environment whose `\begin` and `\end` are each alone on their line. This is what lets a region be located exactly.

4.2. A node's title carries its citation: `\begin{<env>}[{\cite[<locator>]{<citekey>}}]\label{<id>}`. The locator is the paper's own name for the result (`Theorem 4.1`, `Standing assumptions`), optionally with a page (`, p.~9`). This is what makes a citation with a locator a checkable edge.

4.3. Statements are **verbatim**. A paraphrase is a second reading of the hypotheses, and a reader cannot tell which they are looking at.

4.4. A proof is present only under `proofs: verbatim` (2.6), as a `proof` environment following its statement.

4.5. `\uses{…}` inside a node records what that result depends on **within the same paper**, taken from the references in its proof.

4.6. A digest node has no proof obligations of its own: nothing in it may be marked incomplete, and no tool may ask an author to prove someone else's theorem.

## 5. Macros

5.1. Macros the statements need are expanded where they can be. What cannot be expanded goes in one block between `% !LOOM begin macros` and `% !LOOM end macros`, wrapped `\begingroup … \endgroup`, with `\let\NAME\undefined` before each definition so a redefinition cannot leak.

5.2. The block is loaded, never shown: a reader's document view of a digest starts after `% !LOOM end macros`.

5.3. `\newenvironment` and `enumitem` `\newlist` definitions the statements use belong in the block. Environment names are the consuming quilt's own; an importing tool does not remap them.

## 6. Locators

6.1. A citation `\cite[<postnote>]{<citekey>}` names a result of that work when the postnote matches one, after normalising both sides: lowercase; expand abbreviations; `\S` and `§` become `section`; a Roman numeral after a taxon word becomes a digit; drop pages, part selectors, braces, `~`, abbreviation periods, and filler words (`see`, `cf`, `also`, `e.g.`, `i.e.`, `the`, `of`, `in`, `compare`).

6.2. A node answers to its normalised locator, to each part of it, and to `<taxon> <number>` read off its id **and off every id-shaped alias**. `<prefix>-setup` also answers `standing assumptions`.

6.3. A postnote naming several results splits on `,`, `;`, `and`, `&`, and a bare number inherits the preceding taxon.

6.4. A citation inside the digest of the work it cites matches nothing: those citations are the nodes' own titles.

6.5. A postnote that matches nothing while a digest exists is reported, never guessed at.

## 7. What a digest never contains

7.1. No proof under `proofs: none`, under any circumstances.

7.2. No claim about the citing author's own work, no acceptance, no review state. A digest is a reading of someone else's paper.

7.3. No text whose licence the sharer has not considered. Verbatim statements are unproblematic in a private corpus and become a question when one is published; that is policy recorded in the header, not law enforced by a tool. This file is not legal advice.

## 8. What a corpus adds

8.1. A digest belongs to a **version**: one work's preprint and its published article are two digests, because numbering is a property of the artifact and because content differs — a published version can drop a result its preprint states.

8.2. `works/<home>/<version>/results.json` carries the same results as data, keyed `<version-id>#<paperlocal>`, with the statement and proof text, the taxon, the number, the aliases, the page, the extraction method and the numbering. The digest is the document; the JSON is the index's source.

8.3. Edges a corpus records beside the results are exactly the two a paper states: a citation with a locator, resolved by §6 to another version's result, and a citation without one, which names a work and no result. Nothing else is inferred.
