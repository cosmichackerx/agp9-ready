"""buildSrc / build-logic source scanning."""
import os

from agp9_ready.cli import main
from agp9_ready.scan import Project, kind_of, scan, scan_text

KT = "buildSrc/src/main/kotlin/Conv.kt"


def hits(text, rel=KT, project=None):
    return [(f.rule, f.severity, f.line) for f in scan_text(rel, text, "source", project)]


def write(root, files):
    for rel, text in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", newline="") as fh:
            fh.write(text)


def test_only_convention_dirs_are_scanned():
    assert kind_of("Conv.kt", "buildSrc/src/main/kotlin/Conv.kt") == "source"
    assert kind_of("Conv.java", "build-logic/convention/src/main/java/Conv.java") == "source"
    assert kind_of("Conv.groovy", "gradle/buildLogic/src/Conv.groovy") == "source"
    assert kind_of("Main.kt", "app/src/main/kotlin/Main.kt") is None
    assert kind_of("Conv.kt") is None


def test_imports_and_qualified_names():
    assert hits("import com.android.build.gradle.BaseExtension\n") == [("legacy-extension-type", "error", 1)]
    assert hits("val e = p.extensions.getByType(com.android.build.gradle.LibraryExtension::class.java)\n") == [("legacy-extension-type", "error", 1)]
    assert hits("import com.android.build.gradle.internal.dsl.BaseAppModuleExtension\n") == [("legacy-extension-type", "error", 1)]


def test_new_dsl_types_are_fine():
    assert hits("import com.android.build.api.dsl.ApplicationExtension\nimport com.android.build.api.variant.AndroidComponentsExtension\n") == []


def test_star_import_makes_bare_names_count():
    out = hits("import com.android.build.gradle.*\nfun f(x: Any) = x as BaseExtension\n")
    assert out == [("legacy-extension-type", "error", 2)]
    assert hits("fun f(x: Any) = x as BaseExtension\n") == []  # no import: could be anything


def test_variant_calls_and_types():
    assert ("legacy-variant-api", "error", 1) in hits("android.applicationVariants.all { }\n")
    assert ("legacy-variant-api", "error", 1) in hits("import com.android.build.gradle.api.ApplicationVariant\n")
    assert ("register-transform", "error", 1) in hits("android.registerTransform(t)\n")
    assert hits("val applicationVariants = 3\n") == []  # not a member call


def test_kotlin_plugin_applied_by_id():
    assert hits('p.pluginManager.apply("org.jetbrains.kotlin.android")\n') == [("kotlin-android-plugin", "error", 1)]
    assert hits('apply(plugin = "org.jetbrains.kotlin.kapt")\n') == [("kapt-plugin", "error", 1)]
    assert hits('p.pluginManager.withPlugin("org.jetbrains.kotlin.android") { }\n') == []  # only reacts to the plugin


def test_comments_and_strings_do_not_match():
    assert hits("// import com.android.build.gradle.BaseExtension\n/* android.applicationVariants */\n") == []
    assert hits('val s = "x.applicationVariants.all"\n') == []


def test_opt_out_makes_them_warnings():
    p = Project()
    p.props = {"android.newDsl": ("false", 0, 0, 0), "android.builtInKotlin": ("false", 0, 0, 0)}
    out = hits('import com.android.build.gradle.BaseExtension\np.pluginManager.apply("org.jetbrains.kotlin.android")\n', project=p)
    assert out == [("legacy-extension-type", "warning", 1), ("kotlin-android-plugin", "warning", 2)]
    p.target = 10
    assert all(sev == "error" for _, sev, _ in hits('import com.android.build.gradle.BaseExtension\n', project=p))


def test_ignore_comment_and_java_files():
    assert hits("// agp9-ready: ignore legacy-extension-type\nimport com.android.build.gradle.BaseExtension\n") == []
    assert hits("import com.android.build.gradle.BaseExtension;\n", rel="build-logic/src/Conv.java") == [("legacy-extension-type", "error", 1)]


def test_scan_walks_buildsrc_and_ignore_glob(tmp_path):
    write(str(tmp_path), {"app/build.gradle": "plugins { id 'com.android.application' version '9.0.0' }\n",
                          KT: "import com.android.build.gradle.BaseExtension\n",
                          "app/src/main/kotlin/App.kt": "import com.android.build.gradle.BaseExtension\n"})
    r = scan(str(tmp_path))
    assert [(f.rule, f.file) for f in r.findings] == [("legacy-extension-type", KT)]
    assert scan(str(tmp_path), ignore=["buildSrc/**"]).findings == []


def test_cli_lists_the_source_finding(tmp_path, capsys):
    write(str(tmp_path), {KT: "import com.android.build.gradle.BaseExtension\n"})
    assert main([str(tmp_path), "-f", "json"]) == 1
    assert KT in capsys.readouterr().out
