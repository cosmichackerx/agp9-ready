import json
import os
import shutil
import subprocess

import pytest

from agp9_ready.cli import main
from agp9_ready.diffmode import GitError, scan_against_base

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
       "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, env={**os.environ, **ENV}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "build.gradle").write_text("plugins {\n    id 'com.android.application' version '9.0.0'\n    id 'org.jetbrains.kotlin.android' version '2.2.10'\n}\n")
    (tmp_path / "gradle.properties").write_text("android.useAndroidX=true\nandroid.newDsl=false\n")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "build.gradle").write_text("plugins { id 'org.jetbrains.kotlin.kapt' }\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    git(tmp_path, "branch", "base")
    git(tmp_path, "checkout", "-q", "-b", "feature")
    return tmp_path


def commit(repo, msg="change"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def new(repo, **kw):
    r = scan_against_base(str(repo), "base", **kw)
    return [(f.rule, f.file, f.snippet) for f in r.findings], r.pr


def test_unchanged_branch_has_no_new_findings(repo):
    f, pr = new(repo)
    assert f == [] and pr == {"base": "base", "existing": 3, "resolved": 0}


def test_only_the_introduced_finding_is_reported(repo):
    with open(repo / "gradle.properties", "a") as fh:
        fh.write("android.builtInKotlin=false\n")
    commit(repo)
    f, pr = new(repo)
    assert f == [("built-in-kotlin-opt-out", "gradle.properties", "android.builtInKotlin=false")]
    assert pr["existing"] == 3


def test_inserting_lines_above_an_old_finding_does_not_make_it_new(repo):
    src = (repo / "gradle.properties").read_text()
    (repo / "gradle.properties").write_text("# header\n# more\n" + src)
    commit(repo)
    assert new(repo)[0] == []


def test_uncommitted_working_tree_changes_count(repo):
    (repo / "app" / "build.gradle").write_text("plugins { id 'org.jetbrains.kotlin.kapt' }\nplugins { id 'org.jetbrains.kotlin.android' }\n")
    f, _ = new(repo)
    assert [x[0] for x in f] == ["kotlin-android-plugin"] and f[0][1] == "app/build.gradle"


def test_resolved_findings_are_counted_and_renames_are_followed(repo):
    git(repo, "mv", "app/build.gradle", "app/build-renamed.gradle")
    (repo / "gradle.properties").write_text("android.useAndroidX=true\n")
    commit(repo)
    f, pr = new(repo)
    assert f == []
    assert pr["resolved"] == 1 and pr["existing"] == 2  # the opt-out was removed; the renamed file's kapt finding is the same one


def test_a_new_file_is_entirely_new_and_a_subdirectory_can_be_scanned(repo):
    (repo / "lib").mkdir()
    (repo / "lib" / "build.gradle").write_text("plugins {\n  id 'org.jetbrains.kotlin.kapt'\n  id 'org.jetbrains.kotlin.android'\n}\n")
    commit(repo)
    f, _ = new(repo)
    assert sorted(x[0] for x in f) == ["kapt-plugin", "kotlin-android-plugin"] and {x[1] for x in f} == {"lib/build.gradle"}
    sub, _ = new(repo / "app")
    assert sub == []


def test_target_is_forwarded(repo):
    (repo / "gradle.properties").write_text("android.useAndroidX=true\nandroid.newDsl=false\n# touched\n")
    commit(repo)
    r = scan_against_base(str(repo), "base", target=10)
    assert r.target == 10 and r.findings == [] and r.pr["existing"] == 3


def test_cli_exit_codes_and_json(repo, capsys):
    assert main([str(repo), "--base", "base"]) == 0
    with open(repo / "gradle.properties", "a") as fh:
        fh.write("android.builtInKotlin=false\n")
    commit(repo)
    assert main([str(repo), "--base", "base", "--fail-on", "warning", "-f", "json"]) == 1
    capsys.readouterr()
    assert main([str(repo), "--base", "base", "--fail-on", "never", "-f", "json"]) == 0
    out = capsys.readouterr().out
    d = json.loads(out[out.rindex('{\n  "tool"'):])
    assert d["pullRequest"] == {"base": "base", "existing": 3, "resolved": 0} and len(d["findings"]) == 1


def test_unknown_base_and_not_a_repo(tmp_path, repo, capsys):
    assert main([str(repo), "--base", "nope"]) == 2
    assert "fetch-depth: 0" in capsys.readouterr().err
    other = tmp_path.parent / (tmp_path.name + "-nogit")
    other.mkdir()
    (other / "build.gradle").write_text("plugins { id 'org.jetbrains.kotlin.android' }\n")
    try:
        with pytest.raises(GitError):
            scan_against_base(str(other), "main")
    finally:
        shutil.rmtree(other)


def test_base_and_fix_cannot_be_combined(repo):
    assert main([str(repo), "--base", "base", "--fix"]) == 2
