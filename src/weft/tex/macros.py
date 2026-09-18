"""Macro definitions from a paper's preamble closure, by brace matching rather than by regex alone.

Forms: `\\newcommand{\\x}[n][default]{body}`, `\\newcommand\\x{body}`, `\\renewcommand`, `\\providecommand`, `\\def\\x#1#2{body}`, `\\DeclareMathOperator*{\\x}{body}`, `\\let\\a\\b`, `\\NewDocumentCommand\\x{argspec}{body}`. Later definitions win. Expansion substitutes `#n`, which is what lets a statement be written out with the paper's own notation resolved.
"""

from __future__ import annotations

import re

from weft.tex.model import Macro
from weft.tex.tokenize import match_group, read_optional, skip_space

_HEAD = re.compile(
    r"\\(newcommand|renewcommand|providecommand|DeclareRobustCommand|NewDocumentCommand|RenewDocumentCommand"
    r"|ProvideDocumentCommand|DeclareMathOperator|def|let)(\*?)"
)
_NAME = re.compile(r"\\([A-Za-z@]+|.)")


def _read_name(text: str, pos: int) -> tuple[str | None, int]:
    p = skip_space(text, pos)
    if p < len(text) and text[p] == "{":
        q = match_group(text, p)
        inner = text[p + 1 : q - 1].strip() if q > 0 else ""
        m = _NAME.match(inner)
        return (m.group(1), q) if m and q > 0 else (None, pos)
    m = _NAME.match(text, p)
    return (m.group(1), m.end()) if m else (None, pos)


def _read_body(text: str, pos: int) -> tuple[str | None, int]:
    p = skip_space(text, pos)
    if p < len(text) and text[p] == "{":
        q = match_group(text, p)
        if q > 0:
            return text[p + 1 : q - 1], q
    return None, pos


_ALIAS = re.compile(
    r"\\(?:let|def)\s*\\([A-Za-z@]+)\s*=?\s*\\((?:re|provide)?newcommand|providecommand)\b"
    r"|\\(?:new|renew|provide)command\*?\s*\{?\\([A-Za-z@]+)\}?\s*\{\\((?:re|provide)?newcommand|providecommand)\}"
)


def expand_definition_aliases(text: str) -> str:
    """Rewrite uses of an alias such as `\\nc` (declared by `\\newcommand{\\nc}{\\newcommand}` or `\\let\\nc\\newcommand`) as the command it stands for, so definitions made through it are parsed."""
    for _ in range(4):  # an alias may be declared through another alias (\nc{\renc}{\renewcommand})
        aliases: dict[str, str] = {}
        for a in _ALIAS.finditer(text):
            name = a.group(1) or a.group(3)
            target = a.group(2) or a.group(4)
            if name and target and name not in ("newcommand", "renewcommand", "providecommand"):
                aliases[name] = target
        if not aliases:
            return text
        pattern = re.compile(r"\\(" + "|".join(re.escape(n) for n in aliases) + r")(?![A-Za-z@])")
        table = dict(aliases)

        def _swap(mm: re.Match[str], al: dict[str, str] = table) -> str:
            return "\\" + al[mm.group(1)]

        text = pattern.sub(_swap, text)
    return text


def parse_macros(text: str) -> dict[str, Macro]:
    """Every recognised definition in comment-blanked text.

    Parameters
    ----------
    text : str
        The preamble closure's text.

    Returns
    -------
    dict[str, Macro]
        Macro name, without its backslash, to its last definition.

    See Also
    --------
    expand : substitute arguments into one definition's body.
    """
    text = expand_definition_aliases(text)
    macros: dict[str, Macro] = {}
    for m in _HEAD.finditer(text):
        head, star = m.group(1), m.group(2)
        pos = m.end()
        if head == "let":
            a, pos = _read_name(text, pos)
            p = skip_space(text, pos)
            if p < len(text) and text[p] == "=":
                pos = p + 1
            b, pos = _read_name(text, pos)
            if a and b:
                target = macros.get(b)
                macros[a] = Macro(a, target.args if target else 0, target.body if target else "\\" + b, kind="let")
            continue
        if head == "def":
            name, pos = _read_name(text, pos)
            if not name:
                continue
            params = re.match(r"\s*((?:#\d)*)", text[pos:])
            nargs = len(re.findall(r"#\d", params.group(1))) if params else 0
            pos += params.end() if params else 0
            body, pos = _read_body(text, pos)
            if body is not None:
                macros[name] = Macro(name, nargs, body, kind="def")
            continue
        if head == "DeclareMathOperator":
            name, pos = _read_name(text, pos)
            body, pos = _read_body(text, pos)
            if name and body is not None:
                op = "\\operatorname*" if star else "\\operatorname"
                macros[name] = Macro(name, 0, f"{op}{{{body}}}", kind="operator")
            continue
        if head.endswith("DocumentCommand"):
            name, pos = _read_name(text, pos)
            spec, pos = _read_body(text, pos)
            body, pos = _read_body(text, pos)
            if name and body is not None:
                nargs = len(re.findall(r"[a-zA-Z]", (spec or "").replace("O{", "o{")))
                macros[name] = Macro(name, nargs, body, kind="xparse")
            continue
        name, pos = _read_name(text, pos)
        if not name:
            continue
        nargs = 0
        default: str | None = None
        opt, _, _, pos2 = read_optional(text, pos)
        if opt is not None and opt.strip().isdigit():
            nargs = int(opt.strip())
            pos = pos2
            opt2, _, _, pos3 = read_optional(text, pos)
            if opt2 is not None:
                default = opt2
                pos = pos3
        body, pos = _read_body(text, pos)
        if body is not None:
            macros[name] = Macro(name, nargs, body, default=default, kind="newcommand")
    return macros


def expand(macro: Macro, args: list[str]) -> str:
    """The macro's body with `#1`..`#n` replaced by `args`, the default standing in for an argument that was not given."""
    body = macro.body
    for i in range(macro.args, 0, -1):
        val = args[i - 1] if i - 1 < len(args) else (macro.default or "")
        body = body.replace(f"#{i}", val)
    return body
