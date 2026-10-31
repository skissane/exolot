import subprocess
import sys
import urllib.error
from io import BytesIO
from pathlib import Path

import pytest

from scripts.post_patch_coverage import MARKER, MAX_BODY_CHARS, _build_body, main

HEAD = (
    "# Diff Coverage\n## Diff: origin/master...HEAD\n\n- a&#46;py (50.0%): Missing lines 2\n\n"
    "## Summary\n\n- **Total**: 2 lines\n- **Missing**: 1 line\n- **Coverage**: 50%\n"
)
REPORT = HEAD + "\n\n\n## a&#46;py\n\nLines 1-2\n\n```python\n  1 a = 1\n! 2 b = 2\n```\n\n\n---\n"


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    """Run main() on PR 7 in tmp_path, holding report as patch-coverage.md
    (unless it's None), with the API faked: comments are the PR's comments,
    head its head commit, and fail (method, url prefix[, exception]) a request
    that fails (default with HTTP 403). Return the exit code, stderr and each
    request as (method, url, token, json_body)."""

    def run(*args, report=REPORT, comments=(), fail=None, head="abc1234def"):
        requests = []

        def fake_request(method, url, token, *, json_body=None, **kw):
            requests.append((method, url, token, json_body))
            if fail and method == fail[0] and url.startswith(fail[1]):
                if len(fail) > 2:
                    raise fail[2]
                raise urllib.error.HTTPError(url, 403, "Forbidden", {}, BytesIO(b"nope"))
            if url == "https://api.github.com/user":
                return {"login": "me"}
            if url == "https://api.github.com/repos/o/r/pulls/7":
                return {"head": {"sha": head}}
            if method == "GET" and "/issues/7/comments" in url:
                return list(comments)
            return None

        if report is not None:
            (tmp_path / "patch-coverage.md").write_text(report)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GITHUB_TOKEN", "ghs")
        monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
        monkeypatch.setattr("scripts.github_comments.request", fake_request)
        code = main(["7", *args])
        return code, capsys.readouterr().err, requests

    return run


def writes(requests):
    return [r for r in requests if r[0] in ("POST", "PATCH", "DELETE")]


def test_posts_report(run):
    code, _, requests = run(
        "--commit", "abc1234", "--run-url", "https://example.com/run", "--author", "github-actions[bot]"
    )
    assert code == 0
    assert {r[2] for r in requests} == {"ghs"}
    assert "https://api.github.com/user" not in [r[1] for r in requests]
    (post,) = writes(requests)
    assert post[:2] == ("POST", "https://api.github.com/repos/o/r/issues/7/comments")
    assert post[3]["body"] == (
        f"{MARKER}\n## Diff Coverage\n\n"
        "Patch coverage of abc1234, from [this workflow run](https://example.com/run).\n\n"
        "### Diff: origin/master...HEAD\n\n"
        "| File | Coverage | Missing lines |\n| --- | ---: | --- |\n| `a.py` | 50.0% | 2 |\n\n"
        "### Summary\n\n| Total | Missing | Coverage |\n| ---: | ---: | ---: |\n| 2 lines | 1 line | 50% |\n\n\n\n"
        "### a&#46;py\n\nLines 1-2\n\n```python\n  1 a = 1\n! 2 b = 2\n```\n\n\n---"
    )


def test_no_lines(run):
    report = "# Diff Coverage\n## Diff: origin/master...HEAD\n\nNo lines with coverage information in this diff.\n"
    code, _, requests = run(report=report)
    assert code == 0
    assert writes(requests)[0][3]["body"] == (
        f"{MARKER}\n## Diff Coverage\n\n### Diff: origin/master...HEAD\n\n"
        "No lines with coverage information in this diff."
    )


NO_LINES = "# Diff Coverage\n## Diff: x\n\nNo lines with coverage information in this diff.\n"


