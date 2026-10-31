"""End-to-end test against the real language server.

Downloads the server (about 250 MB) on first run, so it only runs when
EXOLOT_INTEGRATION=1.
"""

import os

import pytest

from exolot.analyze import AnalysisSession
from exolot.server import ensure_server

pytestmark = pytest.mark.skipif(os.environ.get("EXOLOT_INTEGRATION") != "1", reason="set EXOLOT_INTEGRATION=1")


def test_finds_python_issue(tmp_path):
    source = tmp_path / "bad.py"
    source.write_text("def f(x):\n    if x == x:\n        pass\n")
    with AnalysisSession(ensure_server(progress=False), tmp_path) as session:
        issues = session.analyze([source], timeout=300)
        names = session.rule_names()
    assert "python:S1764" in {i.rule for i in issues}
    assert names["python:S1764"] == "Identical expressions should not be used on both sides of a binary operator"
