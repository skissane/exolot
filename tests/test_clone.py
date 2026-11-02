import os
import subprocess
from pathlib import Path
from typing import Any, NoReturn

import pytest

from exolot import clone
from tests.conftest import git


def _rev(repo: Path, ref: str = "HEAD") -> str:
    return subprocess.run(["git", "rev-parse", ref], cwd=repo, capture_output=True, text=True).stdout.strip()


def test_clone_fetches_the_checked_out_commit_without_history(repo: Path, tmp_path: Path) -> None:
    (repo / "a.py").write_text("changed\n")
    git(repo, "commit", "-q", "-am", "change")
    dest = tmp_path / "clone"
    assert clone.clone(str(repo), dest) == _rev(repo)
    assert (dest / "a.py").read_text() == "changed\n"
    assert (dest / "sub" / "b.py").exists()
    assert (dest / ".git" / "shallow").exists()


@pytest.mark.parametrize(("ref", "expected"), [(None, "topic\n"), ("master", "master\n"), ("v1", "one\ntwo\nthree\n")])
def test_clone_fetches_a_branch_or_tag(repo: Path, tmp_path: Path, ref: str | None, expected: str) -> None:
    git(repo, "tag", "v1", "master")
    for branch in ("master", "topic"):
        git(repo, "checkout", "-q", branch)
        (repo / "a.py").write_text(f"{branch}\n")
        git(repo, "commit", "-q", "-am", branch)
    assert clone.clone(str(repo), tmp_path / "clone", ref) == _rev(repo, ref or "HEAD")
    assert (tmp_path / "clone" / "a.py").read_text() == expected


def test_clone_fetches_a_commit(repo: Path, tmp_path: Path) -> None:
    base = _rev(repo, "master")
    (repo / "a.py").write_text("changed\n")
    git(repo, "commit", "-q", "-am", "change")
    assert clone.clone(str(repo), tmp_path / "clone", base) == base


def test_clone_reports_an_unknown_ref(repo: Path, tmp_path: Path) -> None:
    with pytest.raises(clone.CloneError, match="git fetch failed: .*nope"):
        clone.clone(str(repo), tmp_path / "clone", "nope")


def test_clone_reports_a_missing_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def run(*args: object, **kwargs: object) -> NoReturn:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(clone.CloneError, match="can't run git"):
        clone.clone("https://example.com/r.git", tmp_path / "clone")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("https://github.com/psf/requests", "psf/requests"),
        ("https://github.com/psf/requests.git", "psf/requests"),
        ("https://github.com/psf/requests/", "psf/requests"),
        ("https://user@GitHub.com/o/my.repo", "o/my.repo"),
        ("git@github.com:o/r.git", "o/r"),
        ("ssh://git@github.com/o/r", "o/r"),
        ("https://gitlab.com/o/r", None),
        ("https://github.com/o", None),
        ("https://github.com/o/r/tree/main", None),
        ("/home/me/r", None),
    ],
)
def test_github_link_template(source: str, expected: str | None) -> None:
    template = clone.github_link_template(source, "abc")
    if expected is None:
        assert template is None
    else:
        assert template == f"https://github.com/{expected}/blob/abc/{{path}}#L{{line}}"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("https://x-access-token:secret@github.com/o/r", "https://github.com/o/r"),
        ("https://user@example.com:8443/r.git", "https://example.com:8443/r.git"),
        ("https://github.com/o/r", "https://github.com/o/r"),
        ("git@github.com:o/r.git", "git@github.com:o/r.git"),
        ("/home/me/r", "/home/me/r"),
    ],
)
def test_display_source_leaves_out_credentials(source: str, expected: str) -> None:
    assert clone.display_source(source) == expected


def test_clone_errors_leave_out_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args[0], 128, "", "fatal: 'http://user:secret@host/r.git' not found")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(clone.CloneError) as e:
        clone.clone("http://user:secret@host/r.git", Path("unused"))
    assert str(e.value) == "git init failed: fatal: 'http://host/r.git' not found"


def test_clone_ignores_the_repository_git_points_hooks_at(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other"
    git(tmp_path, "init", "-q", str(other))
    head = _rev(repo)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    assert clone.clone(str(repo), tmp_path / "clone") == head
    assert (tmp_path / "clone" / "a.py").exists()
    assert not (other / "a.py").exists()


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("fatal: 'https://u:p@ss@host/r' not found", "fatal: 'https://host/r' not found"),
        ("see https://host/a@b and ssh://git@host", "see https://host/a@b and ssh://host"),
        ("no urls here", "no urls here"),
    ],
)
def test_without_credentials(message: str, expected: str) -> None:
    assert clone._without_credentials(message) == expected


def test_without_repo_env_restores_the_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_DIR", "/hook/.git")
    monkeypatch.delenv("GIT_WORK_TREE", raising=False)
    with clone.without_repo_env():
        assert "GIT_DIR" not in os.environ
    assert os.environ["GIT_DIR"] == "/hook/.git"
    assert "GIT_WORK_TREE" not in os.environ
