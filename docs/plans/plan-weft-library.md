# Plan: weft, the gallery

A standalone mathematical library: a gallery of works, their sources, and the statements extracted from them, built to be navigated by a researcher in a browser and queried by an AI agent. Weft is not a writing tool and knows nothing about any paper you are writing. Its end state is that a person working in a quilt consults an agent, the agent consults weft, and every paper read in the course of that work leaves the library larger.

This document is a draft to be revised against the live code before it is executed. It builds on weft as it exists today (identity normalization, `work.json`, service politeness, LaTeX extraction, the digest contract) and changes several of its commitments deliberately; §2 says which.

Markers: **[decided]** settled in design conversation; **[assumed]** the drafter's default; **[open]** to be resolved by the implementer or by an experiment.

---

## 1. What weft is for

**[decided]** Two purposes, and both must hold or the design is wrong:

1. **A researcher navigates it.** Finding connections between papers and results is faster in the library than by reading. A statement is always one click from the page it was printed on.
2. **An agent queries it.** Finding a reference, a hypothesis, or the lemma three papers down is a few cheap calls rather than a re-read.

**[decided]** **The unit is a gallery.** A gallery is to weft what a quilt is to loom: a directory made by `weft init`, holding its own config and every reference the library has. Commands find it by `--gallery PATH`, else `$WEFT_GALLERY`, else by walking up from the working directory.

**[decided]** A quilt is one project; **a gallery is one library**, not one per project, because the point of extracting a work is never to extract it again. Nothing stops you making two, exactly as nothing stops you making two quilts — but the design assumes one, and §9 is how one gallery serves many projects. The measurement behind this: the two demonstration corpora built on 2026-09-18 turned out to be **91% the same works fetched twice**, and merging them would take the extracted count of the larger from 7 to 35 with no new fetching.

**[decided]** The store is safe to delete, at every granularity: a run, an observer, a work, the whole gallery. Nothing anyone wrote depends on it.

**[decided]** Only anchored, machine-checkable records are stored. Every result carries the verbatim span it came from and the artifact it came from; unverifiable prose is stored nowhere.

## 2. What changes from weft as built

### 2.1 The rule that decides most of this plan

**[decided]** **Anything a machine can derive, a machine derives — eagerly, in full, and again whenever its inputs change.**

A model reading pages is the only expensive operation in weft, and therefore the only one that is rationed, gated, ranked, budgeted or put in front of a person. Everything else is cheap, deterministic and repeatable: parsing LaTeX, compiling a paper for its own numbers, mapping pages and sections, computing levels, counting citations, resolving the identity graph from the ledger, drawing the edges a paper states. None of that is scheduled, none of it is ranked, none of it is done partially, and none of it needs permission. Re-deriving it costs minutes and buys correctness: when a rule changes, everything mechanical is recomputed rather than migrated.

**This is auditable.** Wherever this plan mentions a cost, a cap, a gate, a queue, a budget or a demand report, check what is being rationed. If it is not a model reading pages — or bytes crossing the network, which is rationed out of politeness rather than cost — the rationing is a mistake and should be deleted.

**[decided]** The consequence for the pipeline: **a fetch that lands a source leaves it mapped, extracted, compiled for its numbers, levelled and linked.** A person never has to remember a mechanical step, and no work sits fetched-but-undigested waiting to be chosen. `extract`, `link`, `map` and `index rebuild` remain as commands — to force the work after a rule changes, and to run it over what is already on disk — not as steps in a ritual.

**[decided]** **Backwards compatibility is not a constraint at this stage.** Nothing outside this repository depends on weft's file layout, command names or flags. Renames are done outright, formats change in place, and the demonstration corpora are rebuilt to fit the design rather than the design bent to fit them. This holds until the author says otherwise, and it is why §6's renames carry no deprecation window.

### 2.2 Three revised commitments

**[decided]** Three commitments in the current documentation are deliberately revised:

