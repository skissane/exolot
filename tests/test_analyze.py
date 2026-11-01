import json
import subprocess
import sys
from pathlib import Path

import pytest

from exolot import cli
from exolot.analyze import AnalysisSession, collect_files, language_id
from exolot.server import Server
from tests.conftest import git

FAKE_SERVER = Path(__file__).with_name("fake_server.py")


class FakeServer(Server):
    def command(self, jvm_args=None):
        return [sys.executable, str(FAKE_SERVER)]


def test_language_id():
    assert language_id(Path("a.py")) == "python"
    assert language_id(Path("A.TSX")) == "typescriptreact"
    assert language_id(Path("Dockerfile")) == "dockerfile"
    assert language_id(Path("notes.txt")) == "plaintext"


def test_collect_files_skips_binary_and_ignored(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "blob.bin").write_bytes(b"\0\1\2")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("x\n")
    files = collect_files([tmp_path])
    assert files == [(tmp_path / "a.py").resolve()]


def test_collect_files_respects_gitignore(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("ignored.py\n")
    (tmp_path / "ignored.py").write_text("x = 1\n")
    (tmp_path / "kept.py").write_text("x = 1\n")
    names = {f.name for f in collect_files([tmp_path])}
    assert names == {".gitignore", "kept.py"}


def test_session_collects_final_diagnostics(tmp_path):
    a = tmp_path / "a.py"
    a.write_text("x = 1\n")
    b = tmp_path / "b.js"
    b.write_text("var x\n")
    server = FakeServer(root=tmp_path, java=Path("java"))
    with AnalysisSession(server, tmp_path) as session:
        issues = session.analyze([a, b], settle=0.2, timeout=10)
    issues.sort(key=lambda i: i.path.name)
    assert [(i.path.name, i.line, i.column, i.rule, i.message) for i in issues] == [
        ("a.py", 1, 3, "fake:S1", "python issue"),
        ("b.js", 1, 3, "fake:S1", "javascript issue"),
    ]


def test_session_raises_when_a_file_is_never_published(tmp_path):
    a = tmp_path / "a.py"
    a.write_text("SILENT\n")
    server = FakeServer(root=tmp_path, java=Path("java"))
    with AnalysisSession(server, tmp_path) as session:
        with pytest.raises(RuntimeError, match="never reported results"):
            session.analyze([a], settle=0.1, stall=0.5, timeout=10)


def test_session_closes_server_pipes(tmp_path):
    server = FakeServer(root=tmp_path, java=Path("java"))
    with AnalysisSession(server, tmp_path) as session:
        proc = session._proc
    assert proc.returncode is not None
    assert proc.stdin.closed and proc.stdout.closed


def test_session_closes_pipes_of_a_server_that_died(tmp_path):
    server = FakeServer(root=tmp_path, java=Path("java"))
    with AnalysisSession(server, tmp_path) as session:
        proc = session._proc
        proc.kill()
        proc.wait()
    assert proc.stdin.closed and proc.stdout.closed


def test_closing_an_unstarted_session_does_nothing(tmp_path):
    AnalysisSession(FakeServer(root=tmp_path, java=Path("java")), tmp_path).close()


def test_collect_files_rejects_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        collect_files([tmp_path / "nope"])


def test_cli_input_errors_exit_2_without_downloading(tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise AssertionError("should not download")

    monkeypatch.setattr(cli, "ensure_server", fail)
    (tmp_path / "a.py").write_text("x = 1\n")
    bad_rules = tmp_path / "rules.json"
    bad_rules.write_text("{not json")
    assert cli.main([str(tmp_path / "nope")]) == 2
    assert cli.main(["--rules", str(bad_rules), str(tmp_path)]) == 2
    assert cli.main(["--rules", str(tmp_path / "missing.json"), str(tmp_path)]) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli.main([str(empty)]) == 0


@pytest.mark.parametrize(("flags", "expected"), [([], 1), (["--exit-zero"], 0), (["-e"], 0)])
def test_cli_exit_status_with_issues(tmp_path, monkeypatch, capsys, flags, expected):
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))
    (tmp_path / "a.py").write_text("x = 1\n")
    assert cli.main([*flags, "--workspace", str(tmp_path), str(tmp_path / "a.py")]) == expected
    assert "fake:S1" in capsys.readouterr().out


