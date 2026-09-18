"""The `weft` command line. Every command reads a corpus at or above the working directory, and only the crawl touches the network."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from weft import __version__
from weft.config import ConfigError, Settings, load, write_template

EXIT_OK = 0
EXIT_CONTENT = 1
EXIT_USAGE = 2


def note(message: str) -> None:
    """Everything but data goes to stderr, so `--json` on stdout stays machine-readable."""
    click.echo(message, err=True)


def emit(obj: Any) -> None:
    click.echo(json.dumps(obj, indent=2, sort_keys=True, default=str))


def settings_or_exit(ctx: click.Context, corpus: str | None) -> Settings:
    try:
        return load(Path(corpus).expanduser() if corpus else None)
    except ConfigError as exc:
        note(f"Error: {exc}")
        ctx.exit(EXIT_USAGE)
        raise AssertionError("unreachable") from None  # pragma: no cover


corpus_option = click.option(
    "--corpus", default=None, metavar="PATH", help="The corpus root (default: found by walking up)."
)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", message="weft %(version)s")
def main() -> None:
    """A library of mathematical results: crawl, extract, link, serve."""


@main.command()
@click.argument("directory", required=False, default=".")
@click.pass_context
def init(ctx: click.Context, directory: str) -> None:
    """Write a corpus skeleton (weft.toml, works/, cache/, crawl/) into DIRECTORY."""
    try:
        path = write_template(Path(directory).expanduser())
    except ConfigError as exc:
        note(f"Error: {exc}")
        ctx.exit(EXIT_USAGE)
        return
    click.echo(f"wrote {path}")
    note("Name your seeds and, for depth > 1, the subjects to keep; `weft survey` says what is there.")


@main.group()
def crawl() -> None:
    """Plan, fetch and report on the walk through the citation network."""


@crawl.command("plan")
@click.option("--refresh", is_flag=True, help="Ignore cached service answers.")
@click.option("--json", "as_json", is_flag=True)
@corpus_option
@click.pass_context
def crawl_plan(ctx: click.Context, refresh: bool, as_json: bool, corpus: str | None) -> None:
    """Identify the seeds, walk their references to depth, and write crawl/plan.json. Downloads nothing."""
    from weft.crawl import PlanRefused
    from weft.crawl import plan as run_plan

    settings = settings_or_exit(ctx, corpus)
    try:
        made = run_plan(settings, refresh=refresh)
    except PlanRefused as exc:
        note(f"Error: {exc}")
        ctx.exit(EXIT_CONTENT)
        return
    emit(made.payload()) if as_json else click.echo(made.summary())


@crawl.command("fetch")
@click.option("--json", "as_json", is_flag=True)
@corpus_option
@click.pass_context
def crawl_fetch(ctx: click.Context, as_json: bool, corpus: str | None) -> None:
    """Download what the plan selected, under the cap, resuming what is already on disk."""
    from weft.crawl import fetch as run_fetch
    from weft.crawl.plan import load_plan

    settings = settings_or_exit(ctx, corpus)
    made = load_plan(settings)
    if made is None:
        note("Error: no plan; run `weft crawl plan`")
        ctx.exit(EXIT_CONTENT)
        return
    if not made.current(settings):
        note("Error: the plan was made from other settings or another bibliography; run `weft crawl plan` again")
        ctx.exit(EXIT_CONTENT)
        return
    report = run_fetch(settings, made)
    emit(report.payload()) if as_json else click.echo(report.summary())


@crawl.command("status")
@click.option("--json", "as_json", is_flag=True)
@corpus_option
@click.pass_context
def crawl_status(ctx: click.Context, as_json: bool, corpus: str | None) -> None:
    """What is downloaded, failed, still under the cap, and beyond it."""
    from weft.crawl import status as run_status

    settings = settings_or_exit(ctx, corpus)
    report = run_status(settings)
    emit(report.payload()) if as_json else click.echo(report.summary())


@main.command()
@click.option("--refresh", is_flag=True, help="Ignore cached service answers.")
@click.option("--json", "as_json", is_flag=True)
@corpus_option
@click.pass_context
def survey(ctx: click.Context, refresh: bool, as_json: bool, corpus: str | None) -> None:
    """Count what the next level cites, by subject and by category, and say what to configure. Writes no plan."""
    from weft.crawl import survey as run_survey

    settings = settings_or_exit(ctx, corpus)
    found = run_survey(settings, refresh=refresh)
    emit(found.payload()) if as_json else click.echo(found.summary())


@main.command()
@click.argument("idents", nargs=-1, metavar="[IDENT]...")
@click.option("--all", "redo", is_flag=True, help="Re-extract versions that already have results.")
@click.option(
    "--proofs",
    type=click.Choice(["verbatim", "none"]),
    default="verbatim",
    show_default=True,
    help="Keep each result's proof, or keep none of them.",
)
@click.option(
    "--compile", "run_compile", is_flag=True, help="Run latexmk for real numbers where no .aux is beside the source."
)
@click.option("--json", "as_json", is_flag=True)
@corpus_option
@click.pass_context
def extract(
    ctx: click.Context,
    idents: tuple[str, ...],
    redo: bool,
    proofs: str,
    run_compile: bool,
    as_json: bool,
    corpus: str | None,
) -> None:
    """Read the named works' LaTeX sources into statements and proofs; with no IDENT, every version that has a source and no results."""
    from weft.extract import extract_corpus

    settings = settings_or_exit(ctx, corpus)
    report = extract_corpus(settings, idents, proofs=proofs, redo=redo, compile=run_compile)
    if as_json:
        emit(report.payload())
    else:
        click.echo(report.summary())
    if report.refused and not report.extracted:
        ctx.exit(EXIT_CONTENT)


