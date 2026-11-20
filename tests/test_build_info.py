import json
from pathlib import Path

import pytest

from exolot import __version__, build_info, cli


def _use_package_dir(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    monkeypatch.setattr(build_info, "files", lambda package: directory)


def test_read_without_file_is_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_package_dir(monkeypatch, tmp_path)
    assert build_info.read() == build_info.UNKNOWN


def test_read_source_checkout_is_unknown() -> None:
    # Tests run from an editable install, which the hook gives no file.
    assert build_info.read() == build_info.UNKNOWN


@pytest.mark.parametrize("dirty", [False, True])
def test_read_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dirty: bool) -> None:
    (tmp_path / build_info.FILE).write_text(json.dumps({"commit": "a" * 40, "dirty": dirty}))
    _use_package_dir(monkeypatch, tmp_path)
    assert build_info.read() == build_info.BuildInfo("a" * 40, dirty)


@pytest.mark.parametrize(
    "content",
    [
        '{"commit": null, "dirty": null}',
        '{"commit": "", "dirty": "no"}',
        "{}",
        "[]",
        "not json",
    ],
)
def test_read_unknown_or_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    (tmp_path / build_info.FILE).write_text(content)
    _use_package_dir(monkeypatch, tmp_path)
    assert build_info.read() == build_info.UNKNOWN


def test_describe() -> None:
    commit = "0123456789abcdef" + "0" * 24
    assert build_info.describe("1.2.3", build_info.UNKNOWN) == "exolot 1.2.3"
    assert build_info.describe("1.2.3", build_info.BuildInfo(commit, False)) == "exolot 1.2.3 (0123456789ab)"
    assert build_info.describe("1.2.3", build_info.BuildInfo(commit, None)) == "exolot 1.2.3 (0123456789ab)"
    assert (
        build_info.describe("1.2.3", build_info.BuildInfo(commit, True))
        == "exolot 1.2.3 (0123456789ab with uncommitted changes)"
    )


def test_version_flag_shows_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / build_info.FILE).write_text(json.dumps({"commit": "b" * 40, "dirty": False}))
    _use_package_dir(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"exolot {__version__} ({'b' * 12})\n"