1. *"Nothing is inferred from a model's reading."* Becomes: a model's reading is stored only as an anchored span a machine can re-check, plus a rendering marked as such. This is what buys coverage of the works with no LaTeX source.
2. *"Nothing writes to a corpus except the pipeline."* Becomes: nothing writes except the pipeline and `weft propose`, which writes only records that pass verification at the moment of writing.
3. *Extraction is a pipeline stage.* Becomes: extraction is both a pipeline stage and a side effect of reading. An agent that reads a work for any reason digests it as it reads.

**[decided]** Unchanged and load-bearing: files are the truth and the index is derived; identifier normalization and the `is_doi` discipline; one work is one record under every identifier; a result key is scoped to a version; service spacing shared across processes; the digest contract as the interchange format.

### 2.3 Two claims this plan corrected against measurement

An earlier draft justified the pivot to agent reading with two claims that weft's own measurements contradict. Both are recorded here rather than quietly dropped, because the build order followed from them.

**"Most works have no LaTeX source" is false for a citation neighbourhood.** ACGS at depth 2: 47 works, 38 arXiv-downloadable (81%), 3 open copies, 6 metadata-only. relloc: 22 entries became 20 works, 15 with arXiv sources (75%). The claim is true of a *bibliography* — loom's reference layer is right to build on it — and false of a neighbourhood seeded from arXiv. PDF reading is therefore **the tail, not the main path**: it is where the classical literature is (a thesis, an EMS article, a *Math. Scand.* paper), and that tail is worth having, but nothing in the build order should assume it is the bulk.

**"Extraction is the scarce resource" is false for the LaTeX path.** 35 papers, 2,347 results, 608 proofs, 34 real latexmk compiles: about five minutes, unattended. Extraction is scarce only when a model does the reading. What is actually scarce is fetching — and the binding constraint measured on 2026-09-18 was a hostname, `arxiv.org` refusing what `export.arxiv.org` serves, not a budget.

## 3. The gallery

**[assumed]** Extending the current layout:

```
gallery/
  weft.toml
  pdfs/<sha256>.pdf            content-addressed; a file exists before anyone knows what it is
  identity/assertions.jsonl    append-only identity claims with evidence
  works/<home>/
    work.json                  as today, plus match evidence and coverage
    <version>/
      src/                     LaTeX where available
      artifacts.json           what we hold for this version, and the pool hash of each
      pages/                   deterministic page text and token boxes
      sections.json            the section map
      results.json             results with anchors and provenance
      observations.jsonl       negative knowledge
      digest.tex               a render, loom-readable
  cache/<service>/<hash>
  crawl/
    plan.json                  the current plan
    hauls/<name>.json          what one named fetch brought in; the unit a query scopes to (§9)
  index.sqlite
```

**[decided]** What `weft.toml` holds, now that a gallery is one library rather than one project's corpus:

```toml
[sources]
contact = ""                  # an address for Crossref's polite pool; a property of the person
[store]
dsn = "sqlite:index.sqlite"
[licence]
share = false                 # the posture, not enforcement: a gallery is private and nothing exports (10.7)
[expand]
subjects = ["14N", "14D"]     # the default frontier filter; a run may override it
categories = ["math.AG"]      # for works with no MSC code
[read]
warn_pages = 40               # the only budget in weft (§2.1): a model reading pages
```

`[seeds]` and `[crawl]` are gone. A gallery has no seeds — it has a history of hauls (§9), each with its own seeds, depth and cap, recorded where it happened. What survives as configuration is what is true of the *library*: who is asking, where the index is, what may be shared, what subjects this library is about, and when to warn about a model's reading.

### 3.1 Identity as a ledger

**[decided]** Matching is the foundation and deserves the strongest model. A gallery holds an append-only ledger of identity assertions, each with evidence:

```json
{"kind": "pdf-is-work", "subject": "sha256:9c1a…", "object": "doi:10.1112/…",
 "signal": "embedded-doi", "confidence": 1.0, "observer": "ingest", "when": "…"}
```

