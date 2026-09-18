# weft

A machine-readable library of mathematical results: crawl a citation network to arbitrary depth, extract each paper's statements and proofs, link them where the papers say so, and serve the whole thing to a reader and to an AI agent.

Named for the crosswise threads drawn through the warp: the papers are the warp, the links between their results are the weft.

- [docs/plan-0.1-weft.md](docs/plan-0.1-weft.md) — what weft is, its data model, the crawl, the edges it draws, and the milestones.
- [docs/weft-and-loom.md](docs/weft-and-loom.md) — the boundary with [loom](https://github.com/ikmartin/loom), the seam between them, and what loom gives up.

weft never reads or writes a quilt. When you find a work worth citing, `weft bib <identifier>` hands you a bibliography entry and your paper's own tool takes it from there.

## Development

```
uv sync
uv run pytest
uv run ruff check src tests && uv run mypy
```

No test touches the network: service clients take a transport, and recorded answers stand in. `demos/synthetic/` is a small fabricated corpus the tests use; crawled corpora under `demos/` are gitignored, because they hold other people's papers.
