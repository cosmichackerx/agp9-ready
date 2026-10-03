"""PR mode: report only the findings that a change introduces, by scanning the files at a base revision and subtracting.

Findings are matched by (rule, file, source line text), not by line number, so moving code or inserting lines above it does not
make an old finding look new. Renamed files are followed (`git diff -M`). The base is the merge base of REF and HEAD."""
from __future__ import annotations

import collections
import os
import subprocess
import tempfile

from .scan import Result, kind_of, scan


class GitError(Exception):
    pass


def _git(cwd: str, *args: str, data: bytes | None = None) -> bytes:
    try:
        p = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=cwd, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as e:  # git is not installed
        raise GitError("git is required for --base") from e
    if p.returncode != 0:
        raise GitError(p.stderr.decode("utf-8", "replace").strip() or f"git {' '.join(args)} failed")
    return p.stdout


def _text(cwd: str, *args: str) -> str:
    return _git(cwd, *args).decode("utf-8", "replace").strip()


def scan_against_base(path: str, base: str, ignore=(), disabled=(), only=(), target: int = 9) -> Result:
    """Scan `path` (a directory or one file in a git work tree) and keep only the findings that are new compared to `base`."""
    path = os.path.abspath(path)
    cwd = path if os.path.isdir(path) else os.path.dirname(path)
    try:
        top = os.path.realpath(_text(cwd, "rev-parse", "--show-toplevel"))
    except GitError as e:
        raise GitError(f"{path} is not inside a git work tree ({e})") from e
    try:
        _text(top, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    except GitError:
        raise GitError(f"base revision '{base}' not found; in CI fetch full history (actions/checkout with fetch-depth: 0)") from None
    try:
        merge_base = _text(top, "merge-base", base, "HEAD")
    except GitError:
        merge_base = _text(top, "rev-parse", f"{base}^{{commit}}")  # unrelated histories or no HEAD: compare with the ref itself
    head = scan(path, ignore, disabled, only, target)

    real = os.path.realpath(path)
    rel_root = os.path.relpath(real, top).replace(os.sep, "/")
    single = os.path.isfile(path)
    prefix = "" if rel_root == "." else rel_root + "/"
    if single:
        prefix = os.path.dirname(rel_root) + "/" if os.path.dirname(rel_root) else ""

    # files renamed since the base: new name -> old name
    renames = {}
    for line in _text(top, "diff", "--name-status", "-M", merge_base, "--", rel_root).splitlines():
        parts = line.split("\t")
        if parts[0].startswith("R") and len(parts) == 3:
            renames[parts[2]] = parts[1]

    names = [n for n in _text(top, "ls-tree", "-r", "--name-only", merge_base, "--", rel_root).splitlines() if kind_of(os.path.basename(n), n)]
    base_findings: list = []
    with tempfile.TemporaryDirectory(prefix="agp9-base-") as tmp:
        if names:
            blobs = _git(top, "cat-file", "--batch", data="".join(f"{merge_base}:{n}\n" for n in names).encode())
            pos = 0
            for n in names:
                nl = blobs.index(b"\n", pos)
                header = blobs[pos:nl].decode().split()
                size = int(header[2]) if len(header) == 3 and header[1] == "blob" else 0
                body = blobs[nl + 1:nl + 1 + size]
                pos = nl + 1 + size + 1
                dest = os.path.join(tmp, *n.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as fh:
                    fh.write(body)
        root = os.path.join(tmp, *rel_root.split("/")) if rel_root != "." else tmp
        base_res = scan(root if not single else os.path.join(tmp, *rel_root.split("/")), ignore, disabled, only, target)
        base_findings = base_res.findings

    def file_in_head(old: str) -> str:
        new = next((n for n, o in renames.items() if o == prefix + old), None)
        if new is None:
            return old
        return new[len(prefix):] if new.startswith(prefix) else new

    old_counts = collections.Counter((f.rule, file_in_head(f.file), f.snippet) for f in base_findings)
    new_findings, existing = [], 0
    for f in sorted(head.findings, key=lambda f: (f.file, f.line, f.col)):
        k = (f.rule, f.file, f.snippet)
        if old_counts[k] > 0:
            old_counts[k] -= 1
            existing += 1
        else:
            new_findings.append(f)
    resolved = sum(old_counts.values())
    res = Result(findings=new_findings, files_scanned=head.files_scanned, agp=head.agp, target=head.target)
    res.pr = {"base": base, "existing": existing, "resolved": resolved}
    return res
