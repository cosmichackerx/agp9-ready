"""Small lexers for Groovy and Kotlin build scripts.

`blank_comments(text, kotlin)` returns the text with every comment replaced by spaces (newlines kept, so
offsets and line numbers stay valid) and strings left alone. `blank_strings(text, kotlin)` additionally blanks
the *contents* of string literals, so patterns cannot match inside them. `ignore_directives` reads
`agp9-ready: ignore <rule>...` out of the comments.
"""
from __future__ import annotations

import re

_IGNORE = re.compile(r"agp9-ready:\s*ignore\b([^\n]*)")


def _scan(text: str, kotlin: bool, keep_strings: bool):
    """Yield (blanked_text, comments) where comments is a list of (offset, comment_text)."""
    out = list(text)
    comments = []
    n = len(text)
    i = 0
    # stack of template-expression brace depths for "${ ... }" inside strings
    tmpl: list = []
    depth_stack: list = []

    def blank(a, b):
        for k in range(a, b):
            if out[k] != "\n" and out[k] != "\r":
                out[k] = " "

    def read_string(i):
        """i points at an opening quote. Returns the index after the string, blanking contents if requested."""
        q = text[i]
        triple = text.startswith(q * 3, i) and (kotlin or q in "'\"")
        if kotlin and q == "'":
            triple = False
        start = i
        if triple:
            i += 3
            end = q * 3
        else:
            i += 1
            end = q
        raw = triple
        while i < n:
            c = text[i]
            if c == "\\" and not (kotlin and raw):
                i += 2
                continue
            if text.startswith(end, i):
                if triple:  # allow """" at the end
                    while text.startswith(q, i + 3):
                        i += 1
                i += len(end)
                if not keep_strings:
                    blank(start + (3 if triple else 1), i - (3 if triple else 1))
                return i
            if c == "\n" and not triple:
                break  # unterminated: stop at line end
            if c == "$" and q == '"' and text.startswith("${", i):
                # nested expression: skip to the matching brace, honouring nested strings
                j = i + 2
                d = 1
                while j < n and d:
                    cj = text[j]
                    if cj == "{":
                        d += 1
                    elif cj == "}":
                        d -= 1
                    elif cj in "\"'":
                        j = read_string(j)
                        continue
                    j += 1
                if not keep_strings:
                    blank(i, j)
                i = j
                continue
            i += 1
        if not keep_strings:
            blank(start + 1, i)
        return i

    while i < n:
        c = text[i]
        two = text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            j = n if j < 0 else j
            comments.append((i, text[i:j]))
            blank(i, j)
            i = j
        elif two == "/*":
            depth = 1
            j = i + 2
            while j < n and depth:
                if kotlin and text.startswith("/*", j):
                    depth += 1
                    j += 2
                elif text.startswith("*/", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            comments.append((i, text[i:j]))
            blank(i, j)
            i = j
        elif c in "\"'":
            i = read_string(i)
        else:
            i += 1
    return "".join(out), comments


def blank_comments(text: str, kotlin: bool = False) -> str:
    return _scan(text, kotlin, True)[0]


def blank_strings(text: str, kotlin: bool = False) -> str:
    return _scan(text, kotlin, False)[0]


def ignore_directives(text: str, kotlin: bool = False):
    """Return {line_number: set(rule ids or {'*'})} for lines an ignore comment applies to (its own line and the next)."""
    res: dict = {}
    _, comments = _scan(text, kotlin, True)
    for off, body in comments:
        m = _IGNORE.search(body)
        if not m:
            continue
        rules = set(re.findall(r"[a-z][a-z0-9\-]+", m.group(1))) or {"*"}
        line = text.count("\n", 0, off) + 1
        last = line + body.count("\n")
        for ln in (line, last + 1):
            res.setdefault(ln, set()).update(rules)
    return res
