# weft, as built

What is here today, described as it is rather than as it was planned. Three documents divide the work between them: [plan-0.1-weft.md](plan-0.1-weft.md) states the intent and the milestones, the files under [records/](records/) state what was measured and what was found, and this one is the reference — the corpus on disk, the pipeline over it, the surfaces onto it, and the contracts it obeys. [cli-reference.md](cli-reference.md) is generated from the command tree and never disagrees with `--help`; [specs/digest.md](specs/digest.md) is the only normative document in the repository.

Where this file and the code disagree, the code is right and this file is a bug.

## 1. The corpus on disk

A corpus is a directory with a `weft.toml` at its root. Every command finds it by walking up from the working directory, or takes `--corpus PATH`.

```
corpus/
  weft.toml            the settings; the only file a person edits
  works/               one directory per work — the truth
    arxiv/1709.09864/
      work.json        the record: what the work is, and everything anything said about it
      main/            a version's artifacts (see 1.3)
        src/           the LaTeX source as arXiv served it
        digest.tex     the statements as a loom-readable digest
        results.json   the same statements as data, plus the edges drawn from them
    doi/10.1112_s0010437x20007393/
  cache/<service>/<hash>    verbatim service answers, so a second plan asks nothing
  crawl/plan.json           the last plan: what a fetch would do, and why each work was kept or dropped
  index.sqlite              the index, derived from works/ and rebuildable from it
```

**Files are the truth and the index is derived.** `weft index rebuild` clears the index and replays every record under `works/`; nothing is ever only in the database. A corpus survives its index being deleted, and two corpora merge by merging directories.

### 1.1 `weft.toml`

```toml
[seeds]
works = []                  # global identifiers, e.g. "arxiv:1709.09864"
bib = []                    # BibTeX files, relative to this file, whose entries are seeds

[crawl]
depth = 2                   # the seeds are depth 1; a work at `depth` is included and not expanded
subjects = []               # MSC families, e.g. ["14N", "14D"]; required when depth > 1
categories = []             # arXiv categories, e.g. ["math.AG"]; used where a work has no MSC code
cap = 200                   # downloads on disk, counted across every command
[sources]
contact = ""                # an address sent to Crossref's polite pool; nothing identifying is sent when empty
[store]
dsn = "sqlite:index.sqlite" # the index; a Postgres dsn when the corpus outgrows a file
[licence]
share = false               # a corpus is private by default: statements and proofs are verbatim
```

`subjects` is required past depth 1 and weft never guesses it: `weft survey` counts what the seeds cite, by MSC family and by arXiv category, and a person chooses. A work with neither an MSC code nor an arXiv category passes no filter and is dropped — recorded as a finding, not as a feature.

`WEFT_OPENALEX_KEY` is read from the environment only, so a key is never written into a corpus or into a cache file's name.

### 1.2 `work.json`

One record per work, under twenty-one keys, and `record: 1` versions the shape. The keys are the corpus's contract with everything that reads it, which is why `payload()` lists them explicitly rather than dumping a dataclass.

| group | keys |
|---|---|
| identity | `record`, `key`, `ids`, `home`, `provenance` |
| description | `title`, `authors`, `year`, `msc`, `arxiv_category`, `licence` |
| how the crawl got here | `depth`, `reached_from`, `reached_by`, `citekeys` |
| its bibliography | `references_known`, `references` |
| its artifacts | `versions`, `arxiv_version`, `download`, `open_pdf` |

`key` is the first of `ids` in resolution order (§2). A reference carries `work`, `citekey`, `text` and `identified_by`; a reference weft could not identify keeps its printed text and an empty `work`, because the text is evidence and an empty string is not a claim.

### 1.3 The version directory

`works/<home>/<version-local>/`, where the version-local part is **what the identifier adds to the home**: `arxiv:1709.09864` under `arxiv/1709.09864` is `main`, its second version is `v2`, and an artifact of another scheme keeps its own name (`arxiv-1901.00001`). This is what lets a source fetched from arXiv sit under a work homed by its journal DOI without repeating the identifier in the path.

### 1.4 `results.json`

