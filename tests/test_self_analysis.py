import io
import subprocess
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any, NoReturn

import pytest

from scripts import github_comments
from scripts.self_analysis import MARKER, main


def test_post_reports_gh_failure(
    report: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN")

    def run(cmd: list[str], **kwargs: object) -> NoReturn:
        raise subprocess.CalledProcessError(4, cmd, stderr="not logged in")

    monkeypatch.setattr(subprocess, "run", run)
    assert main(["7", str(report), "--repo", "o/r"]) == 1
    assert "gh auth token failed:\nnot logged in" in capsys.readouterr().err


class FakeGitHub:
    """Answers github_comments.request like the API would, for PR 7 of o/r
    with head "abc123" and the given comments (GraphQL nodes)."""

    def __init__(self, comments: list[dict[str, Any]], pages: int = 1) -> None:
        self.comments = comments
        self.pages = pages
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self, method: str, url: str, token: str, *, json_body: Any = None, **kwargs: object) -> Any:
        self.calls.append((method, url, json_body))
        if url.endswith("/pulls/7"):
            return {"head": {"sha": "abc123"}}
        if url.endswith("/issues/7/comments"):
            return {"node_id": "NEW"}
        assert url.endswith("/graphql")
        if "minimizeComment" in json_body["query"]:
            return {"data": {"minimizeComment": {"clientMutationId": None}}}
        page = 0 if json_body["variables"]["cursor"] is None else int(json_body["variables"]["cursor"])
        per_page = -(-len(self.comments) // self.pages) if self.comments else 1
        nodes = self.comments[page * per_page : (page + 1) * per_page]
        more = page + 1 < self.pages
        comments = {"nodes": nodes, "pageInfo": {"hasNextPage": more, "endCursor": str(page + 1) if more else None}}
        return {"data": {"repository": {"pullRequest": {"comments": comments}}}}

    def hidden(self) -> list[str]:
        return [b["variables"]["id"] for m, u, b in self.calls if b and "minimizeComment" in b.get("query", "")]


def comment(
    node_id: str, *, mine: bool = True, minimized: bool = False, body: str = MARKER + "\nold"
) -> dict[str, Any]:
    return {"id": node_id, "viewerDidAuthor": mine, "isMinimized": minimized, "body": body}


@pytest.fixture
def report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    path = tmp_path / "report.md"
    path.write_text("new\n")
    return path


@pytest.mark.parametrize("pages", [1, 2])
def test_post_hides_only_own_earlier_reports(
    report: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], pages: int
) -> None:
    gh = FakeGitHub(
        [
            comment("OLD1"),
            comment("THEIRS", mine=False),
            comment("HIDDEN", minimized=True),
            comment("OTHER", body="<!-- something else -->"),
            comment("OLD2"),
            comment("NEW"),
        ],
        pages=pages,
    )
    monkeypatch.setattr(github_comments, "request", gh)
    assert main(["--repo", "o/r", "7", str(report), "--commit", "abc"]) == 0
    posts = [(u, b) for m, u, b in gh.calls if m == "POST" and u.endswith("/issues/7/comments")]
    assert posts == [("https://api.github.com/repos/o/r/issues/7/comments", {"body": MARKER + "\nnew\n"})]
    assert gh.hidden() == ["OLD1", "OLD2"]
    assert "hid 2 earlier report(s)" in capsys.readouterr().out


def test_post_skips_a_stale_commit(
    report: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGitHub([])
    monkeypatch.setattr(github_comments, "request", gh)
    assert main(["--repo", "o/r", "7", str(report), "--commit", "def"]) == 0
    assert [m for m, u, b in gh.calls] == ["GET"]
    assert "Not posting" in capsys.readouterr().out


def test_post_reports_graphql_errors(
    report: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def request(method: str, url: str, token: str, **kwargs: object) -> dict[str, Any]:
        if url.endswith("/graphql"):
            return {"errors": [{"message": "nope"}]}
        return {"node_id": "NEW"}

    monkeypatch.setattr(github_comments, "request", request)
    assert main(["--repo", "o/r", "7", str(report)]) == 1
    assert "nope" in capsys.readouterr().err


def test_post_reports_http_errors(
    report: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def request(method: str, url: str, token: str, **kwargs: object) -> NoReturn:
        raise urllib.error.HTTPError(url, 403, "Forbidden", Message(), io.BytesIO(b"no access"))

    monkeypatch.setattr(github_comments, "request", request)
    assert main(["--repo", "o/r", "7", str(report)]) == 1
    assert "HTTP 403" in capsys.readouterr().err
