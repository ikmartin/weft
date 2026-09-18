"""Reading a digest's provenance header back out of the file.

A digest says on its face what it contains (docs/specs/digest.md §2), which is what lets a corpus be audited by reading headers rather than by trusting the tool that wrote them; these are the readers that do it, and the tests that pin the contract use them rather than a second regex of their own.
"""

from __future__ import annotations

import re

from weft.tex.directives import HEAD_LINES, list_value

ALWAYS_LOADED = {"amsmath", "amsthm", "loom"}
_PACKAGE = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
_DIRECTIVE = re.compile(r"^[ \t]*%[ \t]*!LOOM[ \t]+([a-z][a-z-]*)[ \t]*:[ \t]*(.*?)[ \t]*$", re.M)


def header(text: str, head_lines: int = HEAD_LINES) -> dict[str, str]:
    """The `key: value` directives of a digest's header, in the order they are written.

    Parameters
    ----------
    text : str
        The digest file's text.
    head_lines : int, default 20
        How far in to look; §1.2 makes a file a digest by a `digest:` directive in its first twenty lines.

    Returns
    -------
    dict[str, str]
        Key to value. Python keeps insertion order, so a caller can check the order of §2 as well as the contents.
    """
    head = "\n".join(text.split("\n")[:head_lines])
    return {m.group(1): m.group(2) for m in _DIRECTIVE.finditer(head)}


def is_digest(text: str) -> bool:
    """Whether the file is a digest: a `digest:` directive in its first twenty lines (§1.2)."""
    return "digest" in header(text)


def required_packages(text: str) -> list[str]:
    """The digest's `requires:` list."""
    return list_value(header(text).get("requires", ""))


def loaded_packages(preamble_text: str) -> set[str]:
    """Package names a preamble closure loads with `\\usepackage` or `\\RequirePackage`."""
    out: set[str] = set()
    for m in _PACKAGE.finditer(preamble_text):
        for name in m.group(1).split(","):
            name = name.strip()
            if name:
                out.add(name)
    return out


def macro_block(text: str) -> str:
    """The text between `% !LOOM begin macros` and `% !LOOM end macros`, or '' when the digest has no block (§5.1)."""
    m = re.search(
        r"^[ \t]*%[ \t]*!LOOM[ \t]+begin macros[ \t]*$(.*?)^[ \t]*%[ \t]*!LOOM[ \t]+end macros", text, re.M | re.S
    )
    return m.group(1).strip("\n") if m else ""
