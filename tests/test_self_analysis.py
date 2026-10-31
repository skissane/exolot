import io
import json
import subprocess
import urllib.error

import pytest

from scripts import github_comments, self_analysis
from scripts.self_analysis import MARKER, build_report, main, parse_diff

DIFF = """\
diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -3 +3,2 @@ def f():
-    x = 1
+    x = 2
+    y = 3
@@ -10,2 +10,0 @@ def g():
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


def finding(path="src/a.py", line=3, rule="python:S1", message="bad"):
    return {"path": path, "line": line, "column": 1, "rule": rule, "severity": "warning", "message": message}


def test_parse_diff():
    assert parse_diff(DIFF) == {"src/a.py": {3, 4, 21}, "has space.py": {1}, "new.py": {1, 2}}


def test_report_without_findings():
    body = build_report([])
    assert body.startswith(MARKER + "\n")
    assert "For information only" in body
    assert "No findings." in body


def test_report_lists_all_findings_without_base():
    body = build_report([finding(line=9), finding(line=3)])
    assert "### Findings (2)" in body
    assert body.index("src/a.py:3") < body.index("src/a.py:9")
    assert "<details>" not in body


def test_report_puts_changed_lines_first_and_links():
    body = build_report(
        [finding(line=3), finding(line=9), finding(path="tests\\b.py", line=1)],
        changed={"src/a.py": {3}},
        repo="o/r",
        commit="abc",
        run_url="https://run",
    )
    new, old = body.split("<details>")
    assert "### On lines this PR changes (1)" in new
    assert "[src/a.py:3](https://github.com/o/r/blob/abc/src/a.py#L3)" in new
    assert "Elsewhere (2)" in old
    assert "src/a.py:9" in old
    assert "tests/b.py:1" in old
    assert "[AGENTS.md](https://github.com/o/r/blob/abc/AGENTS.md)" in body
    assert "Analysis of abc, from [this workflow run](https://run)." in body


def test_report_with_no_findings_on_changed_lines():
    body = build_report([finding(line=9)], changed={})
    assert "### On lines this PR changes (0)\n\nNone." in body
    assert "Elsewhere (1)" in body


def test_report_escapes_markdown():
    body = build_report([finding(message="a | b `c` <d>\nnext *e*")])
    assert "a \\| b \\`c\\` \\<d\\> next \\*e\\*" in body


def test_report_is_truncated_to_fit_a_comment():
    body = build_report([finding(line=n, message="x" * 500) for n in range(1, 200)], run_url="https://run")
    assert len(body) <= self_analysis.MAX_BODY_CHARS + 200
    assert "Report truncated" in body
    assert "[this workflow run](https://run)" in body


def test_report_command_uses_git_diff(tmp_path, monkeypatch):
    findings = tmp_path / "findings.json"
    findings.write_text(json.dumps([finding(line=4)]))
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=DIFF)

    monkeypatch.setattr(subprocess, "run", run)
    out = tmp_path / "report.md"
    assert main(["report", str(findings), "--base", "origin/master", "-o", str(out)]) == 0
    assert calls[0][-1] == "origin/master...HEAD"
    assert "### On lines this PR changes (1)" in out.read_text()


def test_report_command_writes_stdout(tmp_path, capsys):
    findings = tmp_path / "findings.json"
    findings.write_text("[]")
    assert main(["report", str(findings)]) == 0
    assert "No findings." in capsys.readouterr().out


def test_report_command_fails_on_bad_input(tmp_path, capsys):
    findings = tmp_path / "findings.json"
    findings.write_text("{not json")
    assert main(["report", str(findings)]) == 1
    assert main(["report", str(tmp_path / "missing.json")]) == 1


def test_report_command_reports_git_failure(tmp_path, monkeypatch, capsys):
    findings = tmp_path / "findings.json"
    findings.write_text("[]")

    def run(cmd, **kwargs):
        raise subprocess.CalledProcessError(128, cmd, stderr="bad revision")

    monkeypatch.setattr(subprocess, "run", run)
    assert main(["report", str(findings), "--base", "nope"]) == 1
    assert "bad revision" in capsys.readouterr().err


class FakeGitHub:
    """Answers github_comments.request like the API would, for PR 7 of o/r
    with head "abc123" and the given comments (GraphQL nodes)."""

    def __init__(self, comments, pages=1):
        self.comments = comments
        self.pages = pages
        self.calls = []

    def __call__(self, method, url, token, *, json_body=None, **kwargs):
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

    def hidden(self):
        return [b["variables"]["id"] for m, u, b in self.calls if b and "minimizeComment" in b.get("query", "")]


def comment(node_id, *, mine=True, minimized=False, body=MARKER + "\nold"):
    return {"id": node_id, "viewerDidAuthor": mine, "isMinimized": minimized, "body": body}


@pytest.fixture
def report(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    path = tmp_path / "report.md"
    path.write_text(MARKER + "\nnew\n")
    return path


@pytest.mark.parametrize("pages", [1, 2])
def test_post_hides_only_own_earlier_reports(report, monkeypatch, capsys, pages):
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
    assert main(["post", "--repo", "o/r", "7", str(report), "--commit", "abc"]) == 0
    posts = [(u, b) for m, u, b in gh.calls if m == "POST" and u.endswith("/issues/7/comments")]
    assert posts == [("https://api.github.com/repos/o/r/issues/7/comments", {"body": MARKER + "\nnew\n"})]
    assert gh.hidden() == ["OLD1", "OLD2"]
    assert "hid 2 earlier report(s)" in capsys.readouterr().out


def test_post_skips_a_stale_commit(report, monkeypatch, capsys):
    gh = FakeGitHub([])
    monkeypatch.setattr(github_comments, "request", gh)
    assert main(["post", "--repo", "o/r", "7", str(report), "--commit", "def"]) == 0
    assert [m for m, u, b in gh.calls] == ["GET"]
    assert "Not posting" in capsys.readouterr().out


def test_post_reports_graphql_errors(report, monkeypatch, capsys):
    def request(method, url, token, **kwargs):
        if url.endswith("/graphql"):
            return {"errors": [{"message": "nope"}]}
        return {"node_id": "NEW"}

    monkeypatch.setattr(github_comments, "request", request)
    assert main(["post", "--repo", "o/r", "7", str(report)]) == 1
    assert "nope" in capsys.readouterr().err


def test_post_reports_http_errors(report, monkeypatch, capsys):
    def request(method, url, token, **kwargs):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO(b"no access"))

    monkeypatch.setattr(github_comments, "request", request)
    assert main(["post", "--repo", "o/r", "7", str(report)]) == 1
    assert "HTTP 403" in capsys.readouterr().err


def test_report_names_the_commit_without_a_run():
    assert "Analysis of abc.\n" in build_report([], commit="abc")


def test_report_quotes_paths_in_links():
    body = build_report([finding(path="a) [x](https://evil.example).py")], repo="o/r", commit="abc")
    assert "](https://github.com/o/r/blob/abc/a%29%20%5Bx%5D%28https%3A//evil.example%29.py#L3)" in body
