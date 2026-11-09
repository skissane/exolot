"""Runs each script's ``if __name__ == "__main__":`` block, and exolot's
``__main__.py``, as ``python -m`` would, so that coverage measures them and a
mistake there (e.g. passing ``sys.argv`` rather than ``sys.argv[1:]``, or
dropping ``main()``'s exit code) fails a test.

Each case picks arguments for which ``main()`` returns rather than exits
itself (as argparse's ``--help`` does), so the guard's own lines run, and
which need no network.
"""

import io
import json
import runpy
import sys
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from exolot.server import cache_dir

ROOT = Path(__file__).parent.parent


def run_as_main(monkeypatch: pytest.MonkeyPatch, module: str, *args: str) -> object:
    """Runs ``python -m module args...`` in this process, returning its exit
    code (``None`` if it didn't raise ``SystemExit``)."""
    monkeypatch.setattr(sys, "argv", [module, *args])
    # The tests have already imported most of these; run_module warns about
    # running a module that's in sys.modules. monkeypatch puts it back after.
    monkeypatch.delitem(sys.modules, module, raising=False)
    try:
        runpy.run_module(module, run_name="__main__")
    except SystemExit as e:
        return e.code
    return None


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("scripts.check_pins", "workflows and actions pin uv "),
        ("scripts.check_checkout_credentials", "actions/checkout steps set persist-credentials"),
    ],
)
def test_workflow_checks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], module: str, expected: str
) -> None:
    # They check the workflows in the current directory: this repo's.
    monkeypatch.chdir(ROOT)
    assert run_as_main(monkeypatch, module) == 0
    assert expected in capsys.readouterr().out


@pytest.mark.parametrize(
    ("module", "args"),
    [
        ("scripts.post_patch_coverage", ["1", "--report"]),
        ("scripts.self_analysis", ["1"]),
    ],
)
def test_comment_posters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    module: str,
    args: list[str],
) -> None:
    # A missing report fails before anything talks to GitHub.
    assert run_as_main(monkeypatch, module, *args, str(tmp_path / "missing.md")) == 1
    assert "missing.md" in capsys.readouterr().err


def test_claude_review_request(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("@claude review"))
    assert run_as_main(monkeypatch, "scripts.claude_review_request") == 0
    assert capsys.readouterr().out == "review\n"


def test_check_attestations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # An empty directory has no distributions, so it fails without any.
    assert run_as_main(monkeypatch, "scripts.check_attestations", str(tmp_path)) == 1
    assert "No distributions found" in capsys.readouterr().out


def test_wait_for_base_coverage(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def urlopen(request: urllib.request.Request, **kwargs: Any) -> io.BytesIO:
        assert request.full_url.startswith("https://api.codecov.io/")
        response = io.BytesIO(json.dumps({"totals": {"coverage": 98.5}}).encode())
        response.status = 200  # type: ignore[attr-defined]
        return response

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    # Its guard calls main() without SystemExit, so there's no exit code.
    assert run_as_main(monkeypatch, "scripts.wait_for_base_coverage", "o/r", "abc") is None
    assert "Codecov has the base report for abc (coverage 98.5%)" in capsys.readouterr().out


def test_exolot(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_as_main(monkeypatch, "exolot", "cache-dir") == 0
    assert capsys.readouterr().out == f"{cache_dir()}\n"
