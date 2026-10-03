"""Command line interface."""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .report import RENDERERS, meets_threshold
from .rules import RULES
from .scan import apply_fixes, scan


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="agp9-ready", description="Find what Android Gradle Plugin 9 (and 10) breaks in your Gradle files, without running Gradle.")
    p.add_argument("path", nargs="?", default=".", help="project directory (default: .) or one build file")
    p.add_argument("-f", "--format", choices=sorted(RENDERERS), default="text")
    p.add_argument("-o", "--output", help="write the report to a file instead of stdout")
    p.add_argument("--agp-target", type=int, choices=[9, 10], default=9, help="9 (default): opt-out flags are warnings. 10: opt-outs and the legacy APIs are errors")
    p.add_argument("--fail-on", choices=["error", "warning", "never"], default="error", help="lowest severity that gives exit code 1 (default: error)")
    p.add_argument("--ignore", action="append", default=[], metavar="GLOB", help="path glob to skip (repeatable)")
    p.add_argument("--disable", action="append", default=[], metavar="RULE", help="turn a rule off (repeatable)")
    p.add_argument("--only", action="append", default=[], metavar="RULE", help="run only this rule (repeatable)")
    p.add_argument("--fix", action="store_true", help="rewrite files in place for the rules that have a safe automatic fix")
    p.add_argument("--list-rules", action="store_true")
    p.add_argument("--version", action="version", version=f"agp9-ready {__version__}")
    a = p.parse_args(argv)
    if a.list_rules:
        for r in RULES.values():
            print(f"{r.id:<26} {r.severity:<8} {'fix ' if r.fixable else '    '}{'oracle ' if r.oracle else 'docs   '}{r.summary}")
        return 0
    for rid in a.disable + a.only:
        if rid not in RULES:
            print(f"unknown rule: {rid} (see --list-rules)", file=sys.stderr)
            return 2
    if a.fix:
        files, edits = apply_fixes(a.path, a.ignore, a.disable, a.only, a.agp_target)
        print(f"fixed {edits} place(s) in {files} file(s)", file=sys.stderr)
    r = scan(a.path, a.ignore, a.disable, a.only, a.agp_target)
    text = RENDERERS[a.format](r)
    if a.output:
        with open(a.output, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 1 if meets_threshold(r, a.fail_on) else 0


if __name__ == "__main__":
    raise SystemExit(main())
