"""End-to-end test against the real language server.

Downloads the server (about 250 MB) on first run, so it only runs when
EXOLOT_INTEGRATION=1.
"""

import os
from pathlib import Path

import pytest

from exolot import rules
from exolot.analyze import AnalysisSession
from exolot.server import ensure_server

pytestmark = pytest.mark.skipif(os.environ.get("EXOLOT_INTEGRATION") != "1", reason="set EXOLOT_INTEGRATION=1")


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
