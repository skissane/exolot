import os
from pathlib import Path
from typing import NoReturn

import pytest

from exolot import report


def test_display_path_on_another_drive_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    def relpath(path: str, start: str | None = None) -> NoReturn:
        # What Windows does when path and the current directory are on different drives.
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(os.path, "relpath", relpath)
    path = Path("D:/src/a.py")
    assert report.display_path(path) == str(path)
