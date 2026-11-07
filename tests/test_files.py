import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import pytest

from exolot import files
from exolot.exclude import Exclude
from exolot.files import collect_files, language_id


def test_language_id() -> None:
    assert language_id(Path("a.py")) == "python"
    assert language_id(Path("A.TSX")) == "typescriptreact"
    assert language_id(Path("Dockerfile")) == "dockerfile"
    assert language_id(Path("notes.txt")) == "plaintext"


def test_collect_files_skips_binary_and_ignored(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "blob.bin").write_bytes(b"\0\1\2")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("x\n")
    files = collect_files([tmp_path])
    assert files == [(tmp_path / "a.py").resolve()]


def test_collect_files_respects_gitignore(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("ignored.py\n")
    (tmp_path / "ignored.py").write_text("x = 1\n")
    (tmp_path / "kept.py").write_text("x = 1\n")
    names = {f.name for f in collect_files([tmp_path])}
    assert names == {".gitignore", "kept.py"}


def test_collect_files_excludes_by_filename_glob(tmp_path: Path) -> None:
    (tmp_path / "a.m").write_text("x = 1\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.m").write_text("x = 1\n")
    (tmp_path / "sub" / "kept.py").write_text("x = 1\n")
    files = collect_files([tmp_path], exclude=[Exclude("*.m", tmp_path)])
    assert files == [(tmp_path / "sub" / "kept.py").resolve()]


def test_collect_files_excludes_by_relative_path_glob(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "gen").mkdir()
    (tmp_path / "gen" / "skip.py").write_text("x = 1\n")
    (tmp_path / "sub" / "gen").mkdir(parents=True)
    (tmp_path / "sub" / "gen" / "keep.py").write_text("x = 1\n")
    monkeypatch.chdir(tmp_path)
    files = collect_files([tmp_path], exclude=[Exclude("gen/**", tmp_path)])
    assert files == [(tmp_path / "sub" / "gen" / "keep.py").resolve()]


def test_collect_files_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        collect_files([tmp_path / "nope"])


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_collect_files_excludes_symlinks_by_their_listed_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("x = 1\n")
    (tmp_path / "proj" / "vendor").mkdir(parents=True)
    (tmp_path / "proj" / "vendor" / "link.py").symlink_to(outside)
    (tmp_path / "proj" / "kept.py").write_text("x = 1\n")
    monkeypatch.chdir(tmp_path / "proj")
    files = collect_files([Path()], [Exclude("vendor/**", tmp_path / "proj")])
    assert files == [(tmp_path / "proj" / "kept.py").resolve()]


def test_collect_files_walks_directories_without_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    (tmp_path / "a.py").write_text("x = 1\n")
    for skipped in (".hidden", "node_modules"):
        (tmp_path / skipped).mkdir()
        (tmp_path / skipped / "b.py").write_text("x = 1\n")
    assert collect_files([tmp_path]) == [(tmp_path / "a.py").resolve()]


def test_collect_files_skips_files_that_are_too_big(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(files, "MAX_FILE_SIZE", 4)
    (tmp_path / "big.py").write_text("x = 1\n")
    (tmp_path / "ok.py").write_text("x\n")
    assert collect_files([tmp_path]) == [(tmp_path / "ok.py").resolve()]


def test_collect_files_skips_files_it_cannot_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unreadable(*args: object, **kwargs: object) -> NoReturn:
        raise PermissionError("denied")

    (tmp_path / "a.py").write_text("x = 1\n")
    monkeypatch.setattr(files, "open", unreadable, raising=False)
    assert collect_files([tmp_path]) == []


@pytest.mark.skipif(sys.platform == "win32", reason="Windows file names are always Unicode")
def test_collect_files_finds_files_whose_names_are_not_utf8(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    path = tmp_path / os.fsdecode(b"bad\xff.py")
    try:
        path.write_text("x = 1\n")
    except OSError:  # e.g. EILSEQ on macOS
        pytest.skip("this filesystem only allows UTF-8 file names")
    assert collect_files([tmp_path]) == [path.resolve()]