Kinds: `pdf-is-work`, `citekey-is-work`, `same-as`, `tag-is-work`. Resolution computes the current identity graph: union-find over `same-as`, best-supported `pdf-is-work` per PDF. Conflicts are visible as competing assertions, never silently overwritten; a correction is a new assertion, not an edit.

**[decided]** **The ledger is the truth and `work.json`'s `ids` are derived from it**, the same discipline the index already obeys: `weft index rebuild` must be able to reconstruct every binding from the ledger alone. This is what makes a correction cheap and an audit possible. Today the binding is computed at crawl time, written into the record, and its evidence discarded; that is the defect this fixes.

**[decided]** Content-addressed PDFs mean identity can change without a file moving, duplicates across projects collapse, and an unidentified PDF is still a first-class object.

**[decided]** An unidentified PDF is searchable by page text, marked unidentified, and **never linked from anything and never citable**.

**[decided]** Resolution itself is mechanical and is recomputed from the ledger whenever it changes (§2.1). The threshold below gates only which assertions a person is asked to look at; it never gates the computation.

**[open, 10.1]** The auto-accept threshold, as an experiment: run the signals over a real seed, score by hand, choose from the measured error rate. Default until then: two agreeing signals.

### 3.2 Artifacts: what we hold

**[decided]** **A fetch takes the PDF alongside the source.** The crop beside a statement (§6) is what makes the library trustworthy, and it needs a page; of the 36 versions ACGS has fetched today, exactly one has a PDF, because an arXiv work is fetched as source. So both are fetched: the e-print from `export.arxiv.org/e-print/<id>` and the PDF from `export.arxiv.org/pdf/<id>`, under the same host budget.

**[decided]** A PDF lands in `pdfs/<sha256>.pdf` and the version points at it; a source tree stays under the version, because it is a tree rather than a file and nothing dedupes across works. `artifacts.json` records what a version holds and by which hash.

**[decided]** **Nothing in the pipeline waits on a PDF.** Extraction, numbering, levels, edges and the index all derive from the source; the PDF is what a *reader* is shown and what the PDF path anchors into. So fetching both cannot slow extraction down — it is a second artifact fetch, not a second stage — and a work whose PDF has not arrived is fully digested and fully queryable, minus the crop.

arXiv serves `/e-print/` and `/pdf/` separately and the two cannot be combined into one request, so the cost is one extra spaced request per work. Measured over ACGS's neighbourhood on 2026-09-18: **35 PDFs, none refused, 2.9 seconds a request, 0.65 MB each against 0.22 MB for a compressed e-print.** Both artifacts together cost about six seconds and 0.9 MB a work; a thousand-work gallery is under an hour and about 650 MB.

**[decided]** **The PDF is fetched eagerly, with the source.** Three seconds and two thirds of a megabyte is nothing beside the compile that follows, and the alternative is worse than its cost: a crop fetched on first view would make the HTTP API, the MCP server and the view — read-only by construction, and annotated as such — reach out to the network while answering a query.

**[decided]** **A cap counts works, not requests.** A person fetching thinks in papers, and a work costs whatever its artifacts cost; counting requests would silently halve the reach of `--cap 200` the moment a second artifact was added, and halve it again if a third ever were.

**[decided]** **The spacing is arXiv's own: one request every three seconds.** `download.BULK_SPACING` was 15 seconds, chosen on 2026-09-17 to appease a rate limit that turned out to be a wrong hostname (§2.3); 35 PDFs in a row at 3 seconds drew no refusal, so the extra twelve were bought with nothing. The general form is worth keeping in mind whenever this plan sets a number: **a mitigation outlives the diagnosis that justified it unless someone re-measures**, and when a diagnosis is corrected every setting it produced is suspect.

**[decided]** **The compiled PDF is discarded, and named as a fallback.** `weft extract --compile` already produces one for 34 of 35 papers and deletes it. It is not the artifact to anchor into — page breaks differ from the published PDF, and a locator naming "p. 9" means the page its author saw — but where a source exists and no PDF can be fetched, keeping it costs one copy.

