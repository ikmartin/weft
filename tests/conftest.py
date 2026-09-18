"""Fixtures every test module may ask for. Helpers that are imported rather than injected live in `support.py`."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]


def _generator() -> Any:
    """The synthetic corpus's generator, loaded from scripts/ so a test never reads the committed copy."""
    spec = importlib.util.spec_from_file_location("make_synthetic", REPO / "scripts" / "make_synthetic.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _no_shared_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests do not share a host budget across processes: an empty WEFT_STATE_DIR keeps the waiting in the injected clock rather than on the wall."""
    monkeypatch.setenv("WEFT_STATE_DIR", "")


@pytest.fixture
def synthetic(tmp_path: Path) -> Path:
    """A freshly generated synthetic corpus, writable, so a test may edit or delete its files."""
    dest = tmp_path / "synthetic"
    _generator().write_corpus(dest)
    return dest


@pytest.fixture
def library(synthetic: Path) -> Any:
    """The synthetic corpus extracted, linked and indexed: the corpus every query surface answers from."""
    from weft.config import load
    from weft.extract import extract_corpus
    from weft.link import link
    from weft.store import open_store
    from weft.store.rebuild import rebuild

    settings = load(synthetic)
    extract_corpus(settings)
    link(settings, log=synthetic / "record.md")
    store = open_store(settings)
    try:
        rebuild(settings, store)
    finally:
        store.close()
    return settings
