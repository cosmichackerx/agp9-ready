#!/usr/bin/env python3
"""Diff the Android Gradle plugin documentation against the agp9-ready rule table.

Pages read (developer.android.com, plain HTML with heading ids):
  * the Gradle plugin roadmap,
  * the release notes of every AGP 9.x (probes 9.0.0, 9.1.0, ... until two minors in a row are missing) and of AGP 10.x.

It reports, as ONE deduplicated issue payload:
  * a release-notes page that did not exist before (a new AGP minor, or AGP 10) and every section id that is not in `known_sections.txt`
    (`fixed-issues-*` headings are ignored);
  * a roadmap heading whose title changed (the roadmap carries the dates, e.g. "AGP 10.0 (late 2026)");
  * `android.*` property names in the AGP 9.0.0 notes (removed / enforced properties, behavior changes) that no rule mentions and
    that are not in `triaged.txt`;
  * rule anchors (the rule table cites the 9.0.0 notes and the roadmap) that no longer exist in the pages.

Standard library only. Exit codes: 0 nothing new, 3 something to look at, 2 usage/network error.
Heading ids are a proxy: the pages do not tag items as "affects build files" in a machine-readable way.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Dict, List, Optional, Set, Tuple

BASE = "https://developer.android.com/build/releases/"
ROADMAP = "roadmap"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
KNOWN = os.path.join(HERE, "known_sections.txt")
TRIAGED = os.path.join(HERE, "triaged.txt")
PROPERTY_SECTIONS = ("android-gradle-plugin-removed-gradle-properties", "android-gradle-plugin-enforced-gradle-properties",
                     "android-gradle-plugin-behavior-changes")
NOTES_90 = "agp-9-0-0"
SKIP_PREFIX = ("fixed-issues",)


def page_url(name: str) -> str:
    return BASE + ("gradle-plugin-roadmap" if name == ROADMAP else name + "-release-notes")


class _Headings(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: List[Tuple[int, str, str]] = []
        self._cur: Optional[List] = None

    def handle_starttag(self, tag, attrs):
        if tag in ("h2", "h3"):
            self._cur = [int(tag[1]), dict(attrs).get("id") or "", []]

    def handle_data(self, data):
        if self._cur is not None:
            self._cur[2].append(data)

    def handle_endtag(self, tag):
        if self._cur is not None and tag in ("h2", "h3"):
            level, hid, parts = self._cur
            self._cur = None
            if hid:
                self.headings.append((level, hid, re.sub(r"[\u200b\s]+", " ", "".join(parts)).strip()))


def sections(html: str) -> Dict[str, str]:
    """id -> title for h2/h3 headings (without the fixed-issues ones)."""
    p = _Headings()
    p.feed(html)
    return {hid: title for _, hid, title in p.headings if not hid.startswith(SKIP_PREFIX)}


def section_html(html: str, hid: str) -> str:
    i = html.find('id="%s"' % hid)
    if i < 0:
        return ""
    j = html.find("<h2", i + 10)
    return html[i:j if j > 0 else len(html)]


def property_names(html: str) -> List[str]:
    out: Set[str] = set()
    for hid in PROPERTY_SECTIONS:
        text = re.sub(r"<[^>]+>", "", section_html(html, hid))
        out.update(re.findall(r"android\.[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*", text))
    return sorted(out)


def rule_text() -> str:
    d = os.path.join(ROOT, "src", "agp9_ready")
    return "".join(open(os.path.join(d, n), encoding="utf-8").read() for n in ("scan.py", "rules.py"))


def rule_anchors() -> Dict[str, Set[str]]:
    """page name -> anchors cited by rules."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from agp9_ready.rules import RULES  # noqa: WPS433

    res: Dict[str, Set[str]] = {NOTES_90: set(), ROADMAP: set()}
    for r in RULES.values():
        if "#" not in r.url:
            continue
        url, anchor = r.url.split("#", 1)
        if url == page_url(NOTES_90):
            res[NOTES_90].add(anchor)
        elif url == page_url(ROADMAP):
            res[ROADMAP].add(anchor)
    return res


def load_known(path: str = KNOWN) -> Dict[str, str]:
    """'page:id' -> title."""
    out: Dict[str, str] = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if line.strip() and not line.startswith("#"):
                key, _, title = line.rstrip("\n").partition("\t")
                out[key] = title
    return out


def load_triaged(path: str = TRIAGED) -> Set[str]:
    out: Set[str] = set()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.split("#", 1)[0].strip()
            if line:
                out.add(line.split()[0])
    return out


def analyse(pages: Dict[str, str], known: Dict[str, str], triaged: Set[str], text: str, anchors: Dict[str, Set[str]]) -> Dict:
    """Pure function over page HTML (name -> html); name is 'roadmap' or 'agp-9-4-0'."""
    new_pages, new_sections, drift, stale = [], [], [], []
    known_pages = {k.split(":", 1)[0] for k in known}
    for name in sorted(pages):
        secs = sections(pages[name])
        if name not in known_pages:
            new_pages.append(name)
        for hid, title in secs.items():
            key = f"{name}:{hid}"
            if key not in known:
                new_sections.append((name, hid, title))
            elif name == ROADMAP and known[key] and known[key] != title:
                drift.append((hid, known[key], title))
    for name, cited in anchors.items():
        if name in pages:
            ids = set(re.findall(r'\bid="([^"]+)"', pages[name]))
            stale += [(name, a) for a in sorted(cited) if a not in ids]
    props = property_names(pages[NOTES_90]) if NOTES_90 in pages else []
    untracked = [p for p in props if p not in text and p not in triaged]
    return {"pages": sorted(pages), "new_pages": new_pages, "new_sections": new_sections, "title_drift": drift,
            "stale_anchors": stale, "untracked_properties": untracked, "properties_seen": len(props)}


