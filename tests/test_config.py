"""`weft.toml`: where it is found, what it refuses, and what it never stores."""

from __future__ import annotations

from pathlib import Path

import pytest

from weft.config import CONFIG, TEMPLATE, ConfigError, Settings, find_root, load, write_template

SEEDED = """
[seeds]
works = ["arxiv:1709.09864"]
"""


def make(root: Path, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / CONFIG).write_text(body, encoding="utf-8")
    return root


def test_find_root_walks_up(tmp_path: Path) -> None:
    root = make(tmp_path / "corpus", SEEDED)
    deep = root / "works" / "arxiv" / "1709.09864"
    deep.mkdir(parents=True)
    assert find_root(deep) == root
    assert find_root(deep / "work.json") == root


def test_find_root_absent(tmp_path: Path) -> None:
    assert find_root(tmp_path) is None
    with pytest.raises(ConfigError, match="weft init"):
        load(tmp_path)


def test_template_parses_and_its_defaults_arrive(tmp_path: Path) -> None:
    path = write_template(tmp_path)
    assert path.read_text(encoding="utf-8") == TEMPLATE
    for d in ("works", "cache", "crawl"):
        assert (tmp_path / d).is_dir()
    # The template names no seed on purpose, so the skeleton does not load until the author says what to crawl.
    with pytest.raises(ConfigError, match=r"\[seeds\]"):
        load(tmp_path)
    path.write_text(TEMPLATE.replace("works = []", 'works = ["arxiv:1709.09864"]', 1), encoding="utf-8")
    settings = load(tmp_path)
    assert settings.root == tmp_path
    assert settings.works == ["arxiv:1709.09864"]
    assert (settings.depth, settings.cap, settings.share) == (2, 200, False)
    assert settings.dsn == "sqlite:index.sqlite"
    assert settings.works_dir == tmp_path / "works"
    assert settings.cache_dir == tmp_path / "cache"
    assert settings.crawl_dir == tmp_path / "crawl"


def test_write_template_refuses_to_overwrite(tmp_path: Path) -> None:
    write_template(tmp_path)
    with pytest.raises(ConfigError, match="exists"):
        write_template(tmp_path)


def test_refuses_depth_below_one(tmp_path: Path) -> None:
    make(tmp_path, SEEDED + "\n[crawl]\ndepth = 0\n")
    with pytest.raises(ConfigError, match="depth must be at least 1"):
        load(tmp_path)


def test_refuses_a_corpus_with_no_seeds(tmp_path: Path) -> None:
    make(tmp_path, "[seeds]\nworks = []\nbib = []\n")
    with pytest.raises(ConfigError, match="at least one work or one BibTeX file"):
        load(tmp_path)


def test_refuses_a_named_bib_that_is_absent(tmp_path: Path) -> None:
    make(tmp_path, '[seeds]\nbib = ["refs.bib"]\n')
    with pytest.raises(ConfigError, match="refs.bib"):
        load(tmp_path)
    (tmp_path / "refs.bib").write_text("", encoding="utf-8")
    settings = load(tmp_path)
    assert settings.seed_bib_paths() == [tmp_path / "refs.bib"]


def test_refuses_toml_it_cannot_parse(tmp_path: Path) -> None:
    make(tmp_path, "[seeds\nworks = [")
    with pytest.raises(ConfigError, match=CONFIG):
        load(tmp_path)


def test_index_path_relative_and_absolute(tmp_path: Path) -> None:
    relative = Settings(root=tmp_path, dsn="sqlite:index.sqlite")
    assert relative.index_path == tmp_path / "index.sqlite"
    nested = Settings(root=tmp_path, dsn="sqlite:var/weft.db")
    assert nested.index_path == tmp_path / "var" / "weft.db"
    elsewhere = tmp_path / "elsewhere" / "weft.db"
    absolute = Settings(root=tmp_path, dsn=f"sqlite:{elsewhere}")
    assert absolute.index_path == elsewhere


def test_openalex_key_comes_only_from_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make(tmp_path, SEEDED + '\n[sources]\ncontact = "someone@example.org"\n')
    monkeypatch.delenv("WEFT_OPENALEX_KEY", raising=False)
    settings = load(tmp_path)
    assert settings.openalex_key is None
    assert "WEFT_OPENALEX_KEY" not in (tmp_path / CONFIG).read_text(encoding="utf-8")
    monkeypatch.setenv("WEFT_OPENALEX_KEY", "k-123")
    assert load(tmp_path).openalex_key == "k-123"
    monkeypatch.setenv("WEFT_OPENALEX_KEY", "")
    assert load(tmp_path).openalex_key is None


def test_fingerprint_material_is_order_independent(tmp_path: Path) -> None:
    one = Settings(root=tmp_path, works=["b", "a"], subjects=["14N", "14D"])
    other = Settings(root=tmp_path, works=["a", "b"], subjects=["14D", "14N"])
    assert one.fingerprint_material() == other.fingerprint_material()
