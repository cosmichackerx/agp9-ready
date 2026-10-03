import json
import os

import pytest

from agp9_ready.cli import main
from agp9_ready.scan import Project, apply_fixes, parse_catalog, scan, scan_text, version_lt


def rules(text, kind="kotlin", project=None, rel="app/build.gradle.kts"):
    return [(f.rule, f.severity) for f in scan_text(rel, text, kind, project)]


def write(root, files):
    for rel, text in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", newline="") as fh:
            fh.write(text)


def test_kotlin_android_plugin_forms():
    for line in ['id("org.jetbrains.kotlin.android")', 'id "org.jetbrains.kotlin.android" version "2.3.0"', "id 'kotlin-android'",
                 'kotlin("android")', "apply plugin: 'kotlin-android'"]:
        assert ("kotlin-android-plugin", "error") in rules("plugins { %s }\n" % line, "groovy"), line


def test_apply_false_and_comments_are_ignored():
    assert rules('plugins {\n    id("org.jetbrains.kotlin.android") version "2.3.0" apply false\n}\n') == []
    assert rules('plugins {\n    // id("org.jetbrains.kotlin.android")\n}\n') == []
    assert rules('val s = "id(\\"org.jetbrains.kotlin.android\\")"\n') == []


def test_catalog_alias_resolves_to_plugin_id():
    p = Project()
    p.catalog = parse_catalog('[plugins]\nkotlin-android = { id = "org.jetbrains.kotlin.android", version = "2.3.0" }\nother = { id = "x.y" }\n')
    assert ("kotlin-android-plugin", "error") in rules("plugins { alias(libs.plugins.kotlin.android) }\n", project=p)
    assert rules("plugins { alias(libs.plugins.other) }\n", project=p) == []


def test_opt_out_downgrades_and_target_10_escalates():
    p = Project()
    p.props = {"android.builtInKotlin": ("false", 0, 0, 0)}
    assert rules('plugins { id("org.jetbrains.kotlin.android") }\n', project=p) == [("kotlin-android-plugin", "warning")]
    p.target = 10
    assert rules('plugins { id("org.jetbrains.kotlin.android") }\n', project=p) == [("kotlin-android-plugin", "error")]


def test_kapt_plugin():
    assert ("kapt-plugin", "error") in rules('plugins { id("org.jetbrains.kotlin.kapt") }\n')
    assert ("kapt-plugin", "error") in rules('plugins { kotlin("kapt") }\n')
    assert rules('plugins { id("com.android.legacy-kapt") version "9.0.1" }\n') == []


def test_legacy_variant_api_and_negative():
    assert ("legacy-variant-api", "error") in rules("android.applicationVariants.all { v -> println(v.name) }\n", "groovy")
    assert ("legacy-variant-api", "error") in rules("android { variantFilter { ignore = true } }\n", "groovy")
    assert rules('val applicationVariantsX = 1\nprintln("applicationVariants")\n') == []
    assert rules("androidComponents { onVariants { } }\n") == []


def test_new_dsl_opt_out_makes_variant_api_a_warning():
    p = Project()
    p.props = {"android.newDsl": ("false", 0, 0, 0)}
    assert rules("android.applicationVariants.all { }\n", "groovy", p) == [("legacy-variant-api", "warning")]


def test_removed_dsl_only_in_android_block_or_dotted():
    assert ("removed-dsl", "warning") in rules("android {\n    dexOptions { javaMaxHeapSize = '2g' }\n}\n", "groovy")
    assert ("removed-dsl", "warning") in rules("println android.sdkDirectory\n", "groovy")
    assert ("removed-dsl", "warning") in rules("android {\n    sourceSets { main { jni.srcDirs = ['x'] } }\n}\n", "groovy")
    assert rules("tasks.register('t') { def dexOptions = 1 }\n", "groovy") == []


def test_density_splits_and_wear_app():
    assert ("density-splits", "error") in rules("android {\n    splits {\n        density { enable true }\n    }\n}\n", "groovy")
    assert rules("android {\n    splits {\n        abi { enable true }\n    }\n}\n", "groovy") == []
    assert ("wear-app", "error") in rules("dependencies { wearApp 'x:wear:1.0' }\n", "groovy")


def test_legacy_extension_type():
    assert ("legacy-extension-type", "error") in rules("import com.android.build.gradle.BaseExtension\n", "kotlin")
    assert rules("import com.android.build.api.dsl.ApplicationExtension\n") == []


def test_set_dimension_kotlin_only_and_fix(tmp_path):
    assert rules("android { productFlavors { create(\"foo\") { setDimension(\"a\") } } }\n") == [("set-dimension", "error")]
    assert rules("android {\n    productFlavors { foo { setDimension 'a' } }\n}\n", "groovy") == []  # still works through the Groovy property setter
    write(str(tmp_path), {"app/build.gradle.kts": "android { productFlavors { create(\"foo\") { setDimension(\"a\") } } }\n"})
    assert apply_fixes(str(tmp_path)) == (1, 1)
    assert 'create("foo") { dimension = "a" }' in (tmp_path / "app/build.gradle.kts").read_text()


