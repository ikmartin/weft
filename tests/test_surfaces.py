"""The three faces of one set of questions: `weft.query`, the HTTP API and the MCP tools (plan 0.1 M4).

Each surface is tested against the same indexed synthetic corpus, and the payloads are compared to each other rather than only to literals: a reader who asks over HTTP and an agent who asks over MCP must be told the same thing as a caller who imports the module.
"""

from __future__ import annotations

import io
import json
import threading
import urllib.request
from typing import Any

from weft import mcp, query
from weft.config import Settings
from weft.serve import ROUTES, make_server
from weft.store import open_store

TOP = "arxiv:2401.00002v1#thm-1.1"  # cited by both versions of the other paper, and cites a work with no locator


def _query(settings: Settings, call: Any, *args: Any, **kw: Any) -> Any:
    store = open_store(settings)
    try:
        return call(store, *args, **kw)
    finally:
        store.close()


def test_a_result_arrives_with_its_text_and_the_edges_at_both_ends(library: Settings) -> None:
    found = _query(library, query.get, TOP)
    assert found is not None
    assert found["taxon"] == "Theorem" and found["number"] == "1.1" and found["statement"].strip()
    assert {e["origin"] for e in found["uses"]} == {"locator", "unspecified"}
    assert {e["src"] for e in found["used_by"]} >= {"arxiv:2401.00001v1#thm-1.1", "arxiv:2401.00001v2#thm-1.1"}
    assert _query(library, query.get, "arxiv:2401.00002v1#no-such-thing") is None


def test_the_closure_follows_results_reports_whole_work_citations_and_terminates_on_a_cycle(
    library: Settings,
) -> None:
    """The two papers cite each other's Theorem 1.1, so a closure that did not remember where it had been would not return."""
    found = _query(library, query.closure, TOP, text=True)
    reached = {r["key"] for r in found["closure"]}
    assert "arxiv:2401.00001v2#thm-1.1" in reached and TOP not in reached
    assert all(r["statement"] for r in found["closure"]), "with text, every dependency arrives stated"
    assert [e["to"] for e in found["unresolved"]] == ["doi:10.4171/synth.0003"] * len(found["unresolved"])
    assert found["unresolved"], "a citation naming a work and no result ends a branch rather than being followed"
    assert not found["missing"]


def test_what_uses_a_result_and_what_a_work_holds(library: Settings) -> None:
    used = _query(library, query.dependents, TOP)
    assert {u["edge"]["origin"] for u in used["used_by"]} == {"locator", "internal"}, (
        "used by another paper, and by a corollary of its own"
    )
    assert all(u["result"] is not None for u in used["used_by"])

    work = _query(library, query.neighbourhood, "arxiv:2401.00001")
    assert work["found"] and len(work["versions"]) == 2
    assert work["cites"] == ["arxiv:2401.00002", "doi:10.4171/synth.0003"], (
        "what a work cites is other works, named as works, and never itself"
    )
    assert work["references"], "a work's bibliography is part of its neighbourhood"

    versions = _query(library, query.versions, "arxiv:2401.00001")
    by_id = {v["id"]: {r["local"] for r in v["results"]} for v in versions["versions"]}
    assert by_id["arxiv:2401.00001v1"] - by_id["arxiv:2401.00001v2"], "v2 drops a result v1 states, and that is visible"

    assert _query(library, query.versions, "arxiv:9999.99999") == {"key": "arxiv:9999.99999", "found": False}


def test_search_finds_a_work_by_title_and_by_author(library: Settings) -> None:
    by_title = _query(library, query.search, "valuated matroids")
    assert [w["key"] for w in by_title["works"]] == ["arxiv:2401.00001"]
    assert by_title["works"][0]["versions"] == ["arxiv:2401.00001v1", "arxiv:2401.00001v2"]
    assert [w["key"] for w in _query(library, query.search, "Ekstrom")["works"]] == ["arxiv:2401.00002"]


def test_the_http_api_answers_what_the_module_answers(library: Settings) -> None:
    server = make_server(library, port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def ask(path: str) -> tuple[int, Any]:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    try:
        key = urllib.parse.quote(TOP)
        status, payload = ask(f"/result?key={key}")
        assert status == 200 and payload == json.loads(json.dumps(_query(library, query.get, TOP), default=str))
        status, payload = ask(f"/closure?key={key}&depth=2")
        assert status == 200 and payload["depth"] == 2
        status, payload = ask("/result?key=nothing")
        assert status == 404 and payload["error"]
        status, payload = ask("/nowhere")
        assert status == 404 and payload["routes"] == sorted(ROUTES)
        assert ask("/counts")[1]["results"] == 7
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _rpc(settings: Settings, *requests: dict[str, Any]) -> list[dict[str, Any]]:
    """Drive the MCP server over its real transport: newline-delimited JSON in, the same out."""
    out = io.StringIO()
    mcp.serve_stdio(settings, io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n"), out)
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def test_the_mcp_server_handshakes_lists_its_tools_and_ignores_a_notification(library: Settings) -> None:
    answers = _rpc(
        library,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": mcp.PROTOCOL}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "no/such/method"},
    )
    assert [a["id"] for a in answers] == [1, 2, 3], "a notification is not answered"
    assert answers[0]["result"]["protocolVersion"] == mcp.PROTOCOL
    assert answers[0]["result"]["serverInfo"]["name"] == "weft"
    tools = {t["name"]: t for t in answers[1]["result"]["tools"]}
    assert set(tools) == set(mcp.BY_NAME)
    for tool in tools.values():
        assert tool["description"] and tool["inputSchema"]["type"] == "object"
        assert tool["annotations"]["readOnlyHint"], "nothing here writes to a corpus"
    assert answers[2]["error"]["code"] == mcp.METHOD_NOT_FOUND


def test_an_agent_can_answer_what_a_theorem_depends_on_and_where_each_one_is_stated(library: Settings) -> None:
    """M4's acceptance test, asked as an agent would ask it: one tool call, and the answer is in the payload."""
    (answer,) = _rpc(
        library,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "closure", "arguments": {"key": TOP, "text": True}},
        },
    )
    result = answer["result"]
    assert result["isError"] is False
    payload = result["structuredContent"]
    assert payload == json.loads(result["content"][0]["text"]), (
        "the text a model reads is the structure a client parses"
    )
    assert payload == json.loads(json.dumps(_query(library, query.closure, TOP, text=True), default=str))
    for dependency in payload["closure"]:
        assert dependency["version"] and dependency["taxon"] and dependency["statement"].strip()
    assert payload["unresolved"], "and the citations that name no result are said to be unresolved, not dropped"


def test_a_tool_that_finds_nothing_says_so_rather_than_failing(library: Settings) -> None:
    calls = [
        {"name": "get_result", "arguments": {"key": "arxiv:2401.00002v1#nope"}},
        {"name": "not_a_tool", "arguments": {}},
        {"name": "counts", "arguments": {}},
    ]
    answers = _rpc(
        library,
        *[{"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": p} for i, p in enumerate(calls)],
    )
    assert answers[0]["result"]["isError"] and "key" in answers[0]["result"]["content"][0]["text"]
    assert answers[1]["result"]["isError"] and "no such tool" in answers[1]["result"]["content"][0]["text"]
    assert answers[2]["result"]["structuredContent"]["results"] == 7