### 3.3 Results, and what an anchor anchors to

**[decided]** As in the reference-layer plan: two texts per result (`source_text` verbatim and byte-checkable; `statement` a rendering), an anchor, a level, provenance naming the method and observer, and a verification record.

**[decided]** **An anchor names the artifact we hold**, never one we do not. Anything else cannot be displayed: the crop, the page number and the locator text all come from the bytes in the gallery. For a PDF-derived result the anchor is `{sha256, page, quad}`; for a LaTeX-derived one, `{path, sha256, bytes}`.

**[decided]** **Three epistemic classes, not two**, because a rendering produced by a parser and a rendering produced by a model are not the same claim:

| class | how it was made | what a surface must say |
|---|---|---|
| `mechanical` | parsed from LaTeX; `statement` is the source, macro-expanded | verbatim, checkable against `src/` |
| `anchored` | read from a page; `source_text` re-checkable at the anchor | the span is verified, the rendering is not |
| `declared` | a rendering with no check available | asserted, and shown as asserted |

**[decided]** **A locator that names another artifact's numbering is its own case.** The gallery usually holds the preprint while a citing author cites the published article: of the ten locator misses left in ACGS after the neighbourhood was closed, **nine are exactly this** — `Definition 1.17` of the JAMS version against arXiv's 1.16, `Thm. 1.1.2` of the Compositio version against a preprint numbered by section. This is digest contract §8.1 arriving in the data. The linker reports it as `other-artifact` rather than as "matched nothing", a work records which of its versions a locator was resolved against, and the view says so beside the citation. Matching harder cannot fix it; holding the published artifact can.

**[decided]** `numbering` (`compiled` or `emulated`) and `method` (`latex`, `pdf-agent`) stay per version, as today.

### 3.4 Proofs

**[decided]** **Kept by default, not served by default, served on request.** Extraction keeps each proof verbatim as it does today — it is where every internal edge comes from, and a library that cannot show why a theorem is true cannot answer whether an argument transfers (digest contract §2.6). Every query surface omits proofs unless asked: `--proofs` on the CLI, `proofs=1` over HTTP, a `proofs` argument on the MCP tools. `weft digest --level` stays statements-only unless the flag is given.

## 4. Levels, and what they gate

**[decided]** Four levels, none of them a stored artifact beyond a flag:

- **Level 1**: main results, detected mechanically (abstract and introduction mentions, in-degree in the internal graph, "Main" labels), stored as a flag with its reason and recomputable. For a work with a source this is computed and never read for: the document is already parsed, so level 1 costs nothing and is always current.
- **Level 2**: the depth-1 closure of level 1. Nothing between 2 and 3.
- **Level 3**: all results.
- **Level 4**: the source.

**[decided]** **Levels gate agent reading and nothing else.** Level 1 is required before an agent reads a work more deeply, because pages read by a model are the scarce resource. **LaTeX extraction stays whole-work and eager**: parsing the document is how level 1 is found in the first place, so extracting only part of it costs more than extracting all of it, and partial extraction suppresses exactly the edges the library exists to show (§5).

**[decided]** Level 2 is meaningful only where internal edges exist: `\ref` for LaTeX works, proof-text references ("by Lemma 2.3") resolved against the work's own numbering for PDF works. Where neither exists the query says the graph is empty rather than degrading silently.

## 5. Demand, and what it is not

**[decided]** Fetching the seed is cheap and needs no ranking. Two things are limited, for different reasons: **bytes crossing the network**, which is spaced out of politeness to services rather than because it is expensive, and **pages read by a model**, which is the only genuinely costly operation in weft. LaTeX extraction is neither (§2.3), and by §2.1 it is never rationed.

**[decided]** **Three tiers, and the filter governs only the third.** What a work costs depends on how much of it you want, and by §2.1 only the network and a model's attention are rationed at all:

