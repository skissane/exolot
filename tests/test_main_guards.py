"""Runs exolot's ``__main__.py`` as ``python -m`` would, so that coverage
measures it and a mistake there (e.g. passing ``sys.argv`` rather than
``sys.argv[1:]``, or dropping ``main()``'s exit code) fails a test.

It picks arguments for which ``main()`` returns rather than exits itself (as
argparse's ``--help`` does), so the guard's own lines run, and which need no
network.
"""

import runpy
import sys

import pytest

from exolot.server import cache_dir


def run_as_main(monkeypatch: pytest.MonkeyPatch, module: str, *args: str) -> object:
    """Runs ``python -m module args...`` in this process, returning its exit
    code (``None`` if it didn't raise ``SystemExit``)."""
    monkeypatch.setattr(sys, "argv", [module, *args])
    # The tests have already imported it; run_module warns about
    # running a module that's in sys.modules. monkeypatch puts it back after.
    monkeypatch.delitem(sys.modules, module, raising=False)
    try:
        runpy.run_module(module, run_name="__main__")
    except SystemExit as e:
        return e.code
    return None


def test_exolot(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_as_main(monkeypatch, "exolot", "cache-dir") == 0
    assert capsys.readouterr().out == f"{cache_dir()}\n"
