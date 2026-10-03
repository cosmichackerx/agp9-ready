import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("watch", os.path.join(ROOT, "scripts", "watch", "watch_agp_docs.py"))
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

FIX = os.path.join(ROOT, "tests", "fixtures", "agp")
PAGES = {f[:-5]: open(os.path.join(FIX, f), encoding="utf-8").read() for f in sorted(os.listdir(FIX))}


def run(pages=None, known=None, triaged=None):
    return watch.analyse(pages or PAGES, known if known is not None else watch.load_known(), triaged if triaged is not None else watch.load_triaged(),
                         watch.rule_text(), watch.rule_anchors())


def test_baseline_is_complete_so_first_run_opens_nothing():
    res = run()
    assert not watch.has_news(res), res
    assert res["properties_seen"] >= 20


def test_a_new_release_notes_page_and_its_sections_are_reported():
    pages = dict(PAGES)
    pages["agp-9-5-0"] = '<h2 id="shiny">Shiny new thing</h2><h3 id="fixed-issues-agp-9.5.0">x</h3>'
    res = run(pages)
    assert res["new_pages"] == ["agp-9-5-0"]
    assert res["new_sections"] == [("agp-9-5-0", "shiny", "Shiny new thing")]  # fixed-issues headings are ignored
    title, body = watch.render_issue(res)
    assert "agp-9-5-0-release-notes" in body and title.startswith("AGP docs: 2 change(s)")
    assert watch.render_issue(run(pages))[0] == title  # stable dedupe key


def test_a_new_section_on_a_known_page_is_reported():
    pages = dict(PAGES)
    pages["agp-9-4-0"] = pages["agp-9-4-0"].replace("</body>", '<h2 id="another-opt-out">Another opt-out</h2></body>')
    assert run(pages)["new_sections"] == [("agp-9-4-0", "another-opt-out", "Another opt-out")]


def test_roadmap_date_change_is_title_drift():
    pages = dict(PAGES)
    pages["roadmap"] = pages["roadmap"].replace("AGP 10.0 (late 2026)", "AGP 10.0 (March 2027)")
    assert run(pages)["title_drift"] == [("agp-10", "AGP 10.0 (late 2026)", "AGP 10.0 (March 2027)")]


def test_a_removed_anchor_is_stale():
    pages = dict(PAGES)
    pages["agp-9-0-0"] = pages["agp-9-0-0"].replace('id="android-gradle-plugin-built-in-kotlin"', 'id="renamed"')
    assert ("agp-9-0-0", "android-gradle-plugin-built-in-kotlin") in run(pages)["stale_anchors"]


def test_untracked_property_is_reported_and_triaging_silences_it():
    pages = dict(PAGES)
    sec = "android-gradle-plugin-behavior-changes"
    html = pages["agp-9-0-0"]
    i = html.index(f'id="{sec}"')
    html = html[:i] + html[i:].replace("</h2>", "</h2><code>android.shiny<wbr>NewProperty</code>", 1)
    pages["agp-9-0-0"] = html
    res = run(pages)
    assert res["untracked_properties"] == ["android.shinyNewProperty"]
    assert run(pages, triaged={"android.shinyNewProperty", "android.applicationVariants", "android.txt"})["untracked_properties"] == []


def test_page_url_and_probe_stops_after_two_misses():
    seen = []

    def getter(url):
        seen.append(url)
        ok = url.endswith("gradle-plugin-roadmap") or url.endswith(("agp-9-0-0-release-notes", "agp-9-1-0-release-notes", "agp-9-2-0-release-notes"))
        return (200, "<h2 id='x'>X</h2>") if ok else (404, "")

    pages = watch.fetch_all(getter)
    assert sorted(pages) == ["agp-9-0-0", "agp-9-1-0", "agp-9-2-0", "roadmap"]
    assert not any("agp-9-5-0" in u for u in seen)  # 9.3 and 9.4 missing: stop
    assert any("agp-10-0-0" in u for u in seen)