| tier | what it is | cost | governed by |
|---|---|---|---|
| **record** | a `work.json` for everything anything in the gallery cites, from the citing paper's own bibliography and from the resolved reference lists already downloaded | free | nothing; it is always done |
| **identify** | a lookup at a service for a reference nothing already resolved | one spaced request | the run's cap, ordered by `rank` |
| **fetch and expand** | download the source and the PDF, digest it, make it a frontier of its own | requests, disk, a compile | `[expand] subjects` and `categories`, and the run's cap |

The change from weft as built is that **subjects and categories no longer decide what is kept**, only what is expanded. Filtering inside a neighbourhood is what makes the holes that stop edges being drawn, and it is what silently dropped four ACGS works for having no classification — two of them plainly in the seed's own subject. Under this rule an unclassified work cited by something we hold gets a record and is visible as cited; it simply does not become a new frontier. The cost is that `works/` becomes mostly stubs: 35 extracted works carry about 1,260 references, so a closed neighbourhood implies roughly a thousand records, each a small JSON file.

**[decided]** **The cap is per run, and nothing is capped for life.** A gallery accumulates; a lifetime download limit on it means nothing. `weft fetch --cap n` limits one fetch, `weft status` reports the gallery's size — works, versions, sources, PDFs, bytes — and no standing limit ever stops a command.

**[decided]** **The unit that pays is a closed neighbourhood, not a ranked prefix.** A cross-paper edge needs *both* ends extracted: relloc, with 7 of 301 works extracted, draws none; ACGS, with its seed's neighbourhood closed, drew the first eight. Extracting the top *n* works by demand reproduces relloc's shape — popular works whose citations point at neighbours nobody extracted. So `weft rank` chooses **which neighbourhood to close next**, and the closing is exhaustive within it.

**[decided]** Demand is a report, never a scheduler and never stored as authority. `weft rank` computes two things and only two, because by §2.1 nothing else is scarce: **which neighbourhood to close next**, from citation counts among gallery works weighted higher when the citation sits inside a proof; and **which pages deserve a model's attention**, from locators pointing into them and from sections a search has failed in. You read the report and decide.

**[decided]** What `rank` does *not* report, because it is done automatically: **a version with a source is compiled for its own numbers.** An earlier draft ranked "versions whose numbering would improve if compiled"; compiling is a minute of CPU and it decides whether a locator resolves at all, so it is simply done, and a paper that fails to build costs its numbering rather than its extraction.

**[decided]** No background daemon. `weft fetch --top n` when you want it.

**[decided]** The proposal queue for new works: an agent proposes with a checkable reason and an identifier. Auto-rejected when the identifier does not resolve at a service, or when the stated reason references a result the gallery does not hold. Survivors appear in `weft propose review`; only a person promotes one into the fetch queue. A hallucinated paper never reaches review.

## 6. Surfaces

**[decided]** All read-only except `propose`.

**CLI** — the agent-facing set, every command JSON, every list capped with explicit truncation:

| command | purpose |
|---|---|
| `weft find` | statements by text or hypothesis; `--mode exact\|fuzzy\|vector`; `--work` or `--from <haul>` to scope; candidates, never conclusions |
| `weft grep` | raw page text; `--from <haul>` to scope; the cold-start and gap-filling path |
| `weft statement <key>` | both texts, anchor, provenance, verification; `--proofs` to include the proof |
| `weft main <work>` | level 1 |
| `weft digest <work> --level 1\|2\|3` | statements, capped; `--proofs` to include them |
| `weft supports <key> [--depth 1]` | what a result rests on |
| `weft dependents <key>` | the reverse |
| `weft near <key…>` | personalised PageRank from a seed set over internal edges |
| `weft page <version> <n>` | page text and crop; the sanctioned read and the self-check |
| `weft locate <version> <text> --page n` | the quad for a span |
| `weft coverage <work>` | digested by section; searched-and-not-found |
| `weft why <key>` | provenance and verification |
| `weft cite <key>` | BibTeX plus the exact locator string, and which artifact's numbering it names |
| `weft propose result\|edge\|work` | the only write; verifies or rejects with the page text |
| `weft rank` | the demand report |
| `weft drop --run\|--observer\|--unverified\|--work` | deletion |
| `weft hauls` | the named fetches this gallery has made, and what each brought in |

