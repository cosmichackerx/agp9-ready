"""Sticky pull request comment: create it once, update the same comment on every run. Used by the GitHub Action (`comment: true`).

usage: python -m agp9_ready.comment REPORT.md
Reads the pull_request event from GITHUB_EVENT_PATH; the token comes from GITHUB_TOKEN. Never fails the job."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

MARKER = "<!-- agp9-ready:sticky -->"
MAX_COMMENT = 60000  # GitHub rejects bodies over 65536 characters


def build_body(markdown: str) -> str:
    text = markdown.strip()
    if len(text) > MAX_COMMENT:
        text = text[:MAX_COMMENT] + "\n\n_(report truncated; see the job summary for the full text)_"
    return f"{MARKER}\n{text}\n"


def eligibility(event, repo: str):
    """Returns ('ok', pr_number) or ('skip', reason). Forks are skipped: their token is read-only."""
    pr = (event or {}).get("pull_request") if isinstance(event, dict) else None
    if not pr or not isinstance(pr.get("number"), int):
        return "skip", "not a pull request event"
    head = ((pr.get("head") or {}).get("repo") or {}).get("full_name")
    if not head or head.lower() != repo.lower():
        return "skip", "pull request from a fork (the token is read-only there)"
    return "ok", pr["number"]


class _Denied(Exception):
    pass


def _call(api: str, token: str, method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(api.rstrip("/") + path, data=data, method=method, headers={
        "Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "agp9-ready", **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise _Denied(f"HTTP {e.code}; grant pull-requests: write") from None
        raise


def upsert(api: str, token: str, repo: str, pr: int, markdown: str):
    """('created'|'updated'|'unchanged'|'skipped', id-or-reason)"""
    body = build_body(markdown)
    try:
        existing = None
        for page in range(1, 11):
            _, items = _call(api, token, "GET", f"/repos/{repo}/issues/{pr}/comments?per_page=100&page={page}")
            existing = next((c for c in items if isinstance(c.get("body"), str) and c["body"].startswith(MARKER)), None)
            if existing or len(items) < 100:
                break
        if existing:
            if existing["body"] == body:
                return "unchanged", existing["id"]
            _call(api, token, "PATCH", f"/repos/{repo}/issues/comments/{existing['id']}", {"body": body})
            return "updated", existing["id"]
        _, created = _call(api, token, "POST", f"/repos/{repo}/issues/{pr}/comments", {"body": body})
        return "created", created["id"]
    except _Denied as e:
        return "skipped", str(e)
    except urllib.error.HTTPError as e:
        return "skipped", f"GitHub API error HTTP {e.code}"


def main(argv, env=None, log=print) -> int:
    env = os.environ if env is None else env
    if not argv:
        log("usage: python -m agp9_ready.comment REPORT.md")
        return 2
    repo, token, event_path = env.get("GITHUB_REPOSITORY"), env.get("GITHUB_TOKEN"), env.get("GITHUB_EVENT_PATH")
    if not (repo and token and event_path):
        log("::notice::agp9-ready: no sticky comment (GITHUB_REPOSITORY, GITHUB_TOKEN or GITHUB_EVENT_PATH missing)")
        return 0
    try:
        with open(event_path, encoding="utf-8") as fh:
            verdict, val = eligibility(json.load(fh), repo)
        if verdict == "skip":
            log(f"::notice::agp9-ready: no sticky comment ({val})")
            return 0
        with open(argv[0], encoding="utf-8") as fh:
            md = fh.read()
        action, info = upsert(env.get("GITHUB_API_URL", "https://api.github.com"), token, repo, val, md)
        log(f"::warning::agp9-ready: sticky comment skipped: {info}" if action == "skipped" else f"agp9-ready: sticky comment {action} (#{info})")
    except Exception as e:  # never fail the job over a comment
        log(f"::warning::agp9-ready: sticky comment failed: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
