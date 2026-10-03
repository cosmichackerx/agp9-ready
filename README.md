# agp9-ready

**Find what Android Gradle Plugin 9 (and 10) breaks in your Gradle files, without running Gradle.** A zero-dependency static scanner
(Python 3.9+) for `build.gradle(.kts)`, `gradle.properties`, `libs.versions.toml` and `gradle-wrapper.properties`: the
`org.jetbrains.kotlin.android` and **kapt** plugins that conflict with **built-in Kotlin**, the **legacy variant API**
(`applicationVariants`, `variantFilter`), `BaseExtension` casts, removed DSL members, `android.newDsl=false` / `android.builtInKotlin=false`
opt-outs (removed in **AGP 10**), removed `gradle.properties` flags, a Gradle wrapper older than 9.1.0, and third-party plugin versions that
are reported to need an opt-out. It can **fix the mechanical cases** (`--fix`), emits **SARIF** and GitHub annotations, and ships as a
**GitHub Action**.

[![CI](https://github.com/cosmichackerx/agp9-ready/actions/workflows/ci.yml/badge.svg)](https://github.com/cosmichackerx/agp9-ready/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/cosmichackerx/agp9-ready?sort=semver)](https://github.com/cosmichackerx/agp9-ready/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Why a static scanner? The AGP 9 upgrade assistant in Android Studio edits your project, but it is an IDE feature; it cannot run in CI and it
does not tell a team lead how big the migration is across 40 modules. Gradle itself only complains about the code paths a build executes, and
the first failure hides the rest (`kotlin-android` aborts the build before you ever see the variant API errors). This reads the files and lists
everything at once, with the Android Developers page each finding comes from.

## Install and run

```
pipx install git+https://github.com/cosmichackerx/agp9-ready      # or: pip install git+https://github.com/cosmichackerx/agp9-ready
agp9-ready .                       # scan the current project (target AGP 9)
agp9-ready . --agp-target 10       # also treat the temporary opt-outs as errors
agp9-ready . --fix                 # apply the mechanical fixes, then report what is left
agp9-ready . -f sarif -o agp9.sarif --fail-on never
```

From a checkout without installing: `PYTHONPATH=src python -m agp9_ready .`

## Example output

Real output for [`tests/fixtures/legacy-app`](tests/fixtures/legacy-app) (an AGP 8.13.2 project):

```
app/build.gradle.kts
      3  error   kotlin-android-plugin    The `org.jetbrains.kotlin.android` plugin conflicts with built-in Kotlin, which AGP 9 enables by default
         > alias(libs.plugins.kotlin.android)
      4  error   kapt-plugin              The kapt plugin (`org.jetbrains.kotlin.kapt`) is incompatible with built-in Kotlin
         > id("org.jetbrains.kotlin.kapt")
      9  warning removed-dsl              `dexOptions` is removed with the new DSL
         > dexOptions { javaMaxHeapSize = "2g" }
     10  warning legacy-variant-api       `applicationVariants` belongs to the legacy variant API, removed with the new DSL (AGP 9 default) and in AGP 10
         > applicationVariants.all { println(name) }
     11  error   density-splits           Density split APKs are removed in AGP 9
         > splits { density { isEnable = true } }

gradle.properties
      1  error   enforced-property        `android.enableLegacyVariantApi=true` makes AGP 9 stop the build
         > android.enableLegacyVariantApi=true
      2  warning new-dsl-opt-out          `android.newDsl=false` (or `android.newDsl.optOut`) keeps the legacy DSL; the opt-out is removed in AGP 10
         > android.newDsl=false
      3  warning removed-property         `android.defaults.buildfeatures.aidl` was removed in AGP 9 and has no effect; delete it
         > android.defaults.buildfeatures.aidl=false
      4  note    old-default-kept         `android.useAndroidx=false` keeps the AGP 8.13 behaviour; AGP 9 changed the default
         > android.useAndroidx=false

gradle/libs.versions.toml
      8  warning ksp-version              KSP `2.2.10-2.0.2` uses the old `<kotlin>-<ksp>` scheme; Android's AGP 9 upgrade skill asks for KSP 2.3.6 or newer
         > ksp = { id = "com.google.devtools.ksp", version.ref = "ksp" }
      9  warning plugin-opt-out-needed    `io.gitlab.arturbosch.detekt` 1.23.8 is reported to need `android.newDsl=false` and `android.builtInKotlin=false` on AGP 9 (fixed in 2.0.0)
         > detekt = { id = "io.gitlab.arturbosch.detekt", version.ref = "detekt" }

3 file(s) scanned for AGP 9. AGP detected: 8.13.2. 4 error, 6 warning, 1 note; 3 auto-fixable with --fix.
```

## Rules (18)

`agp9-ready --list-rules` prints them. **oracle** = reproduced against a real AGP 9.4.1 build in CI; **docs** = taken from the Android Developers
pages or a third-party compatibility table only.

| Rule | Severity | Checked | What it finds |
|---|---|---|---|
| `kotlin-android-plugin` | error¹ | oracle, `--fix` | `org.jetbrains.kotlin.android`, `kotlin-android`, `kotlin("android")`, `alias(libs.plugins…)` that resolves to it (not `apply false`) |
| `kapt-plugin` | error¹ | oracle | `org.jetbrains.kotlin.kapt`, `kotlin-kapt`, `kotlin("kapt")` |
| `legacy-variant-api` | error² | oracle | `applicationVariants`, `libraryVariants`, `testVariants`, `unitTestVariants`, `variantFilter`, `registerJavaGeneratingTask`, `registerResGeneratingTask` |
| `legacy-extension-type` | error² | oracle | `BaseExtension`, `AppExtension`, `BaseAppModuleExtension`, `import com.android.build.gradle.LibraryExtension` … |
| `kotlin-options` | error¹ | oracle | `android { kotlinOptions { } }` ("Could not find method kotlinOptions()" with built-in Kotlin); a warning while `android.builtInKotlin=false` keeps the old DSL working (the oracle shows it builds silently there) |
| `removed-dsl` | warning | oracle (dexOptions, sdkDirectory), docs (the rest) | `dexOptions`, `deviceProvider`, `testServer`, `generatePureSplits`, `jni` source sets, `android.sdkDirectory/ndkDirectory/bootClasspath/adbExecutable` |
| `density-splits` | error | oracle | `splits { density { … } }` |
| `wear-app` | error | oracle | `wearApp` configuration, `wearAppConfigurationName` |
| `set-dimension` | error | oracle, `--fix` | Kotlin DSL `setDimension("x")` (Groovy still works through the property setter, so it is not flagged) |
| `register-transform` | error | oracle | `registerTransform(...)` |
| `enforced-property` | error | oracle, `--fix` for one | `android.enableLegacyVariantApi=true`, `android.defaults.buildfeatures.aidl=true`, `…renderscript=true` (AGP 9.4.1 fails the build) |
| `removed-property` | warning | oracle, `--fix` | the same flags with another value, and `android.r8.integratedResourceShrinking`, `android.enableNewResourceShrinker.preciseShrinking` (AGP prints "deprecated, no effect") |
| `new-dsl-opt-out` | warning³ | oracle | `android.newDsl=false`, `android.newDsl.optOut=…` |
| `built-in-kotlin-opt-out` | warning³ | oracle | `android.builtInKotlin=false` |
| `old-default-kept` | note | oracle (accepted silently) | properties that pin the AGP 8.13 default which AGP 9 flipped (`android.useAndroidx=false`, `android.uniquePackageNames=false`, …) |
| `gradle-wrapper-too-old` | warning / error⁴ | docs | Gradle wrapper below 9.1.0 |
| `plugin-opt-out-needed` | warning / note | docs | detekt < 2.0.0, ktlint, sqldelight, protobuf, paparazzi, apollo < 4.4.0, baselineprofile < 1.5.0 … (table in `scan.py`) |
| `ksp-version` | warning | docs | KSP below 2.3.6 or in the old `<kotlin>-<ksp>` version scheme |

¹ warning when `android.builtInKotlin=false` opts out (AGP 9), error with `--agp-target 10`. ² warning when `android.newDsl=false` opts out.
³ error with `--agp-target 10`. ⁴ error when the detected AGP is already 9 or newer.

Silence a line with a comment: `// agp9-ready: ignore kapt-plugin` (or `ignore` alone for every rule on that line).

## Fixes

`--fix` only does edits that cannot change what the build means, and prints what is left:

* remove the `kotlin-android` plugin line (skipped when `android.builtInKotlin=false`, and for `apply false` lines);
* delete `android.enableLegacyVariantApi`, `android.r8.integratedResourceShrinking`, `android.enableNewResourceShrinker.preciseShrinking`, and the aidl / renderscript defaults when they are `false`;
* `setDimension("x")` → `dimension = "x"` (Kotlin DSL).

Not fixed on purpose: kapt (needs a KSP decision), the variant API (needs a design), aidl / renderscript `=true` (the feature must be switched on per module first).

## GitHub Action

```yaml
- uses: actions/checkout@v7
- uses: cosmichackerx/agp9-ready@v0.2.0
  with:
    fail-on: error          # error | warning | never
    agp-target: "9"         # "10" makes the opt-out flags errors
    sarif-file: agp9.sarif  # optional; upload with github/codeql-action/upload-sarif
```

Pull requests only, reporting what the PR introduces and keeping one comment up to date (needs `fetch-depth: 0` and `pull-requests: write`; the comment is skipped for fork PRs, whose token is read-only, and a missing permission never fails the job):

```yaml
permissions: { contents: read, pull-requests: write }
steps:
  - uses: actions/checkout@v7
    with: { fetch-depth: 0 }
  - uses: cosmichackerx/agp9-ready@v0.2.0
    with:
      pr-mode: "true"      # base = the pull request base commit; or pass `base:`
      comment: "true"
```

## PR mode: only what a pull request introduces

A legacy build can have hundreds of findings. `--base REF` scans the Gradle files at the merge base of `REF` and `HEAD`, scans the working tree, and reports only the difference. Findings are matched by rule, file and source line text, not by line number, so inserting lines above old code or renaming a file does not make old findings look new.

```
agp9-ready . --base origin/main
# 3 file(s) scanned for AGP 9. AGP detected: 9.0.0. 0 error, 1 warning, 0 note introduced since origin/main; 0 auto-fixable with --fix. Not shown: 3 that were already there; 0 resolved.
```

Needs git history (`actions/checkout` with `fetch-depth: 0`); exit code 2 with a hint if the base is missing. Cannot be combined with `--fix`.

`action.yml` is Marketplace-ready (name, description, branding, inputs). I have **not** checked that the name is unique on the Marketplace, and publishing it there is a manual step in the release UI.

## Convention plugin sources (buildSrc / build-logic)

Most real `BaseExtension` and `applicationVariants` uses live in convention plugins, not in `build.gradle`. Source files (`.kt`, `.java`, `.groovy`) below a `buildSrc`, `build-logic` or `buildLogic` directory are checked for:

* `com.android.build.gradle.{BaseExtension, AppExtension, LibraryExtension, TestExtension, internal.dsl.BaseAppModuleExtension}` as an import or a qualified name (`legacy-extension-type`); bare names only count when the file has `import com.android.build.gradle.*`;
* `com.android.build.gradle.api.*Variant` types and `.applicationVariants`, `.libraryVariants`, `.testVariants`, `.unitTestVariants`, `.registerJavaGeneratingTask`, `.registerResGeneratingTask` calls (`legacy-variant-api`), and `.registerTransform(` (`register-transform`);
* `apply("org.jetbrains.kotlin.android")` / `apply(plugin = "...kapt")` (`kotlin-android-plugin`, `kapt-plugin`); `withPlugin(...)` only reacts to a plugin and is not reported.

The same severities and `android.newDsl` / `android.builtInKotlin` opt-out handling apply as in build scripts. Three oracle cases generate a real buildSrc plugin and run it on AGP 9.4.1 (the `BaseExtension` lookup and the `kotlin-android` apply fail the build; a plugin that uses `com.android.build.api.dsl.ApplicationExtension` passes). Only a text scan: no type resolution, so a class that merely shares a name is not understood.

## Docs watch (keeps the rule table honest)

`.github/workflows/agp-watch.yml` runs every Monday (and on demand). `scripts/watch/watch_agp_docs.py` reads the Android Gradle plugin
[roadmap](https://developer.android.com/build/releases/gradle-plugin-roadmap) and the release notes of every AGP 9.x (and 10.x, once it exists),
and opens **one issue** (label `agp-watch`, deduplicated by a key in the title) when

- a release-notes page appears that was not there before (a new minor, or AGP 10), or a page has a section that is not in `scripts/watch/known_sections.txt`;
- a roadmap heading changes its title (the dates live there, for example "AGP 10.0 (late 2026)");
- a rule cites an anchor that no longer exists in the page;
- the 9.0.0 notes name an `android.*` Gradle property that no rule mentions and `scripts/watch/triaged.txt` does not explain.

`known_sections.txt` is the list of headings that existed **when the watcher started**; it means "known", not "reviewed". Headings are a proxy, because the
pages do not mark which items affect build files. The first live run (2026-10-03) found nothing new; the issue path was exercised with a manual run with `self_test` (it opens one real issue, which I closed).

## How it is verified

`tests/oracle/run_oracle.py` generates a minimal Android app per construct, runs `gradle help --warning-mode all` with **AGP 9.4.1 on Gradle 9.8.0**, and
checks that the build outcome (fails / warns / passes) matches the expectation **and** that agp9-ready reports the rule. 27 cases, 0 disagreements at
the time of release (CI job *oracle*). The Gradle messages it saw, abridged:

* `kotlin-android`: *"The 'org.jetbrains.kotlin.android' plugin is no longer required for Kotlin support since AGP 9.0. Solution: Remove the plugin"*
* `applicationVariants`: *"Could not get unknown property 'applicationVariants' for object of type com.android.build.gradle.internal.dsl…"*; `variantFilter`, `dexOptions`, `registerTransform`, `density`: *"Could not find method …"*
* `BaseExtension`: *"Extension of type 'BaseExtension' does not exist"*
* `android.enableLegacyVariantApi=true`, `…buildfeatures.aidl=true`: the build fails while applying the plugin; with other values it prints *"The option … is deprecated"*
* `android.newDsl=false`, `android.builtInKotlin=false`: *"The option setting … is deprecated"* (a warning, so these are the AGP 10 blockers, not AGP 9 blockers)

One place where the documentation and the tool disagree: the AGP 9.0 release notes say AGP *throws an error* for `android.r8.integratedResourceShrinking` and
`android.enableNewResourceShrinker.preciseShrinking`. AGP 9.4.1 only prints a deprecation warning, so they are `warning` here. Rules marked **docs** have no
oracle case (wrapper version, the third-party plugin table, KSP versions): they are as accurate as the page or table they cite, snapshot 2026-10-03.

## How it relates to other tools

* **Android Studio AGP Upgrade Assistant**: edits the project from inside the IDE and understands more build logic than this tool does. Use it to do the upgrade; use this to find out what is left, in CI and across many modules.
* **AGP 9 migration "skills"** (Android, JetBrains): instructions for AI agents. The plugin table here is derived from JetBrains' compatibility list.
* **[aargrade](https://github.com/gay00ung/aargrade)**: a heavier CLI (doctor / plan / upgrade, builds your project and checks AARs). This tool is a read-only scanner with no build step.
* **[gradle10-ready](https://github.com/cosmichackerx/gradle10-ready)**: the same idea for Gradle 10 removals (space-assignment, multi-string dependencies, Kotlin DSL delegates). The two do not overlap.

## Limitations (read these)

* Static text matching with comment/string blanking, not a Groovy/Kotlin parser. Computed plugin ids (`id(pluginName)`) and dynamic versions are not resolved. Besides `*.gradle`, `*.gradle.kts`, `gradle.properties`, `*.versions.toml` and the wrapper properties, `.kt`, `.java` and `.groovy` sources **under a directory named `buildSrc`, `build-logic` or `buildLogic`** get a small set of checks (see "Convention plugin sources"); convention code in other directories, and anything those checks do not look for (for example `project.extensions.findByName("android") as BaseExtension` through a type alias), is not scanned.
* Version catalogs are read line by line (one entry per line); multi-line TOML tables are skipped.
* The AGP version comes from the catalog, a literal plugin version or a `classpath` coordinate. If none is found the report says so.
* The plugin compatibility table is a snapshot of a third-party list and will go stale.
* `removed-dsl` matches names; it can be wrong for a custom object that happens to have a member with the same name (use the ignore comment).
* Only AGP 9.4.1 was used as the oracle. Behaviour of 9.0 to 9.3 is assumed to match.

## Roadmap

See the [issues](https://github.com/cosmichackerx/agp9-ready/issues): a watcher for the AGP release-notes pages, a pre-commit hook, multi-line catalog tables, `kotlinOptions` migration, AGP 10 task-access rules.

## Related tools

Small, independent tools by the same author, for build and CI hygiene and for migrations with a deadline. Each works on its own; none requires another.

**Gradle and Android migrations**

* [gradle-version-catalog-lint](https://github.com/cosmichackerx/gradle-version-catalog-lint): Lints `libs.versions.toml`: unused libraries, plugins and versions, dynamic or SNAPSHOT versions, hard-coded dependencies.
* [gradle10-ready](https://github.com/cosmichackerx/gradle10-ready): Static scan of Gradle build scripts for what Gradle 10 removes (space assignment, multi-string dependencies, Kotlin DSL delegates). `--fix`, PR mode.
* [kotlin24-ready](https://github.com/cosmichackerx/kotlin24-ready): Static scan of Gradle build scripts for what Kotlin 2.4 removes in the Kotlin Gradle plugin (language version 1.9, KMP `targetHierarchy`, Compose options, ABI validation). `--fix`, PR mode.
* [android-target-ready](https://github.com/cosmichackerx/android-target-ready): Static scanner for the targetSdk 36 / 37 migration in app code and manifests (edge-to-edge, predictive back, large screens).
* [android-target-lint](https://github.com/cosmichackerx/android-target-lint): The same targetSdk migration checks as real Android Lint rules (a lint jar with type resolution).

**CI and repository hygiene**

* [node24-ready](https://github.com/cosmichackerx/node24-ready): Finds GitHub Actions still on the removed Node 20 runtime, also inside composite actions and reusable workflows, and the smallest node24 upgrade.
* [dependabot-gaps](https://github.com/cosmichackerx/dependabot-gaps): Finds manifests your `dependabot.yml` does not cover, and dead or overlapping entries.
* [sha256-ready](https://github.com/cosmichackerx/sha256-ready): Finds code that assumes 40-character Git hashes before Git 3.0 makes SHA-256 repositories the default.
* [agent-context-diff](https://github.com/cosmichackerx/agent-context-diff): Diffs `AGENTS.md`, `CLAUDE.md`, Cursor rules and MCP configs between git refs (new servers, widened permissions, hidden Unicode).

## License

MIT
