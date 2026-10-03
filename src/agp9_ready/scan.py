"""File discovery, project context and the rule detectors."""
from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field

from .lexer import blank_comments, blank_strings, ignore_directives
from .rules import RULES

SKIP_DIRS = {".git", ".gradle", ".idea", "build", "out", "node_modules", ".kotlin", ".svn", "dist", "target"}


@dataclass
class Finding:
    rule: str
    severity: str
    file: str
    line: int
    col: int
    message: str
    snippet: str
    edit: tuple | None = None  # (start, end, replacement) in the original file text

    @property
    def url(self) -> str:
        return RULES[self.rule].url


@dataclass
class Result:
    findings: list = field(default_factory=list)
    files_scanned: int = 0
    agp: str | None = None
    target: int = 9
    pr: dict | None = None  # set in PR mode (--base): {base, existing, resolved}


CONVENTION_DIRS = {"buildSrc", "build-logic", "buildLogic"}
SOURCE_EXT = (".kt", ".java", ".groovy")


def kind_of(name: str, rel: str | None = None):
    if name.endswith(".gradle.kts"):
        return "kotlin"
    if name.endswith(".gradle"):
        return "groovy"
    if name == "gradle.properties":
        return "props"
    if name == "gradle-wrapper.properties":
        return "wrapper"
    if name.endswith(".versions.toml"):
        return "catalog"
    if rel is not None and name.endswith(SOURCE_EXT):
        parts = rel.split("/")[:-1]
        if any(seg in CONVENTION_DIRS for seg in parts):
            return "source"  # convention-plugin sources of buildSrc / build-logic
    return None


def discover(root: str, ignore: list):
    root = os.path.abspath(root)
    if os.path.isfile(root):
        yield root, os.path.basename(root)
        return
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS)
        for fn in sorted(fns):
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if kind_of(fn, rel) is None:
                continue
            if any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(fn, g) for g in ignore):
                continue
            yield full, rel


# ---------------------------------------------------------------- small parsers

def parse_properties(text: str) -> dict:
    """key -> (value, offset of the key, offset of line start, offset after the line incl. newline)."""
    out, off = {}, 0
    for ln in text.split("\n"):
        s = ln.strip()
        if s and not s.startswith(("#", "!")):
            m = re.match(r"([^=:\s]+)\s*[=:]\s*(.*)$", s)
            if m:
                out[m.group(1)] = (m.group(2).strip(), off + ln.index(m.group(1)), off, off + len(ln) + 1)
        off += len(ln) + 1
    return out


def parse_catalog(text: str) -> dict:
    """Minimal TOML reader for version catalogs: {section: {key: {attr: value, '_off': offset}}}; one-line entries only."""
    out, sec, off = {}, None, 0
    for ln in text.split("\n"):
        s = ln.strip()
        m = re.match(r"\[([\w.-]+)\]$", s)
        if m:
            sec = m.group(1)
            out.setdefault(sec, {})
        elif sec and s and not s.startswith("#"):
            m = re.match(r"""([\w.-]+)\s*=\s*(.*)$""", s)
            if m:
                key, rest = m.group(1), m.group(2)
                ent = {"_off": off + ln.index(key)}
                q = re.match(r"""["']([^"']*)["']""", rest)
                if q:
                    ent["value"] = q.group(1)
                else:
                    for k, v in re.findall(r"""([\w.]+)\s*=\s*["']([^"']*)["']""", rest):
                        ent[k] = v
                out[sec][key] = ent
        off += len(ln) + 1
    return out


def vtuple(v: str):
    nums = re.findall(r"\d+", v.split("-")[0])
    return tuple(int(n) for n in nums) if nums else None


def version_lt(v: str, bound: str) -> bool:
    a, b = vtuple(v), vtuple(bound)
    return bool(a and b and a < b)


