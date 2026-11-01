import json
import logging
from pathlib import Path

import pytest

from exolot import cli, problems
from exolot.analyze import AnalysisSession
from exolot.problems import PLUGIN_ACTIVE, PLUGIN_DOWNLOADING, PLUGIN_FAILED, PLUGIN_SYNCED, Problem
from tests.test_analyze import FakeServer
from tests.test_sarif import validate

STACK_TRACE = (
    "[Error - 15:45:54.733] [sonarlint : sonarlint-analysis-scheduler] java.lang.IllegalStateException: "
    "Unable to start OmniSharp\n"
    "\tat org.sonarsource.sonarlint.omnisharp.OmnisharpSensor.execute(OmnisharpSensor.java:100)\n"
    "Caused by: java.lang.IllegalStateException: Unable to start the Omnisharp server: "
    'Cannot run program "dotnet": Exec failed, error: 2 (No such file or directory) \n'
    "\tat org.sonarsource.sonarlint.omnisharp.OmnisharpServerController.lazyStart(OmnisharpServerController.java:184)\n"
    'Caused by: java.io.IOException: Cannot run program "dotnet": Exec failed, error: 2 (No such file or directory) \n'
    "\tat java.base/java.lang.ProcessBuilder.start(Unknown Source)\n"
    "Caused by: java.io.IOException: Exec failed, error: 2 (No such file or directory) \n"
    "\tat java.base/java.lang.ProcessImpl.forkAndExec(Native Method)\n"
    "\t... 28 more"
)


def test_failed_sensor():
    message = "[Error - 15:45:54.733] [sonarlint : sonarlint-analysis-scheduler] Error executing sensor: 'OmniSharp'"
    assert problems.failed_sensor(message) == "OmniSharp"
    assert problems.failed_sensor("[Error - 15:45:54.733] something else") is None


def test_stack_trace_reason_takes_the_root_cause_as_its_wrapper_gives_it():
    assert problems.is_stack_trace(STACK_TRACE)
    assert (
        problems.stack_trace_reason(STACK_TRACE)
        == 'Cannot run program "dotnet": Exec failed, error: 2 (No such file or directory)'
    )


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        # No cause: the exception's own message.
        (
            "[Error - 1] [x : y] java.lang.UnsupportedOperationException: no compile commands\n\tat a.B.c(B.java:1)",
            "no compile commands",
        ),
        # A root cause its wrapper doesn't repeat.
        ("a.B: outer\n\tat a.B.c\nCaused by: a.C: inner\n\tat a.C.d", "inner"),
        # No message: the exception's class name.
        ("[Error - 1] java.nio.channels.ClosedSelectorException\n\tat x.Y.z", "ClosedSelectorException"),
        # Not a Java exception.
        ("something odd\n\tat x", "something odd"),
        ("", None),
    ],
)
def test_stack_trace_reason(message, reason):
    assert problems.stack_trace_reason(message) == reason


def test_find_counts_each_file_towards_the_first_problem():
    files = {
        Path("a.c"): "c",
        Path("b.cpp"): "cpp",
        Path("c.cs"): "csharp",
        Path("d.py"): "python",
        Path("e.java"): "java",
        Path("f.txt"): "plaintext",
        Path("g.vue"): "vue",
    }
    states = {
        "JavaScript": PLUGIN_DOWNLOADING,
        "C": PLUGIN_DOWNLOADING,
        "C#": PLUGIN_ACTIVE,
        "Python": PLUGIN_SYNCED,
        "Java": PLUGIN_FAILED,
    }
    sensors = {"CFamily": "no database", "OmniSharp": None, "Mystery": "oops"}
    found = problems.find(files, states, sensors, needs_compilation_database=True, messages=["shown"])
    assert [(p.cause, p.reason, p.files) for p in found] == [
        ("the C analyzer couldn't be downloaded", "analyzer unavailable", [Path("a.c")]),
        ("the Java analyzer failed to load", "analyzer unavailable", [Path("e.java")]),
        ("the JavaScript analyzer couldn't be downloaded", "analyzer unavailable", [Path("g.vue")]),
        (
            "the C/C++/Objective-C analyzer needs a compilation database (compile_commands.json)",
            "no compilation database",
            [Path("b.cpp")],
        ),
        # CFamily's files are all counted already, so it's left out.
        ("the OmniSharp analyzer failed", "analyzer failed", [Path("c.cs")]),
        ("the Mystery analyzer failed (oops)", "analyzer failed", []),
        ("shown", "server message", []),
    ]