@pytest.mark.parametrize(
    ("report", "error"),
    [
        ("", "line 1: expected '# Diff Coverage', found ''"),
        ("# Coverage\n", "line 1: expected '# Diff Coverage'"),
        ("# Diff Coverage\n", "line 2: expected '## Diff: ...', found the end of the report"),
        ("# Diff Coverage\n## Diff: x\n\n* a.py (50%)\n", "line 4: expected a file's coverage"),
        ("# Diff Coverage\n## Diff: x\n\n- a.py (50%): Missing 2\n", "line 4: expected a file's coverage"),
        (NO_LINES + "more\n", "line 5: expected nothing more, found 'more'"),
        (HEAD.replace("## Summary", "## Totals"), "line 6: expected '## Summary', found '## Totals'"),
        (HEAD.replace("**Missing**", "**Uncovered**"), "line 9: expected '- **Missing**: ...'"),
        (HEAD.replace("- **Coverage**: 50%\n", ""), "line 10: expected '- **Coverage**: ...', found the end"),
    ],
)
def test_unexpected_report_fails(run, report, error):
    code, stderr, requests = run(report=report)
    assert code == 1
    assert f"diff-cover report {error}" in stderr
    assert requests == []


def test_stale_commit_posts_nothing(run):
    code, _, requests = run("--commit", "0ld0ld0")
    assert code == 0
    assert writes(requests) == []


def test_edits_previous_comment(run):
    comments = [
        {"id": 1, "user": {"login": "someone"}, "body": MARKER + "\nnot ours"},
        {"id": 2, "user": {"login": "me"}, "body": "<!-- other -->\nanother kind of comment"},
        {"id": 3, "user": {"login": "me"}, "body": MARKER + "\nold"},
        {"id": 4, "user": {"login": "me"}, "body": MARKER + "\nleft by a raced run"},
    ]
    code, _, requests = run(comments=comments)
    assert code == 0
    assert [r[:2] for r in writes(requests)] == [
        ("PATCH", "https://api.github.com/repos/o/r/issues/comments/3"),
        ("DELETE", "https://api.github.com/repos/o/r/issues/comments/4"),
    ]


def test_lists_become_tables(run):
    report = (
        "# Diff Coverage\n## Diff: origin/master...HEAD\n\n"
        "- scripts/a&#46;py (100%)\n- b&#46;py (40.0%): Missing lines 3,5-9,12\n\n"
        "## Summary\n\n- **Total**: 10 lines\n- **Missing**: 6 lines\n- **Coverage**: 40%\n\n"
        "## b&#46;py\n\n```python\n# not a heading\n```\n- something else\n"
    )
    code, _, requests = run(report=report)
    assert code == 0
    assert writes(requests)[0][3]["body"].split("\n")[3:] == [
        "### Diff: origin/master...HEAD",
        "",
        "| File | Coverage | Missing lines |",
        "| --- | ---: | --- |",
        "| `scripts/a.py` | 100% |  |",
        "| `b.py` | 40.0% | 3, 5-9, 12 |",
        "",
        "### Summary",
        "",
        "| Total | Missing | Coverage |",
        "| ---: | ---: | ---: |",
        "| 10 lines | 6 lines | 40% |",
        "",
        "### b&#46;py",
        "",
        "```python",
        "# not a heading",
        "```",
        "- something else",
    ]


def test_awkward_paths_stay_in_their_cell(run):
    report = HEAD.replace("- a&#46;py (50.0%)", "- a|b`c&#46;py (50.0%)")
    code, _, requests = run(report=report)
    assert code == 0
    assert "| `` a\\|b`c.py `` | 50.0% | 2 |" in writes(requests)[0][3]["body"]


def test_long_report_truncated(run):
    lines = "\n".join(f"  {n} x = {n}" for n in range(20_000))
    report = f"{HEAD}\n## a.py\n\n```python\n{lines}\n```\n"
    code, _, requests = run("--run-url", "https://example.com/run", report=report)
    assert code == 0
    body = writes(requests)[0][3]["body"]
    assert len(body) < 65_536
    before, note = body.rsplit("\n\n", 1)
    assert len(before) <= MAX_BODY_CHARS + 4
    assert before.endswith("\n```")
    assert before.count("```") == 2
    assert "| 2 lines | 1 line | 50% |" in before
    assert note == (
        "_Report truncated; the whole of it is in the `patch-coverage` artifact of "
        "[this workflow run](https://example.com/run)._"
    )