class Project:
    """What the rules need to know about the whole build: gradle.properties, the version catalog, the AGP version."""

    def __init__(self, target: int = 9):
        self.target = target
        self.props: dict = {}
        self.catalog: dict = {}
        self.agp: str | None = None

    @property
    def new_dsl_off(self) -> bool:
        return self.props.get("android.newDsl", ("",))[0].lower() == "false"

    @property
    def builtin_off(self) -> bool:
        return self.props.get("android.builtInKotlin", ("",))[0].lower() == "false"

    @property
    def agp_major(self):
        t = vtuple(self.agp) if self.agp else None
        return t[0] if t else None

    def catalog_version(self, ent: dict):
        if "version" in ent:
            return ent["version"]
        ref = ent.get("version.ref") or ent.get("version.ref".replace(".", "_"))
        if ref:
            return self.catalog.get("versions", {}).get(ref, {}).get("value")
        return ent.get("value") if False else None

    def plugin_alias_ids(self) -> dict:
        """libs.plugins.<alias with dots> -> plugin id."""
        return {k.replace("-", ".").replace("_", "."): v.get("id") for k, v in self.catalog.get("plugins", {}).items() if v.get("id")}

    def detect_agp(self, texts: dict):
        for k in ("agp", "androidGradlePlugin", "android-gradle-plugin", "androidGradle", "android-gradle", "gradle-plugin-android"):
            v = self.catalog.get("versions", {}).get(k, {}).get("value")
            if v and vtuple(v):
                self.agp = v
                return
        for k, ent in self.catalog.get("plugins", {}).items():
            if ent.get("id", "").startswith("com.android.") and not ent.get("id", "").startswith(("com.android.legacy", "com.android.built-in")):
                v = self.catalog_version(ent)
                if v and vtuple(v):
                    self.agp = v
                    return
        for k, ent in self.catalog.get("libraries", {}).items():
            if (ent.get("module") == "com.android.tools.build:gradle"):
                v = self.catalog_version(ent)
                if v and vtuple(v):
                    self.agp = v
                    return
        for text in texts.values():
            m = re.search(r"""com\.android\.tools\.build:gradle:(\d[\w.\-]*)""", text) or \
                re.search(r"""['"]com\.android\.(?:application|library)['"]\)?\s+version\s+['"](\d[\w.\-]*)['"]""", text)
            if m:
                self.agp = m.group(1)
                return


class Ctx:
    def __init__(self, rel: str, text: str, kind: str, project: Project):
        self.rel, self.text, self.kind, self.p = rel, text, kind, project
        self.kotlin = kind == "kotlin" or (kind == "source" and rel.endswith(".kt"))
        code = kind in ("kotlin", "groovy", "source")
        self.code = blank_comments(text, self.kotlin) if code else text
        self.nostr = blank_strings(text, self.kotlin) if code else text
        self.out: list = []

    def line(self, off: int) -> int:
        return self.text.count("\n", 0, off) + 1

    def snippet(self, off: int) -> str:
        s = self.text.rfind("\n", 0, off) + 1
        e = self.text.find("\n", off)
        return self.text[s:e if e >= 0 else len(self.text)].strip()[:160]

    def line_span(self, off: int):
        s = self.text.rfind("\n", 0, off) + 1
        e = self.text.find("\n", off)
        return s, (len(self.text) if e < 0 else e + 1)

    def add(self, rule: str, off: int, message: str | None = None, edit=None, severity: str | None = None):
        r = RULES[rule]
        ln = self.line(off)
        col = off - (self.text.rfind("\n", 0, off) + 1) + 1
        self.out.append(Finding(rule, severity or r.severity, self.rel, ln, col, message or r.summary, self.snippet(off), edit))


def block_spans(nostr: str, name_re: str):
    """Yield (body_start, body_end) for every `name { ... }` block; braces are matched on string-blanked text."""
    for m in re.finditer(r"(?<![\w.])(?:%s)\s*\{" % name_re, nostr):
        depth, i = 1, m.end()
        while i < len(nostr) and depth:
            depth += {"{": 1, "}": -1}.get(nostr[i], 0)
            i += 1
        yield m.end(), i - 1


# ---------------------------------------------------------------- detectors