@main.group()
def index() -> None:
    """The queryable view of the corpus, derived from works/."""


@index.command("rebuild")
@click.option("--json", "as_json", is_flag=True)
@corpus_option
@click.pass_context
def index_rebuild(ctx: click.Context, as_json: bool, corpus: str | None) -> None:
    """Throw the index away and replay every record under works/ into it."""
    from weft.store import open_store
    from weft.store.rebuild import rebuild

    settings = settings_or_exit(ctx, corpus)
    store = open_store(settings)
    try:
        counts = rebuild(settings, store)
    finally:
        store.close()
    if as_json:
        emit(counts)
        return
    click.echo(", ".join(f"{n} {name}" for name, n in sorted(counts.items())))


@index.command("counts")
@click.option("--json", "as_json", is_flag=True)
@corpus_option
@click.pass_context
def index_counts(ctx: click.Context, as_json: bool, corpus: str | None) -> None:
    """What the index holds."""
    from weft.store import open_store

    settings = settings_or_exit(ctx, corpus)
    store = open_store(settings)
    try:
        counts = store.counts()
    finally:
        store.close()
    if as_json:
        emit(counts)
        return
    click.echo(", ".join(f"{n} {name}" for name, n in sorted(counts.items())))


@main.command()
@click.option("--json", "as_json", is_flag=True)
@corpus_option
@click.pass_context
def link(ctx: click.Context, as_json: bool, corpus: str | None) -> None:
    """Draw the edges the papers state, into each version's results.json. Ambiguities are logged, never guessed at."""
    from weft.link import link as run_link

    settings = settings_or_exit(ctx, corpus)
    report = run_link(settings)
    emit(report.payload()) if as_json else click.echo(report.summary())


def _with_store(ctx: click.Context, corpus: str | None):  # type: ignore[no-untyped-def]
    """The corpus's index, opened and closed around one query."""
    from contextlib import closing

    from weft.store import open_store

    return closing(open_store(settings_or_exit(ctx, corpus)))


