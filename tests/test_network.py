"""The one test that asks the real services. Skipped unless WEFT_NETWORK=1, so nothing here runs by default."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from support import corpus
from weft.crawl.plan import plan
from weft.crawl.work import load_all

SEED = "arxiv:1709.09864"


@pytest.mark.network
def test_a_depth_one_plan_for_one_arxiv_seed(tmp_path: Path) -> None:
    if not os.environ.get("WEFT_NETWORK"):
        pytest.skip("set WEFT_NETWORK=1 to ask zbMATH Open, OpenAlex, arXiv and Crossref")
    settings = corpus(tmp_path, works=[SEED], depth=1)
    made = plan(settings)
    assert made.counts["works"] == 1 and made.counts["downloadable"] == 1
    records = load_all(settings.works_dir)
    record = next(iter(records.values()))
    assert SEED in [i.lower() for i in record.ids] or record.key == SEED
    assert record.title and record.downloadable == "source"
    assert made.current(settings)