def has_news(res: Dict) -> bool:
    return bool(res["new_pages"] or res["new_sections"] or res["title_drift"] or res["stale_anchors"] or res["untracked_properties"])


def key_for(res: Dict) -> str:
    parts = (["page:" + p for p in res["new_pages"]] + [f"sec:{n}:{h}" for n, h, _ in res["new_sections"]] +
             [f"drift:{h}:{b}" for h, _, b in res["title_drift"]] + [f"stale:{n}:{a}" for n, a in res["stale_anchors"]] +
             ["prop:" + p for p in res["untracked_properties"]])
    return hashlib.sha1("\n".join(sorted(parts)).encode()).hexdigest()[:8]


def render_issue(res: Dict) -> Tuple[str, str]:
    key = key_for(res)
    n = len(res["new_pages"]) + len(res["new_sections"]) + len(res["title_drift"]) + len(res["stale_anchors"]) + len(res["untracked_properties"])
    title = f"AGP docs: {n} change(s) to look at [{key}]"
    L = ["Opened by the scheduled `AGP docs watch` workflow.", ""]
    if res["new_pages"]:
        L += ["### New release-notes pages", ""] + [f"- [{p}]({page_url(p)})" for p in res["new_pages"]] + [""]
    if res["title_drift"]:
        L += ["### Roadmap headings whose title changed (dates move here)", ""]
        L += [f"- `{h}`: \"{a}\" -> \"{b}\"" for h, a, b in res["title_drift"]] + [""]
    if res["new_sections"]:
        L += ["### New sections", "", "| Page | Section |", "|---|---|"]
        L += [f"| {p} | [{t}]({page_url(p)}#{h}) |" for p, h, t in res["new_sections"]] + [""]
    if res["stale_anchors"]:
        L += ["### Rule anchors that no longer exist", ""] + [f"- `{p}` `#{a}`" for p, a in res["stale_anchors"]] + [""]
    if res["untracked_properties"]:
        L += ["### Gradle properties in the 9.0.0 notes that no rule mentions", ""] + [f"- `{p}`" for p in res["untracked_properties"]] + [""]
    L += ["### What to do", "",
          "1. Read the section; add a rule in `src/agp9_ready/rules.py` / `scan.py` (cite the anchor), or",
          "2. record it as known: add `page:id<TAB>title` to `scripts/watch/known_sections.txt` or the property to `scripts/watch/triaged.txt` with a reason.",
          "Close this issue when the lists cover every row.", "",
          "Headings are a proxy: the pages do not mark items as affecting build files.", f"\n<!-- agp9-ready:watch:{key} -->"]
    return title, "\n".join(L)


def fetch(url: str, timeout: int = 30) -> Tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "agp9-ready-watch"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https URLs)
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def fetch_all(getter=fetch) -> Dict[str, str]:
    pages: Dict[str, str] = {}
    for name in (ROADMAP, NOTES_90):
        st, html = getter(page_url(name))
        if st != 200 or not html:
            raise OSError(f"{page_url(name)} returned HTTP {st}")
        pages[name] = html
    for major, limit in ((9, 30), (10, 4)):
        misses = 0
        for minor in range(0 if major == 10 else 1, limit):
            name = f"agp-{major}-{minor}-0"
            st, html = getter(page_url(name))
            if st == 200 and html:
                pages[name] = html
                misses = 0
            else:
                misses += 1
                if misses >= 2:
                    break
    return pages


def known_lines(pages: Dict[str, str]) -> List[str]:
    out = []
    for name in sorted(pages):
        for hid, title in sections(pages[name]).items():
            out.append(f"{name}:{hid}\t{title if name == ROADMAP else ''}")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pages-dir", help="read roadmap.html and agp-X-Y-Z.html from this directory instead of fetching")
    ap.add_argument("--known", default=KNOWN)
    ap.add_argument("--triaged", default=TRIAGED)
    ap.add_argument("--out", help="write the result JSON (including issue title/body) here")
    ap.add_argument("--print-baseline", action="store_true", help="print known_sections.txt lines for the pages as they are now")
    a = ap.parse_args(argv)
    try:
        if a.pages_dir:
            pages = {os.path.splitext(f)[0]: open(os.path.join(a.pages_dir, f), encoding="utf-8").read()
                     for f in sorted(os.listdir(a.pages_dir)) if f.endswith(".html")}
        else:
            pages = fetch_all()
    except (OSError, urllib.error.URLError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.print_baseline:
        print("\n".join(known_lines(pages)))
        return 0
    if not sections(pages.get(ROADMAP, "")) or not sections(pages.get(NOTES_90, "")):
        print("error: found no headings; the page layout may have changed", file=sys.stderr)
        return 2
    res = analyse(pages, load_known(a.known), load_triaged(a.triaged), rule_text(), rule_anchors())
    if has_news(res):
        res["title"], res["body"] = render_issue(res)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2)
    print(f"pages: {', '.join(res['pages'])}; properties checked: {res['properties_seen']}")
    for p in res["new_pages"]:
        print("  NEW PAGE", p)
    for p, h, t in res["new_sections"]:
        print(f"  NEW SECTION {p}#{h}: {t}")
    for h, x, y in res["title_drift"]:
        print(f"  ROADMAP TITLE {h}: {x!r} -> {y!r}")
    for p, an in res["stale_anchors"]:
        print(f"  STALE ANCHOR {p}#{an}")
    for p in res["untracked_properties"]:
        print("  UNTRACKED PROPERTY", p)
    return 3 if has_news(res) else 0


if __name__ == "__main__":
    sys.exit(main())