_KOTLIN_ANDROID = [
    r"""\bid\s*\(?\s*["'](?:org\.jetbrains\.kotlin\.android|kotlin-android)["']\s*\)?""",
    r"""\bkotlin\s*\(\s*["']android["']\s*\)""",
    r"""\bapply\s*(?:\(\s*)?plugin\s*[:=]\s*["'](?:org\.jetbrains\.kotlin\.android|kotlin-android)["']""",
]
_KAPT = [
    r"""\bid\s*\(?\s*["'](?:org\.jetbrains\.kotlin\.kapt|kotlin-kapt)["']\s*\)?""",
    r"""\bkotlin\s*\(\s*["']kapt["']\s*\)""",
    r"""\bapply\s*(?:\(\s*)?plugin\s*[:=]\s*["'](?:org\.jetbrains\.kotlin\.kapt|kotlin-kapt)["']""",
]
_PLUGIN_LINE = re.compile(r"""^\s*(?:id\s*\(?\s*["'][^"']+["']\s*\)?|kotlin\s*\(\s*["']\w+["']\s*\)|alias\s*\(\s*libs\.plugins\.[\w.]+\s*\)|apply\s*(?:\(\s*)?plugin\s*[:=]\s*["'][^"']+["']\s*\)?)(?:\s+version\s+["'][^"']*["'])?\s*;?\s*$""")


def _plugin_hits(c: Ctx, patterns, catalog_ids):
    """Offsets of plugin applications matching `patterns` or a catalog alias whose id is in `catalog_ids`; skips `apply false`."""
    hits = []
    for pat in patterns:
        hits += [m.start() for m in re.finditer(pat, c.code)]
    aliases = c.p.plugin_alias_ids()
    for m in re.finditer(r"\balias\s*\(\s*libs\.plugins\.([\w.]+)\s*\)", c.code):
        if aliases.get(m.group(1)) in catalog_ids:
            hits.append(m.start())
    out = []
    for off in sorted(set(hits)):
        s, e = c.line_span(off)
        if re.search(r"\bapply\s+false\b|\bapply\s*=\s*false\b", c.code[s:e]):
            continue
        out.append(off)
    return out


def _delete_line_edit(c: Ctx, off: int):
    s, e = c.line_span(off)
    if _PLUGIN_LINE.match(c.code[s:e].rstrip("\n")) and "\n" not in c.code[s:e].rstrip("\n"):
        return (s, e, "")
    return None


def kotlin_plugins(c: Ctx):
    if c.kind not in ("kotlin", "groovy"):
        return
    opt = c.p.builtin_off
    tgt10 = c.p.target >= 10
    for off in _plugin_hits(c, _KOTLIN_ANDROID, {"org.jetbrains.kotlin.android"}):
        sev = "warning" if (opt and not tgt10) else "error"
        msg = RULES["kotlin-android-plugin"].summary
        if opt:
            msg = "`kotlin-android` is applied because `android.builtInKotlin=false` opts out of built-in Kotlin; the opt-out is removed in AGP 10"
        c.add("kotlin-android-plugin", off, msg, None if opt else _delete_line_edit(c, off), sev)
    for off in _plugin_hits(c, _KAPT, {"org.jetbrains.kotlin.kapt"}):
        sev = "warning" if (opt and not tgt10) else "error"
        c.add("kapt-plugin", off, None, None, sev)


_VARIANT = re.compile(r"(?<![\w])(?:applicationVariants|libraryVariants|testVariants|unitTestVariants|variantFilter|registerJavaGeneratingTask|registerResGeneratingTask)\b")


