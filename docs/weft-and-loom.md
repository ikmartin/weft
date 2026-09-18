# weft and loom: the boundary, the seam, and what loom gives up

## 1. Why they are separate tools

loom is a tool for **a single math project**: your results, their dependencies, what you have accepted, what went stale, a document that compiles from its root with plain `pdflatex` and on Overleaf. weft is a tool for **other people's results at corpus scale**: a crawled library, extracted statements and proofs, links between them, and a query surface for an agent.

The invariants pull in opposite directions:

| | loom | weft |
| --- | --- | --- |
| unit | one quilt, one author's paper | a corpus: thousands of works, 10⁴–10⁵ results |
| core acts | accept, stale, compile, identity test | crawl, extract, link, index, serve |
| masters | every quilt has one; the paper must compile | none; nothing here is compiled as a document |
| acceptance | the point of the tool | meaningless; provenance and verification take its place |
| data path | rescan the tree, one `manifest.json` | files plus an index, SQLite then Postgres, possibly on another machine |
| dependencies | TeX, and nothing else | HTTP clients, a database, eventually a model |
| network | never without consent, per command | the normal condition of operation |
| content | your own words | other people's text, verbatim, at scale |
| licence posture | yours to publish | private by default; sharing is a deliberate act |

One codebase serving both would make every one of loom's promises conditional. Keeping them apart lets loom stay small and lets weft take on a database, a crawl budget and a research problem without asking loom's users to carry any of it.

## 2. The boundary

**weft knows nothing about quilts. loom knows nothing about corpora.**

- weft never writes into a quilt: no pull, no import, no materialised digest, no dependency a build needs.
- weft never reads a quilt. An agent that wants both sides reads the quilt itself — through loom, or the files — and queries weft separately.
- Nothing flows from loom into weft. Your digests, your acceptances and your own paper stay yours; a contribution protocol is explicitly not planned.

## 3. The seam

It is a **handoff, not a protocol**.

You browse weft, or an agent crawls it on your behalf, and something turns out to be worth citing. Then:

1. weft names the work by its global identifier and emits a bibliography entry carrying every identifier it holds (`weft bib arxiv:1709.09864`).
2. That entry goes into your quilt's `refs.bib`. It is now **a depth-1 work of your paper**, indistinguishable from one you added by hand.
3. loom does the rest as it already does: identify (`refs resolve` if needed), fetch (`digest fetch`), extract under **your** citekey and prefix (`digest extract`), and from then on the digest is yours — your reading, your locators, your `\uses`, your ledger.

What crosses the seam is therefore an **identifier and a bibliography entry**, and both are formats that predate either tool. Nothing in a quilt depends on weft having run, so a quilt stays self-contained, compiles anywhere, and is reproducible years later with no corpus in sight.

While you are only *looking*, weft's keys stay global — `arxiv:1709.09864v3#thm-4.1` — because a result you have not decided to use has no place in your paper's namespace. The rename into `<citekey>-thm-4.1` happens if and when loom extracts its own digest, which it already does.

### Consequences worth stating

- **No id-stability contract between the tools.** weft may renumber, re-extract or re-key its corpus without touching any quilt.
- **No versioning contract.** A quilt pins nothing of weft's; the paper it cites is pinned the ordinary way, by the bibliography entry and the artifact loom fetched.
- **No acceptance transfer.** weft's statements are machine-extracted and unverified; loom's ledger records what a human accepted, about a digest that human's own tool produced.
- **Two digests of one paper may differ**, weft's and yours, and that is correct: yours records what you read and what you use; weft's records what a crawler could extract.

### What the seam could become later, and what it must not

Plausible, if wanted: an MCP server (weft already plans one) that loom's AI layer can reach, so an agent advising your project queries the library with your consent; an arras artifact projected from weft that you keep open beside your quilt; a "cite this" action that appends the entry to `refs.bib` for you.

Ruled out unless a decision reverses this document: weft writing into a quilt; a quilt's build, lint or compile reaching for weft; a shared code dependency in either direction. **A quilt must build with no weft installed, and weft must run with no quilt in existence.**

## 4. Code: copied, not depended upon