**Operator commands.** What exists today, under today's names: `init`, `crawl plan|fetch|status`, `survey`, `extract`, `link`, `index rebuild|counts`, `search`, `get`, `closure`, `dependents`, `work`, `versions`, `bib`, `serve`, `mcp`. New in this plan: `ingest` (a pile of PDFs into the pool), `identity review|set|explain`, `map` (pages and sections), `hauls`, and the agent-facing set above.

Once `[crawl]` has left the config (§3), the `crawl` group has nothing left to group, so the operator tree is flat: `init`, `ingest`, `identity`, `plan`, `fetch --as <haul> --cap n --depth n`, `status`, `map`, `extract`, `link`, `index rebuild|counts`, `hauls`, `survey`, `serve`, `mcp`. `weft status` reports the gallery — works, versions, sources, PDFs, bytes, coverage — and is the only place a size is ever shown, because no size ever stops a command.

**[decided]** The renames, done outright (§2): `search`→`find`, `get`→`statement`, `closure`→`supports`, `bib`→`cite`, `--corpus`→`--gallery`, and `--collection`→`--from <haul>`. The HTTP API, the MCP tools and the view are updated with them; no aliases, no deprecation window.

**HTTP** — as today, extended with `/page`, `/coverage`, `/near`, `/hauls`, a `from=` parameter on the global queries, and a crop endpoint returning the anchored region as an image.

**[open, 10.12]** **MCP is not a mirror.** Mapping seventeen commands to seventeen tools makes a menu, and a model picks worse from a menu than from the eight orthogonal tools it has today. Drafter's default: keep the MCP surface small — `find`, `statement`, `supports`, `dependents`, `coverage`, `page`, `cite`, `propose` — with everything else reachable as arguments rather than as tools.

**The view** — the researcher's surface, and the place where anchors pay off:

- Search, with coverage stated in every result set.
- A work page: versions, coverage by section, identity evidence, what it cites and what cites it.
- A result page: the rendered statement beside **the PDF crop it was read from**, what uses it, what it rests on, provenance and verification state, the citation string, and which artifact the numbering belongs to.
- A level switch (1/2/3) on any work, and proofs behind a toggle.
- `near` rendered as a small graph; shortest path between two results.
- An identity review screen: the one place a person is genuinely needed.

**[decided]** The crop beside the statement is the single feature that makes the library trustworthy to a human. Anything that makes it hard should be reconsidered rather than worked around — which is why the PDF is now fetched alongside the source (§3.2).

## 7. Build order

**[assumed]**

1. **Identity.** PDF pool, assertions ledger, resolver, signals, `identity review|set|explain`, `bib export`, and `work.json`'s identifiers derived from the ledger. Done when a 50-PDF seed plus a bib file produces a match table and a short review list; when deleting every `work.json` and rebuilding reproduces the same bindings; and when **the two demonstration corpora merge into one gallery**, whose 44 duplicate pairs collapse to one record each and whose extracted count is 35 rather than 7 (§1).
2. **Artifacts.** PDFs fetched alongside sources for what the gallery already holds, `artifacts.json`, the pool. Nothing downstream blocks on them. Done when every fetched version has a page to crop, and when deleting the pool leaves every query still answering.
3. **Map and read.** `map`, `pages/`, `sections.json`, `page`, `locate`, `grep`, `coverage`. Done when the gallery is searchable and readable before anything is digested.
4. **Propose and verify.** `propose result`, anchor verification, rejection with page text, the level-1 gate on agent reading, `statement`, `why`, `drop`. Done when reading leaves a digest behind.
5. **Query.** `find` with modes, `main`, `digest --level`, `supports`, `dependents`, `cite`, coverage in every result set, proofs behind a flag. Done when the worked example of the reference-layer plan runs against weft.
6. **Surfaces.** HTTP additions, the small MCP surface, the view with crops and the level switch. Done when a researcher can navigate the gallery without the CLI.
7. **Crawl and demand.** `rank`, `propose work`, `fetch --top n --as <haul>`, per-run caps, `survey`, neighbourhood closing as the unit. Done when the gallery grows past the seed under your control and every query can be scoped to a haul.
8. **Later.** `near`; vector search in `find`; tag-addressed adapters (the Stacks project); cross-gallery merge; syncing with a quilt's reference layer.