def legacy_api(c: Ctx):
    if c.kind not in ("kotlin", "groovy"):
        return
    sev = "warning" if (c.p.new_dsl_off and c.p.target < 10) else "error"
    for m in _VARIANT.finditer(c.nostr):
        name = m.group(0)
        c.add("legacy-variant-api", m.start(), f"`{name}` belongs to the legacy variant API, removed with the new DSL (AGP 9 default) and in AGP 10", None, sev)
    for m in re.finditer(r"""\b(?:import\s+com\.android\.build\.gradle\.(?:BaseExtension|AppExtension|LibraryExtension|TestExtension|internal\.dsl\.BaseAppModuleExtension)|BaseAppModuleExtension|BaseExtension|AppExtension)\b""", c.code):
        c.add("legacy-extension-type", m.start(), None, None, sev)
    for m in re.finditer(r"\bregisterTransform\s*[(\s]", c.nostr):
        c.add("register-transform", m.start())
    for m in (re.finditer(r"""\bsetDimension(?:\s*\(\s*(?P<a>["'][^"'\n]*["'])\s*\)|[ \t]+(?P<b>["'][^"'\n]*["']))""", c.code) if c.kotlin else ()):
        c.add("set-dimension", m.start(), None, (m.start(), m.end(), f"dimension = {m.group('a') or m.group('b')}"))


_REMOVED_IN_ANDROID = r"dexOptions|deviceProvider|testServer|generatePureSplits"
_REMOVED_DOTTED = re.compile(r"""\bandroid\s*\.\s*(?:get)?(sdkDirectory|ndkDirectory|bootClasspath|adbExecutable|adbExe|dexOptions|deviceProvider|testServer)\b""", re.I)


def removed_dsl(c: Ctx):
    if c.kind not in ("kotlin", "groovy"):
        return
    seen = set()
    for a, b in block_spans(c.nostr, r"android"):
        body = c.nostr[a:b]
        for m in re.finditer(r"(?<![\w.])(%s)\b(?=\s*[{(=\s])" % _REMOVED_IN_ANDROID, body):
            seen.add(a + m.start())
            c.add("removed-dsl", a + m.start(), f"`{m.group(1)}` is removed with the new DSL", severity=None)
        for m in re.finditer(r"(?<![\w.])jni\s*(?:\.\s*srcDirs?|\{)", body):
            seen.add(a + m.start())
            c.add("removed-dsl", a + m.start(), "`jni` source set is removed (it was not functional)")
        for sa, sb in block_spans(body, r"splits"):
            for m in re.finditer(r"(?<![\w.])density\b", body[sa:sb]):
                c.add("density-splits", a + sa + m.start())
        for m in re.finditer(r"\bwearAppConfigurationName\b", body):
            c.add("wear-app", a + m.start(), "`wearAppConfigurationName` is removed with embedded Wear OS apps")
    for m in _REMOVED_DOTTED.finditer(c.nostr):
        if m.start() not in seen:
            c.add("removed-dsl", m.start(), f"`android.{m.group(1)}` is removed with the new DSL; use `androidComponents.sdkComponents` / Gradle-managed devices")
    for m in re.finditer(r"""(?<![\w.])wearApp\s*[(\s]\s*(?:project|["'])""", c.code):
        c.add("wear-app", m.start())


# Observed with AGP 9.4.1 (tests/oracle): setting these to true fails the build; any other value only prints "option is deprecated".
_FAIL_WHEN_TRUE = ("android.enableLegacyVariantApi", "android.defaults.buildfeatures.aidl", "android.defaults.buildfeatures.renderscript")
# AGP 9.4.1 only warns that these have no effect (the release notes say AGP throws an error).
_NO_EFFECT = ("android.r8.integratedResourceShrinking", "android.enableNewResourceShrinker.preciseShrinking")
# property -> value that keeps the AGP 8.13 behaviour (AGP 9.0 release notes, "Behavior changes")
_OLD_DEFAULTS = {
    "android.uniquePackageNames": "false", "android.useAndroidx": "false", "android.default.androidx.test.runner": "false",
    "android.dependency.useConstraints": "true", "android.enableAppCompileTimeRClass": "false",
    "android.sdk.defaultTargetSdkToCompileSdkIfUnset": "false", "android.onlyEnableUnitTestForTheTestedBuildType": "false",
    "android.proguard.failOnMissingFiles": "false", "android.r8.optimizedResourceShrinking": "false",
    "android.r8.strictFullModeForKeepRules": "false", "android.defaults.buildfeatures.resvalues": "true",
    "android.defaults.buildfeatures.shaders": "true", "android.r8.proguardAndroidTxt.disallowed": "false",
    "android.r8.globalOptionsInConsumerRules.disallowed": "false", "android.sourceset.disallowProvider": "false",
    "android.custom.shader.path.required": "false",
}


