"""The crawl: identify the seeds, walk their references to depth, filter, and fetch what the plan selected.

The contract the CLI relies on, and the only surface the rest of weft uses:

    plan(settings, *, refresh=False, clients=None) -> Plan
    survey(settings, *, refresh=False, clients=None) -> Survey
    fetch(settings, plan, *, downloaders=None) -> FetchReport
    status(settings) -> Status

Each returned object carries `summary() -> str` for a person and `payload() -> dict` for `--json`. `clients` and `downloaders` are injection points: tests pass fakes, and no test touches the network.

Two rules the modules below keep, both of them lessons rather than preferences. Every request for a host passes one budget whatever command asked for it, because a service throttles a client and not a command. And a work is one record under every identifier anything has for it, because keying on the first identifier seen recorded one work twice as later sources added identifiers.
"""

from __future__ import annotations

from weft.crawl.fetch import FetchReport, Status, fetch, status
from weft.crawl.plan import Plan, PlanRefused, Survey, plan, survey

__all__ = [
    "FetchReport",
    "Plan",
    "PlanRefused",
    "Status",
    "Survey",
    "fetch",
    "plan",
    "status",
    "survey",
]