## 8. Relationship to a quilt

**[decided]** Weft never reads or writes a quilt. The seam is `weft bib <identifier>`, which hands over a BibTeX entry with every identifier the gallery holds, and the digest contract, which both tools can write and read.

**[decided]** A quilt may have its own small reference layer, built before weft is ready, serving the same purpose within one paper. The eventual relationship is sync or replacement, decided when both exist: the library is standalone precisely so that extraction is not repeated per project.

**[open, 10.6]** What "sync" means concretely: importing a quilt's digested results into the gallery, exporting gallery results into a quilt, or both. This should not be designed until the quilt-local layer has been used for a while.

**[open, 10.13]** The arras projection, which plan 0.1 §9 promised and this plan drops. Established 2026-09-18: arras needs no modification to render a gallery projection — the interface is publisher-neutral by decision, `docs/specs/fixture-minimal/` holds the floor, and weft would become a second publisher of interface v1. The cost is a fragment renderer (loom's `render/convert.py`, `fallback.py` and `fragments.py`, about 1,900 lines, vendored as the crawl was). Keep it or kill it deliberately; it is not blocked on anything.

## 9. Hauls

**[decided]** **A haul is what one named fetch brought in.** `weft fetch --seed arxiv:1709.09864 --as acgs` names the fetch; `crawl/hauls/acgs.json` records its seeds, its settings and every work it reached; `weft find "projection formula" --from acgs` scopes a query to those works. `weft hauls` lists them.

**[decided]** **A haul is derived, never maintained.** It is a fact about what happened, so nobody adds to it, nobody prunes it, and it cannot silently rot the way a hand-kept list does — the same discipline as §2.1. A work reached by two hauls is in both; a haul whose works were later deleted names fewer works and says so.

**[decided]** A haul is a **view, never a container**. Works live once, under `works/`, and a haul narrows a query rather than owning anything. Coverage, demand and identity are gallery-wide.

**[decided]** This is what makes one gallery serve many projects without per-project libraries: "the works I pulled in while writing the relloc paper" is a haul, and it costs one file written by a command that already runs.

**[open, 10.15]** Scoping by a stored *predicate* rather than by a past fetch — subject, reachability from a seed, year, has-source — which is the natural extension once something demands it. Not built until it is demanded; hauls cover the case we have. The same applies to a hand-listed set chosen by taste: it can be added later as sugar over the same `--from` mechanism, and until then it is not built.

## 10. Open questions

**[open, 10.1] The matching auto-accept threshold.** An experiment over a real seed; the threshold follows from measured precision and recall per signal and combination. Two agreeing signals until then.

**[open, 10.2] Ids for PDF-derived results.** The digest contract §3.2 already answers unnumbered results — `<prefix>-<abbrev>-star-<n>`, counting in document order. What it does not answer is per-chapter numbering and books: chapter-qualified local, or content hash.

**[open, 10.3] Whether unidentified PDFs should be searchable.** Decided yes in conversation (findable, never citable, never linked). Worth revisiting once there are enough of them to judge whether the distinction stays clear in the view.

**[open, 10.4] The model-reading budget**, which is the only budget in weft (§2.1): warning and confirmation above n pages read, with cost reported per read. Everything mechanical is uncapped.

**[open, 10.5] Hypothesis splitting.** The sharpest search mode and the most error-prone extraction. Possibly deferred, with `--mode hypothesis` falling back to whole-statement scoring.

**[open, 10.6] Sync with a quilt's reference layer.** Not to be designed before both exist.

**[resolved, was 10.7] Licensing.** Deferred in full, with the assumption written down: **a gallery is private, on one researcher's own machine, read by that researcher and their agent, and never shared.** Under that posture licences do not arise — this is the fetching and reading a person already does, and the gallery is a filing cabinet for it. So no licence is recorded, no licence gates anything, and `[licence] share = false` stays in the config as the *statement* of the posture rather than as enforcement.

The invariant that keeps this honest: **no export or sharing path is built while `share` is false** (§11). The day a gallery is meant to leave the machine, this question comes back, and it comes back before the feature does — at which point §3.3's anchors are already the answer to most of it, because `{sha256, page, quad}` names a passage without reproducing it, and the graph weft exists to build is facts rather than expression.

**[open, 10.8] Vector search.** In `find` as a third mode, as a candidate generator only. Worth building once exact and fuzzy have been shown insufficient on a real gallery, not before.

**[resolved, was 10.9] What `weft.toml` holds.** Decided in §3: `[sources]`, `[store]`, `[licence]`, `[expand]` and `[read]`; `[seeds]` and `[crawl]` are gone, because a gallery has a history of hauls rather than seeds.

**[resolved, was 10.10] Cap accounting and fetch timing.** Decided in §3.2 from measurement: the PDF is fetched eagerly with the source, and a cap counts works rather than requests.

**[resolved, was 10.11] The renames.** Backwards compatibility is not a constraint at this stage (§2), so they are done outright, with no aliases and no deprecation window.

**[open, 10.12] The size of the MCP surface** (§6).

**[open, 10.13] The arras projection**: keep or kill (§8).

**[resolved, was 10.14] The bulk spacing.** Measured: 35 PDFs at 3.0 seconds, no refusal, 2.9 seconds a request. `BULK_SPACING` is 3.0, and fetching is five times faster than the day began.

**[open, 10.16] weft's HTTP client refuses to be served by arXiv.** Measured 2026-09-18 against `oaipmh.arxiv.org/oai`, one URL, one User-Agent, one minute: `urllib` — which is weft's transport everywhere — gets **406**, while `curl` and `httpx` over HTTP/1.1 both get **200**. So the e-print refusals of 2026-09-17 were not fixed by moving to `export.arxiv.org`; they were routed around, and the download paths of that host happen not to apply whatever rule this is. The discriminator is unidentified and is not the User-Agent, the `Accept` headers, the encoding or the HTTP version, all of which were tested. What this costs: arXiv's OAI-PMH interface is unreachable, and that is where a paper's licence, its version history and its dates live — the last of which is an open item from M1, since an arXiv id without a version names "the latest" and weft records the id it was given. The remedy is a different HTTP client, which is a small change to `crawl/net.py` and `crawl/download.py` and would remove the class rather than the instance.

**[open, 10.15] Scoping by a stored predicate** rather than by a past haul, and a hand-listed set chosen by taste (§9). Neither is built until something demands it.

## 11. What this plan does not build

Stored relevance scores; global PageRank; digests of digests; agent-authored prose summaries; auto-accepted single-signal matches; a background fetcher; a level-2 claim for a work whose internal graph does not exist; partial LaTeX extraction; **a ranking, a budget, a queue or a person's confirmation for anything a machine can derive** (§2.1); **any path by which a gallery leaves the machine it was built on** — no export, no publishing, no hosted view, no gallery handed to a collaborator, while `[licence] share` is false (10.7); any store whose deletion would cost a paper anything.

A local artifact is not sharing. An arras projection (10.13) rendered and read on the same machine is the researcher reading their own library in a nicer window, and it stays in scope.
