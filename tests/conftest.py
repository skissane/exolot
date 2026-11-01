"""Fixtures for more than one test module."""

import os
import subprocess

import pytest


@pytest.fixture(autouse=True)
def _outside_github_actions(monkeypatch):
    """Run every test as if outside GitHub Actions, even in CI, so exolot
    doesn't link to the workflow's repository unless a test asks it to."""
    for name in ("GITHUB_ACTIONS", "GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        monkeypatch.delenv(name, raising=False)


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repo whose master has a.py (three lines) and b.py, checked out on a
    branch "topic" from it, with the user's git config ignored."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{name}_NAME", "t")
        monkeypatch.setenv(f"GIT_{name}_EMAIL", "t@example.com")
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    git(repo, "init", "-q", "-b", "master")
    (repo / "a.py").write_text("one\ntwo\nthree\n")
    (repo / "sub" / "b.py").write_text("b\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "checkout", "-q", "-b", "topic")
    return repo.resolve()