def test_find_with_nothing_wrong():
    assert (
        problems.find({Path("a.py"): "python"}, {"Python": PLUGIN_ACTIVE}, {}, needs_compilation_database=False) == []
    )


def test_problem_messages():
    problem = Problem("the C# analyzer failed", "analyzer failed", "C#", ("csharp",), [Path("a.cs"), Path("b.cs")])
    assert problem.message() == (
        "the C# analyzer failed, so 2 C# file(s) were not analyzed; use --log-level error for details"
    )
    assert problem.message(hint=False) == "the C# analyzer failed, so 2 C# file(s) were not analyzed"
    assert problem.sentence() == "The C# analyzer failed, so 2 C# file(s) were not analyzed."
    assert problem.summary() == "2 C# file(s) not analyzed (analyzer failed)"
    unknown = Problem("the X analyzer failed", "analyzer failed")
    assert unknown.sentence() == "The X analyzer failed, so some files may not have been analyzed."


def test_summary():
    cs = Problem("c", "analyzer failed", "C#", ("csharp",), [Path("a.cs")] * 3)
    c = Problem("c", "analyzer unavailable", "C", ("c",), [Path("a.c")])
    unknown = Problem("the X analyzer failed", "analyzer failed")
    assert problems.summary(0, 10, []) == "0 issue(s) in 10 file(s) analyzed"
    assert problems.summary(2, 10, [cs, c, unknown], changed=1) == (
        "2 issue(s), 1 on changed lines, in 6 file(s) analyzed; "
        "3 C# file(s) not analyzed (analyzer failed), 1 C file(s) not analyzed (analyzer unavailable), "
        "some files may not have been analyzed (the X analyzer failed)"
    )
    # A message the server showed is a warning, but not in the summary.
    shown = Problem("Node.js not found", "server message", may_affect_files=False)
    assert shown.message() == "Node.js not found"
    assert Problem("Done.", "server message", may_affect_files=False).sentence() == "Done."
    assert problems.summary(0, 10, [shown]) == "0 issue(s) in 10 file(s) analyzed"


def _session_files(tmp_path):
    files = []
    for name, text in [("a.py", "SENSORFAIL NEEDCDB SHOWMSG\n"), ("b.cs", "x\n"), ("c.c", "x\n"), ("d.js", "x\n")]:
        (tmp_path / name).write_text(text)
        files.append(tmp_path / name)
    return files


def test_session_finds_what_the_server_couldnt_analyze(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, "exolot.analyze")
    monkeypatch.setenv("FAKE_SERVER_PLUGIN_STATES", json.dumps({"JavaScript": PLUGIN_DOWNLOADING, "Python": 0}))
    files = _session_files(tmp_path)
    with AnalysisSession(FakeServer(root=tmp_path, java=Path("java")), tmp_path) as session:
        session.analyze(files, settle=0.2, timeout=10)
        found = session.unanalyzed(files)
    assert [(p.cause, [f.name for f in p.files]) for p in found] == [
        ("the JavaScript analyzer couldn't be downloaded", ["d.js"]),
        ("the C/C++/Objective-C analyzer needs a compilation database (compile_commands.json)", ["c.c"]),
        ('the OmniSharp analyzer failed (Cannot run program "dotnet": Exec failed, error: 2)', ["b.cs"]),
        # Errors and warnings the server shows the user are warnings too, on one line; other messages are info.
        ("message ::of type 1", []),
    ]
    shown = [(r.levelname, r.getMessage()) for r in caplog.records if r.name == "exolot.analyze"]
    assert ("INFO", "message ::of type 3") in shown