def test_cli_exit_zero_still_reports_a_failed_analysis(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))
    (tmp_path / "a.py").write_text("SILENT\n")
    assert cli.main(["--exit-zero", "--timeout", "1", "--workspace", str(tmp_path), str(tmp_path / "a.py")]) == 2
    assert "did not finish in time" in capsys.readouterr().err


def _run_statistics(tmp_path, monkeypatch, capsys, *flags, texts=("TWO TWO", "TWO TWO TWO", "x = 1")):
    """Analyze one file per text: each has one fake:S1 issue, plus a fake:S2 issue per "TWO"."""
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))
    for name, text in zip("abc", texts):
        (tmp_path / f"{name}.py").write_text(text + "\n")
    status = cli.main(["--statistics", *flags, "--workspace", str(tmp_path), str(tmp_path)])
    return status, capsys.readouterr()


def test_cli_statistics_counts_issues_per_rule_most_common_first(tmp_path, monkeypatch, capsys):
    status, captured = _run_statistics(tmp_path, monkeypatch, capsys)
    assert status == 1
    assert captured.out == "5\tfake:S2\n3\tfake:S1\tFake rule one\n"
    assert "8 issue(s) in 3 file(s) analyzed" in captured.err


def test_cli_statistics_orders_ties_by_rule_key(tmp_path, monkeypatch, capsys):
    _, captured = _run_statistics(tmp_path, monkeypatch, capsys, texts=("TWO", "TWO TWO", "x = 1"))
    assert captured.out == "3\tfake:S1\tFake rule one\n3\tfake:S2\n"


def test_cli_statistics_json(tmp_path, monkeypatch, capsys):
    status, captured = _run_statistics(tmp_path, monkeypatch, capsys, "--format", "json", "--exit-zero")
    assert status == 0
    assert json.loads(captured.out) == [
        {"code": "fake:S2", "name": "", "count": 5},
        {"code": "fake:S1", "name": "Fake rule one", "count": 3},
    ]


def test_cli_statistics_without_rule_names(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_SERVER_RULES_FAIL", "1")
    _, captured = _run_statistics(tmp_path, monkeypatch, capsys)
    assert captured.out == "5\tfake:S2\n3\tfake:S1\n"


def test_cli_statistics_with_no_issues(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))
    monkeypatch.setattr(AnalysisSession, "analyze", lambda self, files, timeout=None: [])

    def no_rule_names(self):
        raise AssertionError("rule names aren't needed when there are no issues")

    monkeypatch.setattr(AnalysisSession, "rule_names", no_rule_names)
    (tmp_path / "a.py").write_text("x = 1\n")
    assert cli.main(["--statistics", "--workspace", str(tmp_path), str(tmp_path / "a.py")]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "0 issue(s) in 1 file(s) analyzed" in captured.err


def test_cli_markdown_with_links(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "b.py").write_text("x = 1\n")
    (tmp_path / "a b.py").write_text("x = 1\n")
    status = cli.main(["--format", "markdown", "--link-template", "https://x/{path}#L{line}", "."])
    assert status == 1
    captured = capsys.readouterr()
    assert captured.out == (
        "| Location | Rule | Message |\n"
        "| --- | --- | --- |\n"
        "| [a b.py:1](https://x/a%20b.py#L1) | fake:S1 | python issue |\n"
        "| [b.py:1](https://x/b.py#L1) | fake:S1 | python issue |\n"
    )
    assert "2 issue(s) in 2 file(s) analyzed" in captured.err


def test_cli_markdown_with_no_issues(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))
    monkeypatch.setattr(AnalysisSession, "analyze", lambda self, files, timeout=None: [])
    (tmp_path / "a.py").write_text("x = 1\n")
    assert cli.main(["--format", "markdown", "--workspace", str(tmp_path), str(tmp_path / "a.py")]) == 0
    assert capsys.readouterr().out == "No issues found.\n"


def test_cli_statistics_markdown(tmp_path, monkeypatch, capsys):
    status, captured = _run_statistics(tmp_path, monkeypatch, capsys, "--format", "markdown")
    assert status == 1
    assert captured.out == (
        "| Count | Rule | Name |\n| ---: | --- | --- |\n| 5 | fake:S2 |  |\n| 3 | fake:S1 | Fake rule one |\n"
    )
    assert "8 issue(s) in 3 file(s) analyzed" in captured.err


