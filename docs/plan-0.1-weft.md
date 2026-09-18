# weft 0.1 — a machine-readable library of mathematical results

## 1. What weft is

weft crawls a citation network to arbitrary depth, extracts each paper's results — definitions, statements, lemmas, theorems, remarks **and proofs** — into digests that obey loom's source contract, links those results to each other where the papers say so, and serves the whole thing to a reader and to an AI agent.

The product is the library and its query surface. An agent crawling that library to advise a mathematician on a project in progress is the use it is designed for; a human navigating it to look for connections and ideas is the other.

weft is not a way to get material into a paper. When you find a work you want to use, you add it to your own bibliography and your paper's tool (loom) fetches, extracts and digests it at depth 1 under your own citekey. The boundary is documented in [weft-and-loom.md](weft-and-loom.md).

Named for the crosswise threads drawn through the warp: the papers are the warp, the links between their results are the weft.

## 2. Scope of 0.1

**In:**
- the crawl: identify, walk to depth, filter by subject, cap, plan, fetch, resume;
- extraction of statements and proofs from LaTeX sources, per version of a work;
- the two kinds of cross-paper edge the papers state explicitly (§7);
- a corpus store and an index that can be rebuilt from it;
- a query surface: JSON from the CLI, a local HTTP API, and an MCP server over the same queries;
- a navigation view, in Svelte;
- two seed corpora and the measurements they produce.

**Out, by decision:**
- anything that writes into a quilt: no pull, no import, no materialising a digest into someone's paper;
- reading a quilt: weft has no knowledge of quilts. An agent that wants both reads the quilt itself and queries weft;
- extracting results from a PDF: works with no source are metadata-only nodes in the citation graph, absent from the result graph. §11 keeps the seam for it;
- inferring an edge the papers do not state (§7 covers the two stated cases and no others);
- contributing anything back to a paper's quilt, in either direction.

## 3. The data model

**Work → version → result.** A work is a scholarly item: one paper, one book. A version is an artifact of it: `arxiv:1709.09864v1`, `arxiv:1709.09864v3`, `doi:10.1090/jams/1234`. Results belong to a **version**, not to a work, because numbering is a property of the artifact and because versions differ in content: Kresch's published thesis drops a result his arXiv version states. "The same result in two versions" is a mapping with provenance and a confidence, never an identity.

```
work            ids[], title, authors, year, msc[], arxiv_category, licence, depth, reached_from[], reached_by
version         work, id (scheme:value with version), source?, pdf?, extracted_at, method, numbering
result          version, local ("thm-4.1"), taxon, number, title, statement (LaTeX), proof (LaTeX)?, aliases[], page?
edge            from result, to result | to work, kind (uses | cites), origin (§7), confidence, evidence
reference       version → work, locator text, citekey as printed, identified_by
same_as         result ↔ result across versions, confidence, evidence
```

A result's key is URI-shaped, work and version and paper-local part: **`arxiv:1709.09864v3#thm-4.1`**. Global, readable, stable under quoting in a chat log, and free of any slug policy. Digest files keep loom's id grammar internally so that a projection (§9) can be read by a presenter that expects it; the corpus's own keys are the URIs.

## 4. Storage

**Files are truth; the index is derived and disposable.**

```
corpus/
  weft.toml                         crawl settings, sources, licence posture, index dsn
  works/arxiv/1709.09864/
      work.json                     the work record: identifiers, metadata, references, provenance
      v3/src/                        unpacked source
      v3/paper.pdf
      v3/digest.tex                  statements and proofs, loom's source contract
      v3/results.json               extraction output: results, offsets, numbering, method
  cache/<service>/                  raw service answers, negative caching
  exports/                          projections (§9)
  index.sqlite                      or a Postgres dsn
```

Bytes may live on an external disk, a NAS or a server; the index may live elsewhere again. Nothing in the domain model may mention SQL: one repository interface, two implementations (SQLite to start, Postgres when the corpus outgrows it), and `weft index rebuild` reconstructs everything from `works/`.

## 5. Identification

Ported measurement, from loom's parse-rate study over two real papers: **100% of bibliographies parseable, 9% of 103 entries carrying a usable identifier**, and neither paper shipped a `.bbl` or a `.bib` — both inlined `\begin{thebibliography}` into a `.tex` file. A formatted `\bibitem` is display text, and mathematics styles rarely print a DOI.