def test_session_goes_without_plugin_states_the_server_doesnt_give(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SERVER_PLUGIN_STATES", "fail")
    a = tmp_path / "a.js"
    a.write_text("x\n")
    with AnalysisSession(FakeServer(root=tmp_path, java=Path("java")), tmp_path) as session:
        session.analyze([a], settle=0.2, timeout=10)
        assert session.unanalyzed([a]) == []


def test_session_keeps_the_first_reason_a_sensor_failed_for(tmp_path):
    session = AnalysisSession(FakeServer(root=tmp_path, java=Path("java")), tmp_path)
    for message in [
        "Error executing sensor: 'S'",
        "a message between them",
        "a.B: first\n\tat x",
        "Error executing sensor: 'S'",
        "a.B: second\n\tat x",
        "a.B: a stack trace for no sensor\n\tat x",
    ]:
        session._on_log({"message": message})
    assert session._sensor_failures == {"S": "first"}


@pytest.fixture
def cli_files(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))
    monkeypatch.setenv("FAKE_SERVER_PLUGIN_STATES", json.dumps({"C#": PLUGIN_DOWNLOADING}))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("x\n")
    (tmp_path / "b.cs").write_text("x\n")
    (tmp_path / "c.cs").write_text("x\n")
    return ["a.py", "b.cs", "c.cs"]


WARNING = "the C# analyzer couldn't be downloaded, so 2 C# file(s) were not analyzed"
SUMMARY = "in 1 file(s) analyzed; 2 C# file(s) not analyzed (analyzer unavailable)"


def test_cli_warns_about_files_not_analyzed(cli_files, capsys):
    cli.main(cli_files)
    err = capsys.readouterr().err
    assert f"exolot: warning: {WARNING}; use --log-level error for details\n" in err
    assert f"3 issue(s) {SUMMARY}" in err


def test_cli_shows_server_messages_when_analysis_fails(cli_files, capsys, tmp_path):
    (tmp_path / "busy.py").write_text("SHOWMSG BUSY\n")
    assert cli.main(["--timeout", "2", "busy.py"]) == 2
    err = capsys.readouterr().err
    assert "exolot: warning: message ::of type 1\n" in err
    assert "did not finish in time" in err


def test_cli_warns_without_the_hint_when_showing_the_servers_log(cli_files, capsys):
    cli.main(["--log-level", "error", *cli_files])
    err = capsys.readouterr().err
    assert f"exolot: warning: {WARNING}\n" in err
    assert f"3 issue(s) {SUMMARY}" in err


@pytest.mark.parametrize("flags", [["--format", "markdown"], ["--format", "markdown", "--statistics"]])
def test_cli_markdown_warns_about_files_not_analyzed(cli_files, capsys, flags):
    cli.main([*flags, *cli_files])
    captured = capsys.readouterr()
    assert captured.out.startswith(f"> [!WARNING]\n> - T{WARNING[1:]}.\n\n|")
    assert SUMMARY in captured.err


def test_cli_github_comment_warns_about_files_not_analyzed(cli_files, capsys):
    cli.main(["--format", "github-comment", *cli_files])
    captured = capsys.readouterr()
    assert f"> [!WARNING]\n> - T{WARNING[1:]}.\n\n### Findings" in captured.out
    assert SUMMARY in captured.err


@pytest.mark.parametrize("flags", [[], ["--statistics"]])
def test_cli_text_and_statistics_summaries(cli_files, capsys, flags):
    cli.main([*flags, *cli_files])
    assert SUMMARY in capsys.readouterr().err


def test_cli_annotations_put_files_not_analyzed_first(cli_files, capsys):
    cli.main(["--annotations", *cli_files])
    lines = [line for line in capsys.readouterr().err.splitlines() if line.startswith("::")]
    assert lines[0] == f"::warning title=exolot::T{WARNING[1:]}."
    assert len(lines) == 4  # then one issue for each file
    assert all(line.startswith("::warning file=") for line in lines[1:])


def test_cli_sarif_warns_about_files_not_analyzed(cli_files, capsys):
    cli.main(["--format", "sarif", *cli_files])
    captured = capsys.readouterr()
    log = json.loads(captured.out)
    validate(log)
    (invocation,) = log["runs"][0]["invocations"]
    assert invocation == {
        "executionSuccessful": True,
        "toolExecutionNotifications": [{"level": "warning", "message": {"text": f"T{WARNING[1:]}."}}],
    }
    assert SUMMARY in captured.err