def test_cli_statistics_markdown_with_no_issues(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(AnalysisSession, "analyze", lambda self, files, timeout=None: [])
    status, captured = _run_statistics(tmp_path, monkeypatch, capsys, "--format", "markdown")
    assert status == 0
    assert captured.out == "No issues found.\n"


@pytest.mark.parametrize(
    ("flags", "error"),
    [
        (["--format", "markdown", "--link-template", "{nope}"], "unknown field 'nope'"),
        (["--link-template", "{path}"], "needs --format markdown"),
        (["--link-template", ""], "empty link template"),
        (["--format", "markdown", "--statistics", "--link-template", "{path}"], "needs --format markdown"),
    ],
)
def test_cli_rejects_bad_link_templates_without_downloading(tmp_path, monkeypatch, capsys, flags, error):
    def fail(*args, **kwargs):
        raise AssertionError("should not download")

    monkeypatch.setattr(cli, "ensure_server", fail)
    with pytest.raises(SystemExit) as exc:
        cli.main([*flags, str(tmp_path)])
    assert exc.value.code == 2
    assert error in capsys.readouterr().err


def test_cli_markdown_paths_are_relative_to_the_repo_root(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))
    repo = tmp_path / "repo"
    sub = repo / "sub"
    sub.mkdir(parents=True)
    (repo / ".git").mkdir()
    (sub / "a.py").write_text("x = 1\n")
    outside = tmp_path / "b.py"
    outside.write_text("x = 1\n")
    monkeypatch.chdir(sub)
    cli.main(["--format", "markdown", "--link-template", "u/{path}", "--workspace", str(repo), "a.py", str(outside)])
    out = capsys.readouterr().out
    assert "| [sub/a.py:1](u/sub/a.py) |" in out
    assert "| [../../b.py:1](u/../../b.py) |" in out


def test_cli_github_annotations(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))
    repo = tmp_path / "repo"
    sub = repo / "sub"
    sub.mkdir(parents=True)
    (repo / ".git").mkdir()
    (sub / "a.py").write_text("TWO\n")
    monkeypatch.chdir(sub)
    assert cli.main(["--format", "github-annotations", "--workspace", str(repo), "a.py"]) == 1
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "::notice file=sub/a.py,line=1,col=1,endLine=1,endColumn=2,title=fake%3AS2::another issue",
        "::warning file=sub/a.py,line=1,col=3,endLine=1,endColumn=6,title=fake%3AS1::python issue",
    ]
    assert "2 issue(s) in 1 file(s) analyzed" in captured.err


def test_cli_github_annotations_put_changed_lines_first(repo, tmp_path, monkeypatch, capsys):
    _fake_server(tmp_path, monkeypatch)
    (repo / "sub" / "b.py").write_text("changed\n")
    monkeypatch.chdir(repo)
    assert (
        cli.main(["--diff-base", "master", "--format", "github-annotations", "--workspace", str(repo), str(repo)]) == 1
    )
    captured = capsys.readouterr()
    assert [line.split(",")[0] for line in captured.out.splitlines()] == [
        "::warning file=sub/b.py",
        "::warning file=a.py",
    ]
    assert "2 issue(s), 1 on changed lines, in 2 file(s) analyzed" in captured.err


def test_cli_statistics_cant_be_annotations(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_server", _no_download)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--statistics", "--format", "github-annotations", str(tmp_path)])
    assert exc.value.code == 2
    assert "--statistics can't be used with --format github-annotations" in capsys.readouterr().err


def _fake_server(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))


def _no_download(*args, **kwargs):
    raise AssertionError("should not download")


def test_cli_diff_base_marks_issues_on_changed_lines(repo, tmp_path, monkeypatch, capsys):
    # The fake server reports an issue on line 1 of each file.
    _fake_server(tmp_path, monkeypatch)
    (repo / "a.py").write_text("ONE\ntwo\nthree\n")
    monkeypatch.chdir(repo / "sub")
    assert cli.main(["--diff-base", "master", "--format", "json", "--workspace", str(repo), str(repo)]) == 1
    assert [(f["path"], f["changed"]) for f in json.loads(capsys.readouterr().out)] == [
        (str(Path("../a.py")), True),
        ("b.py", False),
    ]

    assert cli.main(["--diff-base", "master", "--workspace", str(repo), str(repo)]) == 1
    captured = capsys.readouterr()
    assert "2 issue(s), 1 on changed lines, in 2 file(s) analyzed" in captured.err
    out = captured.out.splitlines()
    assert out[0].endswith("python issue (changed)")
    assert out[1].endswith("python issue")

    assert cli.main(["--diff-base", "master", "--format", "markdown", "--workspace", str(repo), str(repo)]) == 1
    out = capsys.readouterr().out
    changed, elsewhere = out.split("<details>")
    assert "### On changed lines (1)" in changed
    assert "| a.py:1 |" in changed
    assert "<summary>Elsewhere (1)</summary>" in elsewhere
    assert "| sub/b.py:1 |" in elsewhere


