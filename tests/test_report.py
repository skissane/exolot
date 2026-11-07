import os
import sys
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


@pytest.mark.skipif(sys.platform == "win32", reason="Windows file names are always Unicode")
def test_artifact_location_quotes_a_path_that_is_not_utf8_as_its_bytes(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    path = tmp_path / os.fsdecode(b"bad\xff.py")
    assert report._artifact_location(path) == {"uri": "bad%FF.py", "uriBaseId": "%SRCROOT%"}