```json
{"version": "arxiv:2401.00001v1", "method": "latex", "numbering": "emulated",
 "results": [{"local": "thm-1.1", "taxon": "Theorem", "number": "1.1", "title": "",
              "aliases": ["thm:main"], "page": "", "statement": "…", "proof": "…"}],
 "edges":   [{"src": "…#thm-1.1", "to": "…#lem-2.1", "origin": "internal",
              "confidence": 1.0, "evidence": "\\ref{…}"}]}
```

`numbering` is `compiled` when the numbers came from the paper's own `.aux` and `emulated` when they were counted; `method` is the source adapter, today always `latex`. `statement` and `proof` are the paper's own text, verbatim. The digest beside it is the same content as a document; this file is the index's source.

## 2. Identity and keys

**Schemes**, in resolution order: `doi`, `arxiv`, `mr`, `zbl`, `work`. A DOI is preferred because it names the published work, which is what a bibliography cites; an eprint names a specific preprint, which is what weft can actually fetch. Both are kept when both exist — they are different facts, not competing answers.

**One spelling per identifier** (`crawl.work.norm`): the scheme lowercased, a DOI's value lowercased, an arXiv number without its version. An arXiv DOI (`10.48550/arxiv.X`) normalises to `arxiv:X`, so one artifact has one directory however a bibliography recorded it. A value that is not shaped like a DOI is not a DOI: `identity.is_doi` accepts `10.<digits>/<no whitespace>` and nothing else, which is what stops a service's licence notice from becoming a work.

**A work with no identifier** gets `work:<sha256[:8]>` over its folded surnames, title and year, so two corpora still merge on a book that has no DOI.

**One work is one record under every identifier.** Sources add identifiers as a walk proceeds, so keying on the first one seen records the same work twice; the alias index in `crawl/plan.py` and `merge` in `crawl/work.py` prevent that, and the linker resolves a citation's identifier to the record that holds the work before it looks for an edge.

**A result key is `<version id>#<paperlocal>`** — `arxiv:1709.09864v2#thm-4.1`. The version, not the work, because numbering is a property of the artifact (digest contract §8.1).

## 3. The pipeline

Each step reads what the one before it wrote and writes files; each is resumable, and re-running one costs nothing where the work is already done.

| step | command | reads | writes |
|---|---|---|---|
| plan | `weft crawl plan` | seeds, service answers | `works/*/work.json`, `crawl/plan.json` |
| fetch | `weft crawl fetch` | the plan | `works/*/<version>/src/`, PDFs, updated records |
| extract | `weft extract [--all] [--compile]` | a version's source | `digest.tex`, `results.json` |
| link | `weft link` | every `results.json` and record | the `edges` of each `results.json` |
| index | `weft index rebuild` | everything under `works/` | `index.sqlite` |

`weft survey` counts what the next level cites without keeping anything, for choosing subjects. `weft crawl status` says where a fetch got to.

### 3.1 Asking services politely

Every request goes through one `Service`, so the spacing, the cache and the transport are the same everywhere. Per host, seconds between requests: `arxiv.org` and `export.arxiv.org` 3.0, `api.zbmath.org` 1.0, `api.crossref.org` 1.0, `api.openalex.org` 0.2, anything else 1.0. Bulk downloads take a further 15 seconds (`download.BULK_SPACING`).

The budget is **shared between processes**: the last request per host is recorded under `$WEFT_STATE_DIR`, else `$XDG_CACHE_HOME/weft/hosts`, else `~/.cache/weft/hosts`, because a service throttles a client and two processes are one client. `WEFT_STATE_DIR=` empty turns sharing off, which is what the tests do. `WEFT_OFFLINE_RESPONSES` names a directory of recorded answers; when it is set the default transport makes no request at all, which is why no test touches the network.

E-prints are downloaded from **`export.arxiv.org`**, the host arXiv asks automated clients to use. Both hosts serve the same bytes and both are one host to the budget, but not to arXiv: measured on 2026-09-18, `arxiv.org/e-print/...` answered 406 to urllib and 200 to curl within the same minute, while the export host answered 35 downloads in a row.

### 3.2 Numbering, and why a corpus compiles

Extraction takes numbers from an `.aux` beside the source when there is one, and emulates amsthm's counters otherwise. Emulation does not follow every way a paper can declare its counters, and a locator is an exact string: on the ACGS neighbourhood, compiling turned `Proposition 1.5.6` from a miss into a hit and doubled the locator edges. `weft extract --compile` runs latexmk for the numbers only, per version, and a paper that does not build costs its numbering rather than its extraction.

