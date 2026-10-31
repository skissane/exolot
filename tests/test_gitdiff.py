import subprocess

import pytest

from exolot import gitdiff
from exolot.gitdiff import Changes, GitError, changes_since, parse_diff
from tests.conftest import git

DIFF = """\
diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -3,2 +3,2 @@ def f():
-    x = 1
--- not a header
+    x = 2
++++ b/not a header
@@ -10,2 +10,0 @@ def g():
-    a = 1
-    b = 2
@@ -20,0 +21 @@
+z = 4
diff --git a/old.py b/old.py
--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
-gone
diff --git a/has space.py b/has space.py
--- a/has space.py\t
+++ b/has space.py\t
@@ -1 +1 @@
-x
+y
diff --git a/new.py b/new.py
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+a
+b
"""


def test_parse_diff():
    assert parse_diff(DIFF) == {"src/a.py": {3, 4, 21}, "has space.py": {1}, "new.py": {1, 2}}


def test_changes_since_the_merge_base(repo, monkeypatch):
    (repo / "a.py").write_text("one\nTWO\nthree\nfour\n")
    git(repo, "commit", "-q", "-am", "change a")
    # Changes on master since the branch point aren't the branch's.
    git(repo, "checkout", "-q", "master")
    (repo / "sub" / "b.py").write_text("B\n")
    git(repo, "commit", "-q", "-am", "change b")
    git(repo, "checkout", "-q", "topic")
    # Nor are ignored files, but uncommitted and untracked ones are.
    (repo / ".gitignore").write_text("ignored.py\n")
    (repo / "ignored.py").write_text("x\n")
    (repo / "sub" / "new.py").write_text("x\n")
    monkeypatch.chdir(repo / "sub")
    changes = changes_since("master")
    assert changes.lines == {repo / "a.py": {2, 4}}
    assert changes.new_files == {repo / ".gitignore", repo / "sub" / "new.py"}
    assert changes.files() == {repo / "a.py", repo / ".gitignore", repo / "sub" / "new.py"}
    assert changes.touches(repo / "a.py", 2)
    assert not changes.touches(repo / "a.py", 1)
    assert changes.touches(repo / "sub" / "new.py", 7)
    assert not changes.touches(repo / "sub" / "b.py", 1)


def test_changes_ignore_the_users_diff_prefix_settings(repo):
    git(repo, "config", "diff.noprefix", "true")
    (repo / "a.py").write_text("ONE\ntwo\nthree\n")
    assert changes_since("master", repo).lines == {repo / "a.py": {1}}


def test_changes_since_an_unknown_ref(repo):
    with pytest.raises(GitError, match="can't find commit 'nope'"):
        changes_since("nope", repo)


def test_changes_without_a_merge_base(repo):
    git(repo, "checkout", "-q", "--orphan", "other")
    git(repo, "commit", "-q", "-m", "unrelated")
    with pytest.raises(GitError, match="can't find the merge base of 'master' and HEAD"):
        changes_since("master", repo)


def test_changes_outside_a_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    with pytest.raises(GitError, match="not in a git repository: fatal"):
        changes_since("master", tmp_path)


def test_changes_without_git(monkeypatch):
    def run(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(gitdiff.subprocess, "run", run)
    with pytest.raises(GitError, match="needs git"):
        changes_since("master")


def test_git_failure_without_a_message(monkeypatch):
    monkeypatch.setattr(gitdiff.subprocess, "run", lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 1, "", ""))
    with pytest.raises(GitError, match="^not in a git repository$"):
        changes_since("master")


def test_empty_changes():
    assert Changes().files() == set()