weft copies the code it needs from loom and maintains it separately. That is the pattern this workspace already uses successfully: loom and arras share **no code at all**, and are joined by a written interface plus a conformance fixture.

To copy, then refactor freely: `refs/crawl/*` (the crawl), `refs/identity.py` (identifiers, the synthetic key, normalisation), `refs/resolve.py` (lookup and scoring), `scan/bib.py` (the BibTeX reader), `scan/postnote.py` (locator normalisation and matching), `digest/extract.py` and its counter emulation (extraction).

Why copy rather than depend: every one of those files must change in ways loom should not carry — proofs kept rather than dropped, per-version output, batch extraction with a cached `.aux`, an index instead of a full rescan, a PDF adapter later. Depending on `loomtex` would freeze loom's internals into a public API and tie weft's releases to loom's.

**The cost of copying is drift, and drift is paid for with a written contract.** Before the copy: write down the digest contract that both implementations must keep — the header directives, the id grammar, prefixes and aliases, the title-carries-the-locator rule, the locator normalisation table and match forms, and the `proofs:` policy — and extend the shared conformance fixture with digests and their expected locator matches. Then a divergence is a failing test rather than a discovery months later.

## 5. What loom gives up

loom's crawl (`src/loom/refs/crawl/`, nine modules, three CLI commands, `[crawl]` config) is committed and working. It is corpus machinery living in a paper's tool, and it goes to weft in a deliberate change, not by neglect.

**loom keeps** — everything a single project needs:

- the bibliography and its identifiers, including the synthetic key and the arXiv-DOI normalisation;
- `loom refs resolve` — candidates for a work that states no identifier, which loom still refuses to bind (DR-122; where a confirmed identity lives is WQ-23);
- `loom refs add` and `loom refs path` — a PDF you obtained by hand, filed by identifier;
- `loom digest fetch` — one arXiv source for one citekey, at depth 1;
- `loom digest extract`, `import`, the digest format, locator matching, postnote edges, bundles, and the whole review ledger;
- the `refs/<scheme>/<value>/` layout, which the crawl motivated and which stands on its own.

**loom loses:**

- depth past 1: `loom refs crawl plan`, `fetch` and `status`;
- `[crawl]` in `config.toml` — `depth`, `subjects`, `categories`, `cap` — and the MSC and arXiv-category clients that serve them;
- the survey, the subject filter, and the whole idea of a corpus, a library or a work graph beyond the works this paper cites;
- the ambition, recorded in the book, of following citations for their own sake.

**The reduction, concretely:**

1. weft ports `refs/crawl/*` and makes it weft's own (plan 0.1, M1).
2. loom deletes `src/loom/refs/crawl/`, the three `refs crawl` commands, the `[crawl]` table and its validation, and the crawl tests; `refs/cache/crawl/` stops being written.
3. `loom digest fetch` stays exactly as it is: one work, named by citekey, gated on `[refs] fetch`.
4. The book loses its crawl sections (chapter 8's crawl material, chapter 4's `[crawl]` keys, chapter 12's generated entries) and gains one paragraph saying that a corpus is another tool's business and naming weft. The decision records that specified the crawl stay in the appendix as history, as retired decisions do, with a new record for the removal; `docs/deviations.md` gains its row.
5. The work-queue items that were about corpora — reference libraries, the shared byte cache, extraction sharing the node model, locator normalisation beyond English — are re-read in this light: some are weft's from now on, and the queue says so rather than carrying them silently.
6. `loom doctor` and the config template stop mentioning crawl settings.

**What loom gains by it:** a smaller promise. No database, no service clients beyond the two lookups, no rate budget to manage across commands, and a tool whose whole surface is about the paper in front of you.

## 6. What is still open

These belong to weft and are listed in its plan; they are named here because each one is a place where the boundary could be pushed on later, and it should be pushed on deliberately:

- extracting results from PDFs, which is the only way the classical literature enters a corpus;
- inferred edges beyond the two cases the papers state, and what an agent is told about their confidence;
- cross-version result identity, where the ACGS-style case (a result dropped between preprint and publication) is the interesting one;
- verification of machine-extracted statements, and whether a human's check can be recorded anywhere but in that human's own quilt;
- whether an agent's access to weft is ever given a seat inside loom's AI layer, which is the first seam change worth wanting.