def test_properties_rules():
    props = ("android.enableLegacyVariantApi=true\nandroid.defaults.buildfeatures.aidl=false\nandroid.defaults.buildfeatures.renderscript=true\n"
             "android.r8.integratedResourceShrinking=true\nandroid.newDsl=false\nandroid.builtInKotlin=false\nandroid.newDsl.optOut=:lib\n"
             "android.useAndroidx=true\nandroid.uniquePackageNames=false\n")
    fs = scan_text("gradle.properties", props, "props")
    assert [f.rule for f in fs] == ["enforced-property", "removed-property", "enforced-property", "removed-property", "new-dsl-opt-out",
                                    "built-in-kotlin-opt-out", "new-dsl-opt-out", "old-default-kept"]
    assert [f.severity for f in fs][:4] == ["error", "warning", "error", "warning"]
    assert [f.edit is not None for f in fs] == [True, True, False, True, False, False, False, False]


def test_target_10_makes_opt_outs_errors():
    p = Project(10)
    got = {f.rule: f.severity for f in scan_text("gradle.properties", "android.newDsl=false\nandroid.builtInKotlin=false\n", "props", p)}
    assert got == {"new-dsl-opt-out": "error", "built-in-kotlin-opt-out": "error"}


def test_wrapper_version():
    t = "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.13-bin.zip\n"
    assert [(f.rule, f.severity) for f in scan_text("gradle/wrapper/gradle-wrapper.properties", t, "wrapper")] == [("gradle-wrapper-too-old", "warning")]
    p = Project()
    p.agp = "9.0.1"
    assert [f.severity for f in scan_text("w.properties", t, "wrapper", p)] == ["error"]
    ok = t.replace("8.13", "9.1.0")
    assert scan_text("w.properties", ok, "wrapper") == []


def test_plugin_table_and_flags_set():
    cat = '[versions]\ndetekt = "1.23.8"\n[plugins]\ndetekt = { id = "io.gitlab.arturbosch.detekt", version.ref = "detekt" }\nsq = { id = "app.cash.sqldelight", version = "2.0.0" }\n'
    p = Project()
    p.catalog = parse_catalog(cat)
    got = [(f.rule, f.severity) for f in scan_text("gradle/libs.versions.toml", cat, "catalog", p)]
    assert got == [("plugin-opt-out-needed", "warning"), ("plugin-opt-out-needed", "note")]
    p.props = {"android.newDsl": ("false", 0, 0, 0), "android.builtInKotlin": ("false", 0, 0, 0), "android.disallowKotlinSourceSets": ("false", 0, 0, 0)}
    assert scan_text("gradle/libs.versions.toml", cat, "catalog", p) == []
    new = cat.replace("1.23.8", "2.0.0")
    p.catalog = parse_catalog(new)
    p.props = {}
    assert [f.rule for f in scan_text("gradle/libs.versions.toml", new, "catalog", p)] == ["plugin-opt-out-needed"]  # sqldelight only


def test_ksp_versions():
    for ver, flagged in [("2.2.10-2.0.2", True), ("2.3.5", True), ("2.3.6", False), ("2.4.0", False)]:
        text = '[plugins]\nksp = { id = "com.google.devtools.ksp", version = "%s" }\n' % ver
        p = Project()
        p.catalog = parse_catalog(text)
        assert bool(scan_text("gradle/libs.versions.toml", text, "catalog", p)) == flagged, ver


def test_version_lt():
    assert version_lt("1.4.9", "1.5.0") and not version_lt("1.5.0", "1.5.0") and not version_lt("2.0.0-alpha1", "2.0.0")
    assert version_lt("0.10.7", "0.10.8")


def test_agp_detection(tmp_path):
    write(str(tmp_path), {"gradle/libs.versions.toml": '[versions]\nagp = "9.1.0"\n', "app/build.gradle.kts": "plugins {}\n"})
    assert scan(str(tmp_path)).agp == "9.1.0"
    t2 = tmp_path / "b"
    write(str(t2), {"build.gradle": "plugins { id 'com.android.application' version '8.13.2' apply false }\n"})
    assert scan(str(t2)).agp == "8.13.2"
    t3 = tmp_path / "c"
    write(str(t3), {"build.gradle": "buildscript { dependencies { classpath 'com.android.tools.build:gradle:8.5.0' } }\n"})
    assert scan(str(t3)).agp == "8.5.0"


def test_ignore_directive():
    assert rules('plugins {\n    id("org.jetbrains.kotlin.android") // agp9-ready: ignore kotlin-android-plugin\n}\n') == []


