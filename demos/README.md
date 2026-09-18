# demos

Three corpora, one committed and two not.

- **`synthetic/`** -- fabricated, committed, and what the tests read. Invented authors and invented mathematics in the real corpus format: two seeds, a work with two versions differing by a dropped result, a metadata-only work, and a source per version with locator and unspecified citations and an inlined bibliography. Written by `scripts/make_synthetic.py`; see [synthetic/README.md](synthetic/README.md).
- **`acgs/`** -- [arXiv:1709.09864](https://arxiv.org/abs/1709.09864) crawled to depth 2, the first seed corpus of the plan's §13.
- **`relloc/`** -- the relative-localization paper's bibliography at depth 2, the second, which loom has already fetched and measured.

`acgs/` and `relloc/` are **gitignored in full**. They hold other people's papers -- sources, PDFs, and statements and proofs copied verbatim -- and a corpus is private by default (§10). Generate them yourself:

    cd demos/acgs && weft crawl plan && weft crawl fetch

The measurements those two produce -- identification rate by depth, how many works have a source, results per paper, how many `\cite[locator]` references resolve and the false-match rate in a hand-checked sample -- are the point of them, and they are what decides whether the cross-paper graph is a product or a research project.