def properties_file(c: Ctx):
    if c.kind != "props":
        return
    tgt10 = c.p.target >= 10
    for k, (v, o, ls, le) in parse_properties(c.text).items():
        if k in _FAIL_WHEN_TRUE and v.lower() == "true":
            fix = (ls, le, "") if k == "android.enableLegacyVariantApi" else None
            more = "" if fix else "; turn the feature on per module with android { buildFeatures { ... = true } }, then delete the line"
            c.add("enforced-property", o, f"`{k}=true` makes AGP 9 stop the build{more}", fix)
        elif k in _FAIL_WHEN_TRUE or k in _NO_EFFECT:
            c.add("removed-property", o, f"`{k}` was removed in AGP 9 and has no effect; delete it", (ls, le, ""))
        elif k == "android.newDsl" and v.lower() == "false":
            c.add("new-dsl-opt-out", o, None, None, "error" if tgt10 else None)
        elif k == "android.newDsl.optOut":
            c.add("new-dsl-opt-out", o, f"`android.newDsl.optOut={v}` is a temporary per-module opt-out, removed in AGP 10", None, "error" if tgt10 else None)
        elif k == "android.builtInKotlin" and v.lower() == "false":
            c.add("built-in-kotlin-opt-out", o, None, None, "error" if tgt10 else None)
        elif k in _OLD_DEFAULTS and v.lower() == _OLD_DEFAULTS[k]:
            c.add("old-default-kept", o, f"`{k}={v}` keeps the AGP 8.13 behaviour; AGP 9 changed the default")


def wrapper(c: Ctx):
    if c.kind != "wrapper":
        return
    m = re.search(r"distributionUrl\s*=.*?gradle-(\d[\w.\-]*?)-(?:bin|all)\.zip", c.text.replace("\\:", ":"))
    if m and version_lt(m.group(1), "9.1.0"):
        sev = "error" if (c.p.agp_major or 0) >= 9 else "warning"
        c.add("gradle-wrapper-too-old", m.start(), f"Gradle {m.group(1)} is older than the 9.1.0 that AGP 9.0 requires", None, sev)


# id, version below which an opt-out is reported, flags (from JetBrains' kotlin-tooling-agp9-migration PLUGIN-COMPATIBILITY.md, snapshot 2026-10-03)
PLUGIN_TABLE = [
    ("androidx.baselineprofile", "1.5.0", ("android.newDsl=false",)),
    ("de.mannodermaus.android-junit5", "1.13.4.0", ("android.newDsl=false",)),
    ("com.google.android.gms.oss-licenses-plugin", "0.10.8", ("android.newDsl=false",)),
    ("com.apollographql.apollo", "4.4.0", ("android.newDsl=false",)),
    ("org.gradle.android.cache-fix", "3.0.2", ("android.newDsl=false",)),
    ("com.github.triplet.play", "4.0.0", ("android.newDsl=false",)),
    ("io.gitlab.arturbosch.detekt", "2.0.0", ("android.newDsl=false", "android.builtInKotlin=false")),
    ("dev.icerock.mobile.multiplatform-resources", "0.26.0", ("android.builtInKotlin=false", "android.newDsl=false", "android.sourceset.disallowProvider=false")),
    ("app.cash.sqldelight", None, ("android.newDsl=false", "android.disallowKotlinSourceSets=false")),
    ("com.google.protobuf", None, ("android.newDsl=false",)),
    ("app.cash.paparazzi", None, ("android.newDsl=false",)),
    ("org.jlleitschuh.gradle.ktlint", None, ("android.builtInKotlin=false",)),
]