def test_fix_removes_plugin_line_only_without_opt_out(tmp_path):
    files = {"app/build.gradle.kts": 'plugins {\n    id("com.android.application")\n    id("org.jetbrains.kotlin.android")\n}\n', "gradle.properties": "android.enableLegacyVariantApi=true\nandroid.x=1\n"}
    write(str(tmp_path), files)
    assert apply_fixes(str(tmp_path)) == (2, 2)  # plugin line + enableLegacyVariantApi
    assert (tmp_path / "app/build.gradle.kts").read_text() == 'plugins {\n    id("com.android.application")\n}\n'
    assert (tmp_path / "gradle.properties").read_text() == "android.x=1\n"
    assert not [f for f in scan(str(tmp_path)).findings if f.severity == "error"]
    t2 = tmp_path / "optout"
    write(str(t2), {**files, "gradle.properties": "android.builtInKotlin=false\n"})
    assert apply_fixes(str(t2)) == (0, 0)


def test_cli_outputs_and_exit_codes(tmp_path, capsys):
    write(str(tmp_path), {"gradle.properties": "android.enableLegacyVariantApi=true\nandroid.newDsl=false\n"})
    assert main([str(tmp_path)]) == 1
    capsys.readouterr()
    assert main([str(tmp_path), "--only", "new-dsl-opt-out"]) == 0
    assert main([str(tmp_path), "--agp-target", "10", "--only", "new-dsl-opt-out"]) == 1
    capsys.readouterr()
    main([str(tmp_path), "-f", "json", "--fail-on", "never"])
    j = json.loads(capsys.readouterr().out)
    assert j["summary"]["error"] == 1 and j["agpTarget"] == 9
    main([str(tmp_path), "-f", "sarif", "--fail-on", "never"])
    s = json.loads(capsys.readouterr().out)
    assert s["version"] == "2.1.0" and s["runs"][0]["results"][0]["ruleId"] == "enforced-property"
    main([str(tmp_path), "-f", "github", "--fail-on", "never"])
    assert capsys.readouterr().out.startswith("::error file=gradle.properties,line=1")
    assert main([str(tmp_path), "--only", "nope"]) == 2
    assert main(["--list-rules"]) == 0


def test_every_rule_has_a_url_with_a_fragment_or_page():
    from agp9_ready.rules import RULES
    for r in RULES.values():
        assert r.url.startswith("https://") and r.severity in ("error", "warning", "note")


def test_kotlin_options_in_android_block():
    assert ("kotlin-options", "error") in rules("android {\n    kotlinOptions {\n        jvmTarget = \"17\"\n    }\n}\n")
    assert ("kotlin-options", "error") in rules("android { kotlinOptions { jvmTarget = '17' } }", "groovy", rel="app/build.gradle")
    assert ("kotlin-options", "error") in rules("android.kotlinOptions { jvmTarget = '17' }", "groovy", rel="app/build.gradle")
    # not in an android block, or already the new DSL
    assert rules("tasks.withType<KotlinCompile> { kotlinOptions { jvmTarget = \"17\" } }") == []
    assert rules("kotlin { compilerOptions { jvmTarget.set(JvmTarget.JVM_17) } }") == []
    assert rules("// android { kotlinOptions { } }\n") == []


def test_kotlin_options_is_a_warning_with_the_builtin_kotlin_opt_out():
    p = Project()
    p.props = {"android.builtInKotlin": ("false", 0, 0, 0)}
    assert ("kotlin-options", "warning") in rules("android { kotlinOptions { } }", project=p)
    p.target = 10
    assert ("kotlin-options", "error") in rules("android { kotlinOptions { } }", project=p)


def test_catalog_table_sections_and_dotted_keys():
    cat = parse_catalog(
        '[versions]\nkotlinv = "2.3.0"\n\n[plugins.kotlin-android]\nid = "org.jetbrains.kotlin.android"\nversion.ref = "kotlinv"\n\n'
        '[plugins]\nkapt.id = "org.jetbrains.kotlin.kapt"\nkapt.version = "2.3.0"\nagp = { id = "com.android.application", version = "9.0.0" }\n\n'
        '[libraries.core]\nmodule = "androidx.core:core-ktx"\nversion = "1.15.0"\n')
    assert cat["plugins"]["kotlin-android"]["id"] == "org.jetbrains.kotlin.android" and cat["plugins"]["kotlin-android"]["version.ref"] == "kotlinv"
    assert cat["plugins"]["kapt"]["id"] == "org.jetbrains.kotlin.kapt" and cat["plugins"]["kapt"]["version"] == "2.3.0"
    assert cat["plugins"]["agp"]["id"] == "com.android.application"
    assert cat["libraries"]["core"]["module"] == "androidx.core:core-ktx"


def test_alias_of_a_table_form_catalog_plugin_is_found(tmp_path):
    write(str(tmp_path), {
        "gradle/libs.versions.toml": '[plugins.kotlin-android]\nid = "org.jetbrains.kotlin.android"\nversion = "2.3.0"\n[plugins.kapt]\nid = "org.jetbrains.kotlin.kapt"\nversion = "2.3.0"\n',
        "app/build.gradle.kts": "plugins {\n    alias(libs.plugins.kotlin.android)\n    alias(libs.plugins.kapt)\n}\n"})
    got = sorted(f.rule for f in scan(str(tmp_path)).findings)
    assert got == ["kapt-plugin", "kotlin-android-plugin"], got
