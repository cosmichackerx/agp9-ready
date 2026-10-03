#!/usr/bin/env python3
"""Check agp9-ready against a real Android Gradle Plugin.

For every case a tiny Android app is generated, `gradle help --warning-mode all` runs on it, and the outcome (build fails /
warns / passes) must agree with whether agp9-ready reports the rule that the case is about. Negative control: the clean case
must pass and produce no error.

usage: run_oracle.py [--gradle PATH] [--agp 9.4.1] [case ...]     (needs ANDROID_HOME, JDK 17+, Gradle 9.1+)
"""
import json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))
from agp9_ready.scan import scan  # noqa: E402

SETTINGS = """pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement { repositories { google(); mavenCentral() } }
rootProject.name = "oracle"
include ":app"
"""
MANIFEST = '<manifest xmlns:android="http://schemas.android.com/apk/res/android"/>\n'


def app(plugins="", android="", tail="", extra_plugins=""):
    return f"""plugins {{
    id 'com.android.application' version 'AGP_VERSION'
{plugins}}}
android {{
    namespace = 'x.y'
    compileSdk = 36
    defaultConfig {{ minSdk = 24 }}
{android}}}
{tail}
"""


def kapp(android="", tail=""):
    return f"""plugins {{
    id("com.android.application") version "AGP_VERSION"
}}
android {{
    namespace = "x.y"
    compileSdk = 36
    defaultConfig {{ minSdk = 24 }}
{android}}}
{tail}
"""


# name: (rule, expectation, regex that must appear in Gradle's output (or None), app/build.gradle, extra gradle.properties lines)
CASES = {
    "clean": (None, "pass", None, app(), ""),
    "kotlin-android-plugin": ("kotlin-android-plugin", "fail", r"no longer required", app("    id 'org.jetbrains.kotlin.android' version '2.3.0'\n"), ""),
    "kapt-plugin": ("kapt-plugin", "fail", r"kapt", app("    id 'org.jetbrains.kotlin.kapt' version '2.3.0'\n"), ""),
    "legacy-variant-api": ("legacy-variant-api", "fail", None, app(android="    applicationVariants.all { v -> println v.name }\n"), ""),
    "variant-filter": ("legacy-variant-api", "fail", None, app(android="    variantFilter { v -> v.ignore = false }\n"), ""),
    "dex-options": ("removed-dsl", "fail", None, app(android="    dexOptions { javaMaxHeapSize = '2g' }\n"), ""),
    "sdk-directory": ("removed-dsl", "fail", None, app(tail="println android.sdkDirectory\n"), ""),
    "density-splits": ("density-splits", "fail", None, app(android="    splits { density { enable = true } }\n"), ""),
    "set-dimension-kotlin": ("set-dimension", "fail", r"setDimension|Unresolved reference|dimension", kapp(android='    flavorDimensions += "a"\n    productFlavors { create("foo") { setDimension("a") } }\n'), "", "build.gradle.kts"),
    "set-dimension-groovy-still-works": (None, "pass", None, app(android="    flavorDimensions = ['a']\n    productFlavors { foo { setDimension 'a' } }\n"), ""),
    "register-transform": ("register-transform", "fail", None, app(tail="android.registerTransform(null)\n"), ""),
    "legacy-extension-type": ("legacy-extension-type", "fail", None, app(tail="def e = project.extensions.getByType(com.android.build.gradle.BaseExtension)\nprintln e\n"), ""),
    "wear-app": ("wear-app", "fail", None, app(tail="dependencies { wearApp 'x:wear:1.0' }\n"), ""),
    "enforced-legacy-variant-flag": ("enforced-property", "fail", r"enableLegacyVariantApi", app(), "android.enableLegacyVariantApi=true\n"),
    "legacy-variant-flag-false": ("removed-property", "warn", r"enableLegacyVariantApi", app(), "android.enableLegacyVariantApi=false\n"),
    "r8-integrated-flag": ("removed-property", "warn", r"integratedResourceShrinking", app(), "android.r8.integratedResourceShrinking=true\n"),
    "r8-precise-flag": ("removed-property", "warn", r"preciseShrinking", app(), "android.enableNewResourceShrinker.preciseShrinking=true\n"),
    "aidl-default-true": ("enforced-property", "fail", r"buildfeatures\.aidl", app(), "android.defaults.buildfeatures.aidl=true\n"),
    "aidl-default-false": ("removed-property", "warn", r"buildfeatures\.aidl", app(), "android.defaults.buildfeatures.aidl=false\n"),
    "renderscript-default-true": ("enforced-property", "fail", r"buildfeatures\.renderscript", app(), "android.defaults.buildfeatures.renderscript=true\n"),
    "renderscript-default-false": ("removed-property", "warn", r"buildfeatures\.renderscript", app(), "android.defaults.buildfeatures.renderscript=false\n"),
    "old-default-use-androidx-false": ("old-default-kept", "pass", None, app(), "android.useAndroidx=false\n"),
    "new-dsl-opt-out": ("new-dsl-opt-out", "warn", r"newDsl", app(), "android.newDsl=false\n"),
    "builtin-kotlin-opt-out": ("built-in-kotlin-opt-out", "warn", r"builtInKotlin", app(), "android.builtInKotlin=false\n"),
}