def _plugin_refs(c: Ctx):
    """Yield (plugin id, version or None, offset) for plugin applications in a build file or a version catalog."""
    if c.kind == "catalog":
        for k, ent in c.p.catalog.get("plugins", {}).items():
            if ent.get("id") and ent["_off"] < len(c.text) and c.text.startswith(k, ent["_off"]):
                yield ent["id"], c.p.catalog_version(ent), ent["_off"]
        return
    for m in re.finditer(r"""\bid\s*\(?\s*["']([\w.\-]+)["']\s*\)?(?:\s+version\s+["']([^"']+)["'])?""", c.code):
        yield m.group(1), m.group(2), m.start()
    for m in re.finditer(r"""["']([\w.\-]+):([\w.\-]+):(\d[\w.\-]*)["']""", c.code):
        yield m.group(1), m.group(3), m.start()  # classpath coordinates, group used as an approximation of the plugin id
        yield m.group(1) + "." + m.group(2), m.group(3), m.start()


def plugin_compat(c: Ctx):
    if c.kind not in ("kotlin", "groovy", "catalog"):
        return
    flags_set = {f"{k}={v[0].lower()}" for k, v in c.p.props.items()}
    for pid, ver, off in _plugin_refs(c):
        for tid, below, flags in PLUGIN_TABLE:
            if pid != tid or (below and ver and not version_lt(ver, below)):
                continue
            if below and not ver:
                continue
            if all(f in flags_set for f in flags):
                continue
            sev = "warning" if below else "note"
            v = f" {ver}" if ver else ""
            c.add("plugin-opt-out-needed", off, f"`{pid}`{v} is reported to need {' and '.join('`' + f + '`' for f in flags)} on AGP 9" + (f" (fixed in {below})" if below else " (check your version)"), None, sev)


def ksp(c: Ctx):
    if c.kind not in ("kotlin", "groovy", "catalog"):
        return
    for pid, ver, off in _plugin_refs(c):
        if pid != "com.google.devtools.ksp" or not ver:
            continue
        if re.match(r"^\d+\.\d+\.\d+-\d+\.\d+\.\d+$", ver):
            c.add("ksp-version", off, f"KSP `{ver}` uses the old `<kotlin>-<ksp>` scheme; Android's AGP 9 upgrade skill asks for KSP 2.3.6 or newer")
        elif version_lt(ver, "2.3.6"):
            c.add("ksp-version", off, f"KSP `{ver}` is older than 2.3.6")


_LEGACY_EXT = "BaseExtension|AppExtension|LibraryExtension|TestExtension|internal\\.dsl\\.BaseAppModuleExtension"
_LEGACY_VARIANT_TYPES = "api\\.(?:BaseVariant|ApplicationVariant|LibraryVariant|TestVariant|UnitTestVariant)"
_SRC_KOTLIN_APPLY = r"""\bapply\s*\(\s*(?:plugin\s*=\s*)?["']%s["']"""
_SRC_VARIANT_CALL = re.compile(r"\.\s*(applicationVariants|libraryVariants|testVariants|unitTestVariants|registerJavaGeneratingTask|registerResGeneratingTask)\b")


def convention_sources(c: Ctx):
    """buildSrc / build-logic sources (.kt, .java, .groovy): conservative checks on imports, qualified names and `apply("plugin.id")`."""
    if c.kind != "source":
        return
    sev = "warning" if (c.p.new_dsl_off and c.p.target < 10) else "error"
    star = re.search(r"\bimport\s+com\.android\.build\.gradle\.\*", c.code) is not None
    for m in re.finditer(r"\bcom\.android\.build\.gradle\.(?:%s)\b" % _LEGACY_EXT, c.code):
        c.add("legacy-extension-type", m.start(), None, None, sev)
    if star:
        for m in re.finditer(r"(?<![\w.])(?:BaseExtension|AppExtension|LibraryExtension|TestExtension)\b", c.nostr):
            c.add("legacy-extension-type", m.start(), None, None, sev)
    for m in re.finditer(r"\bcom\.android\.build\.gradle\.%s\b" % _LEGACY_VARIANT_TYPES, c.code):
        c.add("legacy-variant-api", m.start(), "the legacy variant API types (`com.android.build.gradle.api.*Variant`) are removed with the new DSL (AGP 9 default) and in AGP 10", None, sev)
    for m in _SRC_VARIANT_CALL.finditer(c.nostr):
        c.add("legacy-variant-api", m.start(1), f"`{m.group(1)}` belongs to the legacy variant API, removed with the new DSL (AGP 9 default) and in AGP 10", None, sev)
    for m in re.finditer(r"\.\s*registerTransform\s*\(", c.nostr):
        c.add("register-transform", m.start())
    opt = c.p.builtin_off
    ksev = "warning" if (opt and c.p.target < 10) else "error"
    for rule, pid in (("kotlin-android-plugin", "org\\.jetbrains\\.kotlin\\.android"), ("kapt-plugin", "org\\.jetbrains\\.kotlin\\.kapt")):
        for m in re.finditer(_SRC_KOTLIN_APPLY % pid, c.code):
            c.add(rule, m.start(), None, None, ksev)


