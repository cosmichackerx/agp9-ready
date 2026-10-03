# Changelog

## 0.2.1 - 2026-10-03

* New rule `kotlin-options`: `android { kotlinOptions { } }` fails with built-in Kotlin; oracle case against AGP 9.4.1 (and a negative case for the `kotlin { compilerOptions { } }` replacement).
* Version catalogs: table sections (`[plugins.kotlin-android]` + `id = ...`) and dotted keys (`kapt.id = ...`, `kapt.version.ref = ...`) are read, so `alias(libs.plugins...)` to such entries is resolved; 3 oracle cases.
* pre-commit hooks `agp9-ready` and `agp9-ready-fix` (`.pre-commit-hooks.yaml`), checked in CI with `pre-commit try-repo`.
* `action.yml` description shortened to the Marketplace limit of 125 characters, with a CI check (name, description length, branding).

## 0.2.0 - 2026-10-03

* Weekly docs watcher (`scripts/watch/watch_agp_docs.py`, `.github/workflows/agp-watch.yml`): new AGP release-notes pages and sections, roadmap title changes, stale rule anchors, uncovered documented properties. One deduplicated issue.
* PR mode: `--base REF` reports only findings a change introduces (matched by rule, file and line text; renames followed); Action inputs `pr-mode`, `base`.
* Sticky pull request comment (`comment: true`), updated in place; skipped for fork PRs.
* Scan `.kt`, `.java` and `.groovy` sources under `buildSrc`, `build-logic` and `buildLogic` (legacy extension types, legacy variant API, `registerTransform`, kotlin-android/kapt applied by id); 3 new oracle cases against AGP 9.4.1.

## 0.1.0 - 2026-10-03

First release.

* 17 rules for Android Gradle Plugin 9 and the AGP 10 roadmap: `kotlin-android` and kapt plugins (built-in Kotlin), legacy variant API, legacy extension types, removed DSL members, density splits, embedded Wear OS apps, `setDimension`, `registerTransform`, `gradle.properties` flags (enforced, removed, opt-outs, pinned old defaults), Gradle wrapper older than 9.1.0, third-party plugin versions reported to need an opt-out, old KSP versions.
* `--agp-target 10` turns the temporary opt-outs (`android.newDsl=false`, `android.builtInKotlin=false`) into errors.
* `--fix` for the mechanical cases: remove the `kotlin-android` plugin line (only when `android.builtInKotlin=false` is not set), delete `android.enableLegacyVariantApi` and the no-effect properties, `setDimension("x")` to `dimension = "x"`.
* Text, Markdown, JSON, GitHub annotation and SARIF 2.1.0 output; composite GitHub Action.
* Checked against real AGP 9.4.1 in CI (`tests/oracle/run_oracle.py`).