def run_case(name, spec, gradle, agp, sdk):
    rule, expect, rx, build, props = spec[:5]
    fname = spec[5] if len(spec) > 5 else "build.gradle"
    d = tempfile.mkdtemp(prefix="agp9-oracle-")
    try:
        os.makedirs(os.path.join(d, "app", "src", "main"))
        open(os.path.join(d, "settings.gradle"), "w").write(SETTINGS)
        open(os.path.join(d, "app", "src", "main", "AndroidManifest.xml"), "w").write(MANIFEST)
        open(os.path.join(d, "local.properties"), "w").write("sdk.dir=%s\n" % sdk)
        open(os.path.join(d, "gradle.properties"), "w").write("org.gradle.jvmargs=-Xmx1g\n" + props)
        open(os.path.join(d, "app", fname), "w").write(build.replace("AGP_VERSION", agp))
        p = subprocess.run([gradle, "help", "--warning-mode", "all", "--no-daemon", "--console=plain"], cwd=d, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, timeout=900)
        out = p.stdout
        failed = p.returncode != 0
        warned = bool(rx) and re.search(rx, out) is not None and not failed
        outcome = "fail" if failed else ("warn" if warned else "pass")
        res = scan(d)
        got = {f.rule for f in res.findings}
        errors = [f for f in res.findings if f.severity == "error"]
        gradle_ok = outcome == expect and (rx is None or re.search(rx, out) is not None or expect == "fail")
        if expect == "fail" and rx:
            gradle_ok = failed and re.search(rx, out) is not None
        ours_ok = (rule in got) if rule else not errors
        return gradle_ok, ours_ok, outcome, out
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    argv = sys.argv[1:]
    gradle = argv[argv.index("--gradle") + 1] if "--gradle" in argv else "gradle"
    agp = argv[argv.index("--agp") + 1] if "--agp" in argv else "9.4.1"
    names = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] not in ("--gradle", "--agp"))]
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or "/usr/local/lib/android/sdk"
    bad = 0
    for name, spec in CASES.items():
        if names and name not in names:
            continue
        g_ok, o_ok, outcome, out = run_case(name, spec, gradle, agp, sdk)
        status = "ok " if g_ok and o_ok else "BAD"
        why = ""
        m = re.search(r"\* What went wrong:\n(.*?)\n\n", out, re.S)
        if m:
            why = " | " + " ".join(m.group(1).split())[:150]
        elif spec[2]:
            w = re.search(r"(?m)^.*(?:%s).*$" % spec[2], out)
            why = " | " + (w.group(0).strip()[:150] if w else "")
        print(f"{status} {name:<30} expected gradle={spec[1]:<5} got={outcome:<5} agp9-ready flags {spec[0] or 'nothing'}: {'yes' if o_ok else 'NO'}{why}", flush=True)
        if not (g_ok and o_ok):
            bad += 1
            print("    " + "\n    ".join([l for l in out.splitlines() if l.strip()][:14]))
    print(f"{bad} disagreement(s) with AGP {agp}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