def test_long_report_truncated_outside_code_block(run):
    report = HEAD + "\n## a.py\n\n" + "text\n" * 20_000
    code, _, requests = run(report=report)
    assert code == 0
    before, note = writes(requests)[0][3]["body"].rsplit("\n\n", 1)
    assert before.endswith("\ntext")
    assert "```" not in before
    assert note == "_Report truncated; the whole of it is in the `patch-coverage` artifact of the workflow run._"


def test_missing_report(run):
    code, stderr, requests = run(report=None)
    assert code == 1
    assert "patch-coverage.md" in stderr
    assert requests == []


def test_network_error_reported(run):
    code, stderr, _ = run(fail=("GET", "https://api.github.com/user", urllib.error.URLError("unreachable")))
    assert code == 1
    assert "unreachable" in stderr


def test_http_error_reported(run):
    code, stderr, _ = run(fail=("POST", "https://api.github.com/repos/o/r/issues/7/comments"))
    assert code == 1
    assert "HTTP 403" in stderr
    assert "nope" in stderr


def test_gh_failure_reported(tmp_path, monkeypatch, capsys):
    def fake_gh(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="not logged in")

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setattr("scripts.github_comments.subprocess.run", fake_gh)
    monkeypatch.chdir(tmp_path)
    Path("patch-coverage.md").write_text(REPORT)
    assert main(["7"]) == 1
    assert "not logged in" in capsys.readouterr().err


# The tests below run the installed diff-cover, so an upgrade that changes the
# Markdown format the script expects fails here, rather than only in CI's
# post-patch-coverage job.


def real_report(tmp_path: Path, new_source: str, hits: dict[int, int]) -> str:
    """diff-cover's Markdown report, run as CI runs it, for a branch that
    changes a.py from one line to new_source, with coverage.xml giving each
    line's hits."""

    def git(*args):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "core.autocrlf=false", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-q", "-b", "main")
    (tmp_path / "a.py").write_bytes(b"a = 1\n")
    git("add", "a.py")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "change")
    (tmp_path / "a.py").write_bytes(new_source.encode())
    git("commit", "-qam", "change")
    lines = "".join(f'<line number="{n}" hits="{h}"/>' for n, h in hits.items())
    (tmp_path / "coverage.xml").write_text(
        '<?xml version="1.0" ?><coverage version="7"><sources><source>.</source></sources>'
        '<packages><package name="."><classes><class name="a.py" filename="a.py">'
        f"<lines>{lines}</lines></class></classes></package></packages></coverage>"
    )
    subprocess.run(
        [
            Path(sys.executable).parent / "diff-cover",
            "coverage.xml",
            "--compare-branch=main",
            "--branch-coverage",
            "--format",
            "markdown:report.md",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return (tmp_path / "report.md").read_text()


def test_real_diff_cover_missing_lines(tmp_path):
    body = _build_body(real_report(tmp_path, "a = 1\nb = 2\nc = 3\nd = 4\n", {1: 1, 2: 0, 3: 1, 4: 0}), "abc", None)
    assert "| `a.py` | 33.3% | 2, 4 |" in body
    assert "| 3 lines | 2 lines | 33% |" in body
    assert "! 2 b = 2" in body


def test_real_diff_cover_all_covered(tmp_path):
    body = _build_body(real_report(tmp_path, "a = 1\nb = 2\n", {1: 1, 2: 1}), "abc", None)
    assert "| `a.py` | 100% |  |" in body
    assert "| 1 line | 0 lines | 100% |" in body


def test_real_diff_cover_no_lines(tmp_path):
    body = _build_body(real_report(tmp_path, "a = 1\n# comment\n", {1: 1}), "abc", None)
    assert body.endswith("No lines with coverage information in this diff.")