DETECTORS = [kotlin_plugins, legacy_api, removed_dsl, properties_file, wrapper, plugin_compat, ksp, convention_sources]


def scan_text(rel: str, text: str, kind: str, project: Project | None = None, disabled=frozenset(), only=frozenset()):
    c = Ctx(rel, text, kind, project or Project())
    for d in DETECTORS:
        d(c)
    ign = ignore_directives(text, c.kotlin) if kind in ("kotlin", "groovy", "source") else {}
    res = []
    for f in c.out:
        if f.rule in disabled or (only and f.rule not in only):
            continue
        s = ign.get(f.line, set())
        if "*" in s or f.rule in s:
            continue
        res.append(f)
    res.sort(key=lambda f: (f.line, f.col, f.rule))
    seen, uniq = set(), []
    for f in res:
        k = (f.rule, f.line, f.col)
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


def _read(full: str) -> str:
    with open(full, encoding="utf-8", errors="replace", newline="") as fh:
        return fh.read()


def load_project(root: str, files: list, target: int) -> Project:
    p = Project(target)
    texts = {}
    base = os.path.abspath(root) if os.path.isdir(root) else os.path.dirname(os.path.abspath(root))
    for full, rel in files:
        kind = kind_of(os.path.basename(full), rel)
        if kind in ("kotlin", "groovy"):
            texts[rel] = blank_comments(_read(full), kind == "kotlin")
    # gradle.properties and catalog from the scan root, even when only one build file was named
    props = os.path.join(base, "gradle.properties")
    if os.path.isfile(props):
        p.props = parse_properties(_read(props))
    for cand in (os.path.join(base, "gradle", "libs.versions.toml"),):
        if os.path.isfile(cand):
            p.catalog = parse_catalog(_read(cand))
    for full, rel in files:  # a catalog or properties file inside the scan wins when the root has none
        kind = kind_of(os.path.basename(full), rel)
        if kind == "catalog" and not p.catalog:
            p.catalog = parse_catalog(_read(full))
    p.detect_agp(texts)
    return p


def scan(root: str, ignore=(), disabled=(), only=(), target: int = 9) -> Result:
    files = list(discover(root, list(ignore)))
    p = load_project(root, files, target)
    r = Result(agp=p.agp, target=target)
    for full, rel in files:
        r.files_scanned += 1
        r.findings += scan_text(rel, _read(full), kind_of(os.path.basename(full), rel), p, frozenset(disabled), frozenset(only))
    return r


def apply_fixes(root: str, ignore=(), disabled=(), only=(), target: int = 9) -> tuple:
    """Rewrite files in place. Returns (files_changed, edits_applied)."""
    files, edits = 0, 0
    flist = list(discover(root, list(ignore)))
    p = load_project(root, flist, target)
    for full, rel in flist:
        text = _read(full)
        fs = [f for f in scan_text(rel, text, kind_of(os.path.basename(full), rel), p, frozenset(disabled), frozenset(only)) if f.edit]
        if not fs:
            continue
        last, n = None, 0
        for s, e, rep in sorted({f.edit for f in fs}, reverse=True):
            if last is not None and e > last:
                continue
            text = text[:s] + rep + text[e:]
            last = s
            n += 1
        with open(full, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        files += 1
        edits += n
    return files, edits