### 3.3 Proofs

`--proofs verbatim` (the default) keeps each result's proof as the paper wrote it; `--proofs none` keeps none. The digest says on its face which it holds, so a corpus can be audited by reading headers (digest contract §2.6).

## 4. The edges

Three origins and no fourth. Nothing is inferred from similarity, from notation, or from a model's reading.

| origin | drawn by | points at |
|---|---|---|
| `internal` | a `\ref` in a statement or proof to another result of the same version | a result |
| `locator` | `\cite[Theorem 9.4]{key}`, resolved by digest contract §6 | a result |
| `unspecified` | `\cite{key}` with no postnote | a whole work |

A postnote is resolved part by part, so `Theorems 1.1 and 2.3` is two edges and not one ambiguity. A part answering several *different* results of the cited work draws no edge and appends a row to [multi-match-record.md](multi-match-record.md): a wrong dependency is worse than a missing one for anything reasoning over the graph, and the decision waits until the case is understood.

## 5. The surfaces

One set of questions, three faces, all read-only. `weft.query` is the only module that knows how to answer; the others are a few lines each around it.

**CLI** — `search`, `get`, `closure`, `dependents`, `work`, `versions`, `bib`, `index counts`, all printing JSON. See [cli-reference.md](cli-reference.md).

**HTTP** — `weft serve` (127.0.0.1:8791 by default): `/search`, `/result`, `/closure`, `/dependents`, `/work`, `/versions`, `/bib`, `/counts`. A key carries `#` and `/`, so everything is passed as a query parameter and never in a path. CORS is answered permissively: every route is read-only and answers the same to anyone who can already reach the port.

**MCP** — `weft mcp`, JSON-RPC over stdio, protocol `2025-06-18`, no dependency beyond the standard library. Tools: `search_works`, `get_result`, `closure`, `dependents`, `work`, `versions`, `bib`, `counts`, all annotated read-only. `claude mcp add weft -- weft mcp --corpus /path/to/corpus`.

**The view** — `view/`, a SvelteKit single-page app sharing arras's stack, reading the HTTP API: search, a work with its versions and what it cites, a result with its statement, its proof, what uses it, and a force-laid graph of what it rests on. A citation inside a statement is a link wherever the linker resolved it and the printed text wherever it did not. `?api=` points it at a corpus serving elsewhere.

**The index** holds `works`, `work_ids`, `versions`, `results`, `edges`, `refs` and `same_as`; `weft index counts` reports them under the domain's names, which is how a rebuild is checked against what it says it wrote.

## 6. The contracts

**[specs/digest.md](specs/digest.md) is normative**, and the only document here that is. Two independent implementations write digests — loom's `digest extract` for the papers an author cites, weft's extraction for a corpus — and a digest written by either is readable by both. `tests/test_digest_contract.py` exercises its numbered statements.

**weft never reads or writes a quilt.** The seam is `weft bib <identifier>`, which hands over a BibTeX entry with every identifier the corpus holds; your paper's own tool takes it from there. The boundary and what each tool gives up are in [weft-and-loom.md](weft-and-loom.md).

**A corpus is private by default.** Statements and proofs are other people's text, verbatim; `[licence] share` is a recorded posture, not a tool-enforced law.

**Nothing here writes to a corpus except the pipeline.** The HTTP API, the MCP server and the view are read-only by construction, and say so in their annotations.

## 7. Where the numbers are

Measurements live in [records/](records/), dated, with the method beside each number. As of 2026-09-18: the synthetic corpus (3 works, closed) draws every edge kind; ACGS (`arxiv:1709.09864` and what it cites, 47 works, 35 extracted, 2347 results) draws 1606 internal and 8 locator edges; relloc (301 works, 7 with sources) draws 282 internal and none by locator, which is what 2% coverage predicts.

## 8. Working on it

```sh
uv sync
uv run pytest                                   # 187 tests and one network-marked skip; nothing here touches the network
uv run ruff check src tests && uv run mypy
uv run python scripts/gen_cli_reference.py      # after changing a command or its help
cd view && npm run check && npm run test && npm run test:e2e
```

`demos/synthetic/` is a small fabricated corpus, committed, which the tests generate afresh from `scripts/make_synthetic.py`; crawled corpora under `demos/` are gitignored, because they hold other people's papers.
