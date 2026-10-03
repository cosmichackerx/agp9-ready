"""Rule catalogue. Every rule cites the Android Developers page it comes from."""
from __future__ import annotations

from dataclasses import dataclass

NOTES = "https://developer.android.com/build/releases/agp-9-0-0-release-notes"
ROADMAP = "https://developer.android.com/build/releases/gradle-plugin-roadmap"


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str  # default severity for --agp-target 9: error = documented to fail the build, warning = documented but detection is heuristic or an opt-out exists, note = information
    summary: str
    fix: str
    url: str
    fixable: bool = False
    oracle: bool = True  # True: reproduced against a real AGP in tests/oracle. False: taken from the documentation only


RULES: dict = {r.id: r for r in [
    Rule("kotlin-android-plugin", "error",
         "The `org.jetbrains.kotlin.android` plugin conflicts with built-in Kotlin, which AGP 9 enables by default",
         "Remove the plugin; AGP compiles Kotlin itself. To postpone, set `android.builtInKotlin=false` (removed in AGP 10).",
         NOTES + "#android-gradle-plugin-built-in-kotlin", True),
    Rule("kapt-plugin", "error",
         "The kapt plugin (`org.jetbrains.kotlin.kapt`) is incompatible with built-in Kotlin",
         "Move annotation processors to KSP, or apply `com.android.legacy-kapt` (same version as AGP) to the module that still needs kapt.",
         NOTES + "#android-gradle-plugin-built-in-kotlin"),
    Rule("legacy-variant-api", "error",
         "The legacy variant API (applicationVariants, libraryVariants, variantFilter, ...) is not available with the new DSL, the AGP 9 default",
         "Use `androidComponents { onVariants { ... } }` / `beforeVariants { ... }`.",
         NOTES + "#android-gradle-plugin-new-dsl"),
    Rule("legacy-extension-type", "error",
         "BaseExtension / AppExtension / BaseAppModuleExtension are no longer implemented by the `android` extension (ClassCastException in AGP 9)",
         "Use the public interfaces from `com.android.build.api.dsl` (ApplicationExtension, LibraryExtension, CommonExtension).",
         NOTES + "#android-gradle-plugin-new-dsl"),
    Rule("removed-dsl", "warning",
         "DSL member removed with the new DSL (dexOptions, deviceProvider, testServer, generatePureSplits, sdkDirectory, ndkDirectory, bootClasspath, adbExecutable, jni source sets, ...)",
         "See the replacement column in the AGP 9.0 release notes (for example `androidComponents.sdkComponents`, Gradle-managed devices).",
         NOTES + "#android-gradle-plugin-new-dsl"),
    Rule("density-splits", "error",
         "Density split APKs are removed in AGP 9",
         "Publish an Android App Bundle; Google Play serves density configuration splits.",
         NOTES + "#android-gradle-plugin-removed-features"),
    Rule("wear-app", "error",
         "Embedded Wear OS apps (`wearApp` configuration) are removed in AGP 9",
         "Publish the Wear OS app as its own app in Play.",
         NOTES + "#android-gradle-plugin-removed-features-wear-os"),
    Rule("set-dimension", "error",
         "ProductFlavor.setDimension(...) is not available in the Kotlin DSL (use the `dimension` property)",
         "Write `dimension = \"...\"`.",
         NOTES + "#android-gradle-plugin-removed-dsl", True),
    Rule("register-transform", "error",
         "BaseExtension.registerTransform (Transform API) is removed",
         "Use `AsmClassVisitorFactory` through `androidComponents.onVariants { it.instrumentation.transformClassesWith(...) }`.",
         NOTES + "#android-gradle-plugin-removed-apis"),
    Rule("enforced-property", "error",
         "AGP 9 stops the build when this Gradle property is set to true",
         "Delete the line (enableLegacyVariantApi) or enable the feature per module (aidl, renderscript) and then delete it.",
         NOTES + "#android-gradle-plugin-enforced-gradle-properties", True),
    Rule("removed-property", "warning",
         "This Gradle property was removed in AGP 9 and has no effect (AGP prints a warning)",
         "Delete the line.",
         NOTES + "#android-gradle-plugin-removed-gradle-properties", True),
    Rule("new-dsl-opt-out", "warning",
         "`android.newDsl=false` (or `android.newDsl.optOut`) keeps the legacy DSL; the opt-out is removed in AGP 10",
         "Migrate custom build logic and plugins to the new DSL, then delete the flag.",
         ROADMAP + "#agp-10-removed"),
    Rule("built-in-kotlin-opt-out", "warning",
         "`android.builtInKotlin=false` keeps the standalone Kotlin plugin; the opt-out is removed in AGP 10",
         "Migrate to built-in Kotlin (remove `kotlin-android`), then delete the flag. Modules without Kotlin: `android { enableKotlin = false }`.",
         ROADMAP + "#agp-10-opt-out-kotlin"),
    Rule("old-default-kept", "note",
         "This property pins the AGP 8.13 behaviour; AGP 9 flipped its default",
         "Adopt the new default when you can, then delete the line.",
         NOTES + "#android-gradle-plugin-behavior-changes"),
    Rule("gradle-wrapper-too-old", "warning",
         "AGP 9.0 needs Gradle 9.1.0 or newer",
         "Run `./gradlew wrapper --gradle-version <9.1.0 or newer>`.",
         NOTES + "#compatibility"),
    Rule("plugin-opt-out-needed", "warning",
         "This third-party plugin version is reported to need an AGP 9 opt-out flag",
         "Upgrade the plugin to a version that supports AGP 9, or set the listed flag(s) temporarily.",
         "https://github.com/jetbrains/skills/blob/HEAD/kotlin-tooling-agp9-migration/references/PLUGIN-COMPATIBILITY.md", oracle=False),
    Rule("ksp-version", "warning",
         "This KSP version predates AGP 9 support (Android's AGP 9 upgrade skill asks for KSP 2.3.6 or newer)",
         "Upgrade the `com.google.devtools.ksp` plugin.",
         "https://developer.android.com/agents/skills/build/agp/agp-9-upgrade/skill", oracle=False),
]}