def test_cli_changed_only_analyzes_and_reports_only_changes(repo, tmp_path, monkeypatch, capsys):
    _fake_server(tmp_path, monkeypatch)
    (repo / "a.py").write_text("one\nTWO\nthree\n")
    (repo / "sub" / "new.py").write_text("x = 1\n")
    monkeypatch.chdir(repo)
    assert cli.main(["--diff-base", "master", "--changed-only", "--format", "json", "--workspace", str(repo)]) == 1
    out = capsys.readouterr().out
    # a.py's issue is on line 1, which it didn't change; sub/b.py isn't analyzed.
    assert [f["path"] for f in json.loads(out)] == [str(Path("sub/new.py"))]
    assert "changed" not in out

    assert cli.main(["--diff-base", "master", "--changed-only", "--workspace", str(repo)]) == 1
    captured = capsys.readouterr()
    assert "(changed)" not in captured.out
    assert "1 issue(s) in 2 file(s) analyzed" in captured.err

    (repo / "sub" / "new.py").unlink()
    assert cli.main(["--diff-base", "master", "--changed-only", "--statistics", "--workspace", str(repo)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "0 issue(s) in 1 file(s) analyzed" in captured.err


def test_cli_changed_only_with_no_changed_files(repo, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_server", _no_download)
    monkeypatch.chdir(repo)
    assert cli.main(["--diff-base", "master", "--changed-only"]) == 0
    assert "no files to analyze" in capsys.readouterr().err


def test_cli_diff_base_errors_exit_2_without_downloading(repo, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_server", _no_download)
    monkeypatch.chdir(repo)
    assert cli.main(["--diff-base", "nope"]) == 2
    assert "exolot: can't find commit 'nope'" in capsys.readouterr().err
    assert cli.main(["--diff-base", ""]) == 2
    assert "exolot: can't find commit ''" in capsys.readouterr().err


def test_cli_changed_only_needs_diff_base(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_server", _no_download)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--changed-only", str(tmp_path)])
    assert exc.value.code == 2
    assert "--changed-only needs --diff-base" in capsys.readouterr().err


def test_cli_diff_base_counts_secondary_locations_and_whole_ranges(repo, tmp_path, monkeypatch, capsys):
    # The fake server's flow issue (fake:S3) is on line 1, with a secondary
    # location on line 2; its fake:S1 issue is on line 1 alone.
    _fake_server(tmp_path, monkeypatch)
    (repo / "a.py").write_text("FLOW\nTWO\nthree\n")
    git(repo, "commit", "-q", "-am", "flow")
    (repo / "a.py").write_text("FLOW\nchanged\nthree\n")
    monkeypatch.chdir(repo)
    args = ["--diff-base", "HEAD", "--format", "json", "--workspace", str(repo), "a.py"]
    assert cli.main(args) == 1
    findings = json.loads(capsys.readouterr().out)
    assert [(f["rule"], f["changed"]) for f in findings] == [("fake:S3", True), ("fake:S1", False)]
    # The message keeps its note of the secondary locations, which only SARIF shows.
    assert findings[0]["message"] == "flow issue [+1 location]"

    assert cli.main([*args, "--changed-only"]) == 1
    assert [f["rule"] for f in json.loads(capsys.readouterr().out)] == ["fake:S3"]

    assert cli.main([*args, "--changed-only", "--format", "sarif"]) == 1
    results = json.loads(capsys.readouterr().out)["runs"][0]["results"]
    assert [(r["ruleId"], r["message"]["text"]) for r in results] == [("fake:S3", "flow issue")]

    # Statistics without --changed-only don't need to know what changed.
    monkeypatch.setattr(AnalysisSession, "add_related_locations", _no_download)
    assert cli.main([*args, "--statistics"]) == 1


def _in_actions(monkeypatch, run_id="42"):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.example/")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    if run_id:
        monkeypatch.setenv("GITHUB_RUN_ID", run_id)


def _head(repo):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()


def test_cli_markdown_links_to_the_checked_out_commit_in_github_actions(repo, tmp_path, monkeypatch, capsys):
    _fake_server(tmp_path, monkeypatch)
    _in_actions(monkeypatch)
    monkeypatch.chdir(repo / "sub")
    assert cli.main(["--format", "markdown", "b.py"]) == 1
    assert f"| [sub/b.py:1](https://github.example/o/r/blob/{_head(repo)}/sub/b.py#L1) |" in capsys.readouterr().out


@pytest.mark.parametrize("flags", [["--no-links"], ["--link-template", "u/{path}"]], ids=["no-links", "link-template"])
def test_cli_markdown_links_in_github_actions_can_be_overridden(repo, tmp_path, monkeypatch, capsys, flags):
    _fake_server(tmp_path, monkeypatch)
    _in_actions(monkeypatch)
    monkeypatch.chdir(repo)
    cli.main(["--format", "markdown", *flags, "a.py"])
    assert "github.example" not in capsys.readouterr().out


def test_cli_markdown_has_no_links_in_github_actions_outside_a_repo(tmp_path, monkeypatch, capsys):
    _fake_server(tmp_path, monkeypatch)
    _in_actions(monkeypatch)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    cli.main(["--format", "markdown", "a.py"])
    assert capsys.readouterr().out.endswith("| a.py:1 | fake:S1 | python issue |\n")


def test_cli_github_comment(repo, tmp_path, monkeypatch, capsys):
    _fake_server(tmp_path, monkeypatch)
    _in_actions(monkeypatch)
    (repo / "pyproject.toml").write_text('[tool.exolot]\npreamble = "Read *this*."\n')
    (repo / "a.py").write_text("one changed\ntwo\nthree\n")
    monkeypatch.chdir(repo)
    assert cli.main(["--format", "github-comment", "--diff-base", "master", "a.py", "sub/b.py"]) == 1
    captured = capsys.readouterr()
    head = _head(repo)
    assert captured.out.startswith(
        "## exolot's findings\n\nRead *this*.\n\n"
        f"Analysis of {head}, from [this workflow run](https://github.example/o/r/actions/runs/42).\n\n"
        "### On changed lines (1)\n"
    )
    assert f"[a.py:1](https://github.example/o/r/blob/{head}/a.py#L1)" in captured.out
    assert "Elsewhere (" in captured.out
    assert "1 on changed lines, in 2 file(s) analyzed" in captured.err


def test_cli_github_comment_outside_github_actions(tmp_path, monkeypatch, capsys):
    _fake_server(tmp_path, monkeypatch)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    assert cli.main(["--format", "github-comment", "a.py"]) == 1
    captured = capsys.readouterr()
    assert captured.out == (
        "## exolot's findings\n\n### Findings (1)\n\n"
        "| Location | Rule | Message |\n| --- | --- | --- |\n| a.py:1 | fake:S1 | python issue |\n"
    )
    assert "1 issue(s) in 1 file(s) analyzed" in captured.err


def test_cli_bad_config_exits_2_without_downloading(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_server", _no_download)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".exolot.toml").write_text("nope = 1\n")
    (tmp_path / "a.py").write_text("x = 1\n")
    assert cli.main(["a.py"]) == 2
    assert "unknown setting 'nope'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("flags", "error"),
    [
        (["--format", "github-comment", "--statistics"], "--statistics can't be used with --format github-comment"),
        (["--no-links"], "--no-links needs --format markdown or github-comment"),
        (["--format", "markdown", "--no-links", "--link-template", "{path}"], "--no-links needs"),
    ],
)
def test_cli_rejects_github_comment_and_no_links_misuse(tmp_path, monkeypatch, capsys, flags, error):
    monkeypatch.setattr(cli, "ensure_server", _no_download)
    with pytest.raises(SystemExit) as exc:
        cli.main([*flags, str(tmp_path)])
    assert exc.value.code == 2
    assert error in capsys.readouterr().err


def test_cli_github_comment_without_git(tmp_path, monkeypatch, capsys):
    _fake_server(tmp_path, monkeypatch)
    real_run = subprocess.run

    def run(cmd, *args, **kwargs):
        if cmd[0] == "git":
            raise FileNotFoundError("git")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(cli.subprocess, "run", run)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    cli.main(["--format", "github-comment", "a.py"])
    assert "Analysis of" not in capsys.readouterr().out