@main.command()
@click.argument("text")
@click.option("--limit", default=25, show_default=True)
@corpus_option
@click.pass_context
def search(ctx: click.Context, text: str, limit: int, corpus: str | None) -> None:
    """Works whose title or authors answer TEXT."""
    from weft import query

    with _with_store(ctx, corpus) as store:
        emit(query.search(store, text, limit=limit))


@main.command()
@click.argument("key")
@click.option("--no-text", is_flag=True, help="Leave the statement and the proof out.")
@corpus_option
@click.pass_context
def get(ctx: click.Context, key: str, no_text: bool, corpus: str | None) -> None:
    """One result by key (arxiv:1709.09864v2#thm-4.1), with what it uses and what uses it."""
    from weft import query

    with _with_store(ctx, corpus) as store:
        found = query.get(store, key, text=not no_text)
    if found is None:
        note(f"Error: {key} is not a result of this corpus")
        ctx.exit(EXIT_CONTENT)
        return
    emit(found)


@main.command()
@click.argument("key")
@click.option("--depth", default=6, show_default=True)
@click.option("--text", is_flag=True, help="Include each statement.")
@corpus_option
@click.pass_context
def closure(ctx: click.Context, key: str, depth: int, text: bool, corpus: str | None) -> None:
    """Everything a result depends on, and the citations that name no result."""
    from weft import query

    with _with_store(ctx, corpus) as store:
        emit(query.closure(store, key, depth=depth, text=text))


@main.command()
@click.argument("key")
@corpus_option
@click.pass_context
def dependents(ctx: click.Context, key: str, corpus: str | None) -> None:
    """What uses a result."""
    from weft import query

    with _with_store(ctx, corpus) as store:
        emit(query.dependents(store, key))


@main.command()
@click.argument("identifier")
@corpus_option
@click.pass_context
def work(ctx: click.Context, identifier: str, corpus: str | None) -> None:
    """A work, its versions, its results, and what it cites."""
    from weft import query

    with _with_store(ctx, corpus) as store:
        emit(query.neighbourhood(store, identifier))


@main.command()
@click.argument("identifier")
@corpus_option
@click.pass_context
def versions(ctx: click.Context, identifier: str, corpus: str | None) -> None:
    """The versions of a work and what each one states, so a result dropped between them is visible."""
    from weft import query

    with _with_store(ctx, corpus) as store:
        emit(query.versions(store, identifier))


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8791, show_default=True)
@corpus_option
@click.pass_context
def serve(ctx: click.Context, host: str, port: int, corpus: str | None) -> None:
    """Answer the same queries over HTTP, read-only, for the view and for anything else that would rather ask over a socket."""
    from weft.serve import ROUTES
    from weft.serve import serve as run_serve

    settings = settings_or_exit(ctx, corpus)
    note(f"weft serving {settings.root} at http://{host}:{port} · routes: {' '.join(sorted(ROUTES))}")
    run_serve(settings, host, port)


@main.command()
@corpus_option
@click.pass_context
def mcp(ctx: click.Context, corpus: str | None) -> None:
    """Answer the same queries as MCP tools on stdin and stdout, for an agent rather than a shell."""
    from weft.mcp import TOOLS, serve_stdio

    settings = settings_or_exit(ctx, corpus)
    note(f"weft mcp over {settings.root} · tools: {' '.join(t.name for t in TOOLS)}")
    serve_stdio(settings)


@main.command()
@click.argument("identifier")
@corpus_option
@click.pass_context
def bib(ctx: click.Context, identifier: str, corpus: str | None) -> None:
    """A BibTeX entry for a work, with every identifier the corpus holds for it: the handoff to a paper's own tool."""
    from weft.bibtex import entry_for
    from weft.store import open_store

    settings = settings_or_exit(ctx, corpus)
    store = open_store(settings)
    try:
        work = store.work(identifier)
        if work is None:
            note(f"Error: {identifier} is not a work of this corpus")
            ctx.exit(EXIT_CONTENT)
            return
        click.echo(entry_for(work))
    finally:
        store.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