Consequences, all of them already true in loom's code and to be ported:
- **the unit is `\bibitem` wherever it occurs**, not a file extension;
- identification is a lookup by title, surnames and year (zbMATH Open, then Crossref, with loom's scoring: 0.75 title ratio + 0.15 first surname + 0.10 year within one), and a free-text branch for `\bibitem` strings;
- a work that states no identifier gets a deterministic synthetic key, `work:<sha256[:8]>` over folded surnames, title and year, so two corpora can merge later;
- **every identifier of a work is indexed and records are merged.** Keying on the first identifier seen made one work two records mid-walk (EGA I, twice), because sources add identifiers as the walk proceeds;
- an arXiv DOI (`10.48550/arxiv.X`) is normalised to `arxiv:X`: one artifact, one directory.

Measured yield on loom's relloc corpus: 3 cited works unresolved of 22 entries (23%); lookup found DOIs for two of the three and correctly declined the Stacks project.

Unlike loom, weft **binds** a strong match as the work's identity, recording provenance (`declared`, `resolved`, `asserted`) and the evidence. loom refuses to bind because a wrong binding would edit an author's bibliography; weft owns its corpus, and a walk cannot proceed on candidates alone.

## 6. The crawl

Ported from loom's `refs/crawl/` (to be factored out of loom, see the companion document), keeping its shape:

- **`weft crawl plan`** — metadata only. Identify the seeds, enrich from zbMATH and OpenAlex, read references from those services and from `\bibitem`s in any source on disk, identify each reference, filter, order by depth then in-degree, apply the cap, estimate bytes and time, write `plan.json` and a record per work. A plan carries a **fingerprint** of the settings plus the seed texts; a fetch refuses a plan that no longer matches.
- **`weft crawl fetch`** — download the plan's selection, resumable, writing each record as it goes, counting what is already on disk against the cap first.
- **`weft crawl status`** — downloaded, failed, under the cap, beyond it, metadata-only, outside the plan.
- **`weft survey`** — with depth > 1 and no subjects, count what the next level cites by MSC family, by any code, and by arXiv category, and say what to configure. No plan, no records.

**Filtering is configured, never inferred.** Two measurements say so. A default of "the families of the seeds' primary MSC codes" excluded `14L` (algebraic groups), the primary family of 20 of the works the seeds cite and a code of 45. A table mapping MSC families to arXiv categories, measured on 1,675 arXiv records, held the category authors chose for 93% of algebraic-geometry papers, 75% of PDE and 38% of ODE; it was removed.

**Politeness is code, not prose.** Per-service spacing (arXiv 3 s and 50 ids a batch, zbMATH 1 s, Crossref 1 s, OpenAlex 0.2 s), a User-Agent naming weft and its version, raw answers cached with 404s cached as absences, unpacking that refuses symlinks and paths escaping the directory, an OpenAlex key read only from the environment and sent as a header so it never names a cache file, and a cap counted in downloads on disk.

**One rate budget per host, across everything weft does, and across processes.** The last request to a host is recorded under `$WEFT_STATE_DIR` (else `~/.cache/weft/hosts/`), so a second weft process cannot double the rate a service sees. This is the lesson of loom's worst incident: a harvest of arXiv's OAI-PMH interface run *while a fetch was in progress* made arXiv answer 406 to every request from loom's HTTP client for about fifty minutes, while curl from the same machine was still served. arXiv throttles a client, not a command. loom's fix was local (three consecutive refusals stop a fetch; the harvest spaces pages ten seconds apart); weft's must be structural: every request for a host passes one budget, whatever command asked.

Licences of the metadata, to be recorded and honoured on export: zbMATH Open CC-BY-SA 4.0, OpenAlex CC0, Crossref open.

## 7. Cross-paper edges: the two stated cases, and no others

Only what a paper states explicitly:

1. **A citation with a locator.** `\cite[Theorem 9.4]{bib-key}` inside a result or its proof. The locator is resolved against the cited version's results by loom's normalising matcher (ported): lowercase, a 60-entry abbreviation table, `§` → section, Roman numerals folded after a taxon word, pages and part selectors and filler words dropped; a result answers to its normalised locator, each part of it, and `<taxon> <number>` read off its local part and off every alias. Result → result, kind `uses`, origin `locator`.
2. **A citation with no locator.** `\cite{bib-key}` inside a result or its proof: the result uses something of that work but does not say what. Result → **work**, kind `cites`, origin `unspecified`. It is not promoted to a result edge by guessing.

Everything else is deliberately absent. No inference from text similarity, from shared notation, or from a model's reading; those are the research question of §11 and they stay out of 0.1. An edge carries its evidence (the citing file, offset and the locator as printed) so a reader or an agent can check it.

Two known hazards to measure rather than assume: a locator that resolves against the wrong version's numbering (hence per-version results), and the abbreviation table's English-only vocabulary.

**An ambiguous match records no edge and is logged.** A locator that answers several results, or a multi-part postnote where some parts resolve and others do not, goes to [multi-match-record.md](multi-match-record.md) with its evidence. Whether such a case should become an edge with a confidence, no edge, or a best guess marked uncertain is a decision to take once that file shows what these cases actually are; a problem seen once is not a problem understood.

## 8. The query surface

One set of queries, three deliveries: JSON on stdout from the CLI, a local HTTP API, and an MCP server wrapping the same calls so an agent gets tools rather than a shell.

- `search` — free text, title, author, MSC, taxon, with filters on method and confidence.
- `get` — a result by key, with statement, proof, taxon, number, aliases, version, provenance.
- `closure` — everything a result depends on, transitively, through `uses` edges, with a depth cap and the unresolved `cites` edges listed rather than hidden.
- `dependents` — what uses a result.
- `neighbourhood` — the citation graph around a work, for navigation.
- `versions` — the versions of a work, and the `same_as` mapping between their results.
- `bib` — a BibTeX entry for a work, with every identifier it has. **This is the handoff to a paper's own tool.**

Every payload carries provenance: extraction method, whether the statement is verbatim, and for an edge its origin and confidence. An agent that cannot tell a verbatim statement from a reconstructed one will assert someone's theorem with unearned certainty, so the labels are part of the contract, not decoration.

## 9. The view, and artifacts

- **weft's own view** — Svelte, sharing arras's stack so code can move between them: search, a work page with its versions, a result page with statement, proof, what it uses and what uses it, and a graph for navigation. It reads the HTTP API; the corpus is queried, never published whole.
- **Artifacts** — a filtered projection (a subject, a seed result and its closure) is exported for **arras**, which is becoming a general presenter for text-based interlinked webs of results. A projection is a snapshot with the query that produced it recorded; the interface it targets is arras's, and it follows arras wherever that interface goes.

## 10. Licence posture

A corpus is **private by default**. Statements and proofs are verbatim, which is the point of a library and the thing that makes sharing a decision: each digest records the work's licence and what the digest contains, so an export can say what it is carrying. weft records policy and provenance; it does not enforce law, and this is not legal advice.

## 11. Research and deferred components

- **PDF → results.** The classical literature every paper cites has no LaTeX source, so a corpus built from sources alone systematically under-represents it. A **source adapter** interface (source → results with a method and a confidence) is defined in 0.1 with one implementation, LaTeX; a model-based implementation is its own project. Existing tools to evaluate rather than assume: Nougat, marker, Docling, GROBID for structure, Mathpix commercially. None targets theorem and proof structure.
- **Inferred edges.** Beyond the two stated cases: a threshold, what is shown below it, and whether a probable edge is offered to an agent at all. A false dependency is worse than a missing one when something reasons over it. Unresolved, and out of 0.1.
- **Cross-version result identity** beyond exact-match heuristics.
- **Verification.** Nothing checks a digest against its paper. At corpus scale this wants sampling, a per-statement verified flag, and a way for a reader's check to be recorded.

## 12. Milestones

**M1 — the store and the crawl.** `weft.toml`, the work/version/result model, the repository interface with SQLite behind it, the ported crawl with one rate budget per host, `plan`/`fetch`/`status`/`survey`. Done when a depth-2 plan over the first seed is hand-checked and a capped fetch runs, resumes after an interrupt, and re-plans without re-downloading.

**M2 — extraction.** LaTeX source adapter: statements and proofs per version, numbering from the paper's own compile with counter emulation as the fallback, macro residue handled, `results.json` and a `digest.tex` per version. Done when the seeds' arXiv-sourced works are extracted and a hand-check of one paper's results against the PDF finds no missing or misattributed statement.

**M3 — edges and the index.** Intra-paper `uses` from each proof's own references, the two cross-paper cases of §7, the index and `index rebuild`, and the query set of §8 over the CLI. Done when the measurements of §13 are in hand.

**M4 — surfaces.** The HTTP API, the MCP server, and the Svelte view. Done when an agent, given only the MCP tools, can answer "what does this theorem depend on, and where is each dependency stated" for a result in the corpus.

**M5 — artifacts.** A projection exported for arras, with its query recorded.

## 13. Seeds and the measurements they must produce

Two corpora, because one is a demonstration and two are a comparison:

1. **ACGS**, [arXiv:1709.09864](https://arxiv.org/abs/1709.09864), crawled to depth 2.
2. **The relative-localization paper's bibliography**, at depth 2, which loom has already fetched and measured.

For each: identification rate at depth 1 and depth 2; how many works have a source; results extracted per paper; how many `\cite[locator]` references resolve to a result, how many fail, and **the false-match rate in a hand-checked sample**; how many `\cite{key}` edges stay at work level; bytes and wall-clock for the fetch.

That last number decides whether the cross-paper graph is a product or a research project, and it is the reason M3 ends in measurement rather than in a feature.

## 14. Stack and conventions

Python for the crawl, extraction and API; Svelte for the view; SQLite then Postgres. Ruff and mypy strict, pytest with markers for anything that touches the network, and **no test touches the network by default**: service clients take a transport, and recorded answers stand in. Prose in this repository is never hard-wrapped. The corpus format is documented as a spec before a second tool reads it.

## 15. First actions

1. Repository skeleton, `weft.toml` schema, the work/version/result model and the repository interface.
2. Port `refs/crawl/*`, `refs/identity.py`, `scan/bib.py`, `scan/postnote.py` and `digest/extract.py` from loom, then refactor freely: proofs kept, per-version output, no `ScanResult` rescan model. The contract those files implement is written down first, as §16 of the companion document requires.
3. M1 against the ACGS seed.
