import sys
from pathlib import Path

import pytest

from exolot import exclude
from exolot.exclude import Exclude, is_empty, is_excluded

BASE = Path("/repo").resolve()
FILE = BASE / "vendor" / "lib" / "a.py"


@pytest.mark.parametrize(
    ("pattern", "skipped"),
    [
        # A name without a slash matches the file or any directory it's in.
        ("a.py", True),
        ("*.py", True),
        ("vendor", True),
        ("lib", True),
        ("*.m", False),
        # A trailing slash matches only directories.
        ("vendor/", True),
        ("a.py/", False),
        # A slash makes it relative to the base, matching directories too.
        ("vendor/lib", True),
        ("vendor/*", True),
        ("vendor/**", True),
        ("vendor/**/*.py", True),
        ("**/lib/*.py", True),
        ("lib/*", False),
        ("lib/**", False),
        ("./vendor", True),
        ("./vendor/**", True),
        ("./lib", False),
        ("vendor/lib/a.py/**", False),
        ("vendor/lib/**/**", True),
        ("/vendor", True),
        ("/lib", False),
        ("vendor/lib/a.py/", False),
        # Nothing to match.
        ("", False),
        ("/", False),
        ("./", False),
        # No negation: `!` is just a character.
        ("!a.py", False),
    ],
)
def test_matches(pattern: str, skipped: bool) -> None:
    assert Exclude(pattern, BASE).matches(FILE) is skipped


def test_paths_outside_the_base_match_only_by_file_name() -> None:
    outside = BASE.parent / "other" / "vendor" / "a.py"
    assert Exclude("*.py", BASE).matches(outside)
    assert not Exclude("vendor", BASE).matches(outside)
    assert not Exclude("other/**", BASE).matches(outside)


@pytest.mark.parametrize("insensitive", [True, False])
def test_case(monkeypatch: pytest.MonkeyPatch, insensitive: bool) -> None:
    monkeypatch.setattr(exclude, "CASE_INSENSITIVE", insensitive)
    assert Exclude("VENDOR/**", BASE).matches(FILE) is insensitive
    assert Exclude("*.PY", BASE).matches(FILE) is insensitive
    assert Exclude("*.py", BASE).matches(BASE.parent / "A.PY") is insensitive


def test_is_excluded() -> None:
    assert is_excluded(FILE, [Exclude("*.m", BASE), Exclude("lib", BASE)])
    assert not is_excluded(FILE, [Exclude("*.m", BASE)])
    assert not is_excluded(FILE, [])


def test_dir_glob_doesnt_match_a_file_of_that_name() -> None:
    assert not Exclude("foo/**", BASE).matches(BASE / "foo")
    assert Exclude("foo/**", BASE).matches(BASE / "foo" / "bar")


def test_base_case_is_folded_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(exclude, "CASE_INSENSITIVE", True)
    assert Exclude("vendor/**", BASE.parent / "REPO").matches(FILE)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_unresolved_base(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    target = (tmp_path / "real" / "vendor" / "a.py").resolve()
    assert Exclude("vendor/**", tmp_path / "link").matches(target)


def test_many_double_stars_stay_fast() -> None:
    deep = BASE.joinpath(*["d"] * 40, "a.py")
    assert not Exclude("/".join(["**", "d"] * 10) + "/x/**", BASE).matches(deep)


@pytest.mark.parametrize(
    ("pattern", "empty"), [("", True), ("/", True), ("./", True), ("//", True), ("a", False), ("/a/", False)]
)
def test_is_empty(pattern: str, empty: bool) -> None:
    assert is_empty(pattern) is empty
