"""End-to-end test against the real language server.

Downloads the server (about 250 MB) on first run, so it only runs when
EXOLOT_INTEGRATION=1.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from functools import partialmethod
from pathlib import Path

import pytest

from exolot import cli, rules
from exolot.analyze import AnalysisSession
from exolot.server import ensure_server

pytestmark = pytest.mark.skipif(os.environ.get("EXOLOT_INTEGRATION") != "1", reason="set EXOLOT_INTEGRATION=1")


@pytest.fixture(autouse=True)
def patient_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the server 300 quiet seconds rather than 30 before deciding it
    will never report a file's results. The tests run in parallel, each
    starting its own server (test_concurrent_sessions_all_start four), and
    on a small CI runner that many JVMs starting at once can keep a server
    quiet for longer than 30 seconds."""
    monkeypatch.setattr(AnalysisSession, "analyze", partialmethod(AnalysisSession.analyze, stall=300))


def test_finds_python_issue(tmp_path: Path) -> None:
    source = tmp_path / "bad.py"
    source.write_text("def f(x):\n    if x == x:\n        pass\n")
    with AnalysisSession(ensure_server(progress=False), tmp_path) as session:
        issues = session.analyze([source], timeout=300)
        names = session.rule_names()
    assert "python:S1764" in {i.rule for i in issues}
    assert names["python:S1764"] == "Identical expressions should not be used on both sides of a binary operator"


def test_finds_secondary_locations(tmp_path: Path) -> None:
    source = tmp_path / "bad.py"
    source.write_text("def f(x):\n    if x == x:\n        pass\n")
    with AnalysisSession(ensure_server(progress=False), tmp_path) as session:
        issues = session.analyze([source], timeout=300)
        session.add_related_locations(issues)
    (issue,) = [i for i in issues if i.rule == "python:S1764"]
    assert issue.message == 'Correct one of the identical sub-expressions on both sides of operator "==".'
    assert [(loc.path, loc.line, loc.column, loc.end_line, loc.end_column) for loc in issue.related] == [
        (source, 2, 8, 2, 9)
    ]


def test_rule_settings_turn_rules_off_and_set_parameters(tmp_path: Path) -> None:
    source = tmp_path / "bad.py"
    source.write_text("def f(x, y):\n    if x == x:\n        pass\n")
    # S107 (too many parameters) allows 13 by default.
    with AnalysisSession(ensure_server(progress=False), tmp_path) as session:
        default = {i.rule for i in session.analyze([source], timeout=300)}
    assert "python:S1764" in default
    assert "python:S107" not in default
    rule_settings = rules.check(
        {"python:S1764": {"level": "off"}, "python:S107": {"level": "on", "parameters": {"max": 1}}}, "test"
    )
    with AnalysisSession(ensure_server(progress=False), tmp_path, rules=rule_settings) as session:
        configured = {i.rule for i in session.analyze([source], timeout=300)}
    assert "python:S1764" not in configured
    assert "python:S107" in configured


# Cognitive complexity 1 (simple) and 6 (nested: 1 + 2 + 3).
COMPLEXITY = """\
def simple(a):
    if a:
        return 1
    return 0


def nested(a, b, c):
    if a:
        if b:
            if c:
                return 1
    return 0
"""


@pytest.mark.parametrize(
    ("threshold", "expected"),
    [(0, {"simple", "nested"}), (3, {"nested"}), (10, set())],
)
def test_rule_parameter_sets_the_complexity_threshold(tmp_path: Path, threshold: int, expected: set[str]) -> None:
    source = tmp_path / "complexity.py"
    source.write_text(COMPLEXITY)
    lines = {1: "simple", 7: "nested"}
    rule_settings = rules.check({"python:S3776": {"level": "on", "parameters": {"threshold": threshold}}}, "test")
    with AnalysisSession(ensure_server(progress=False), tmp_path, rules=rule_settings) as session:
        issues = session.analyze([source], timeout=300)
    assert {lines[i.line] for i in issues if i.rule == "python:S3776"} == expected


def test_concurrent_sessions_all_start(tmp_path: Path) -> None:
    # Servers sharing one SONARLINT_USER_HOME race on its database's lock,
    # and the losers fail to initialize (issue #100).
    server = ensure_server(progress=False)

    def analyze(n: int) -> set[str]:
        workspace = tmp_path / f"w{n}"
        workspace.mkdir()
        source = workspace / "bad.py"
        source.write_text("def f(x):\n    if x == x:\n        pass\n")
        with AnalysisSession(server, workspace) as session:
            return {i.rule for i in session.analyze([source], timeout=300)}

    with ThreadPoolExecutor(4) as pool:
        found = list(pool.map(analyze, range(4)))
    assert all("python:S1764" in rules_found for rules_found in found)


def test_select_and_rule_param(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "bad.py"
    source.write_text("def f(x, y):\n    if x == x:\n        pass\n")
    rules_file = tmp_path / "rules.json"
    rules_file.write_text('{"python:S1764": {"level": "off"}}')
    # S1764 is on by default but off in the settings, and S107 (too many parameters) allows 13
    # parameters unless --rule-param lowers its max.
    args = ["--rules", str(rules_file), "--select", "python:S1764,python:S107", "--rule-param", "python:S107.max=1"]
    args += ["--format", "json", str(source)]
    assert cli.main(args) == 1
    captured = capsys.readouterr()
    assert sorted(issue["rule"] for issue in json.loads(captured.out)) == ["python:S107", "python:S1764"]
    # The server lists every rule, not only those on by default, so --select doesn't warn about them.
    assert "warning: --select" not in captured.err
