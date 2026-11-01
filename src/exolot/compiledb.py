"""Find the compilation database (compile_commands.json) that the server's
C/C++ analyzer needs: without one, it fails rather than analyze C, C++ and
Objective-C files."""

from __future__ import annotations

from pathlib import Path

NAME = "compile_commands.json"
# Where to look in each directory: the directory itself (e.g. made by
# `bear -- make`), then CMake's usual build directory.
CANDIDATES = (Path(NAME), Path("build") / NAME)


def find(paths: list[Path]) -> list[Path]:
    """The compilation databases for paths (files or directories to
    analyze): for each one, the nearest in it or its parents (see CANDIDATES),
    but no higher than the git repository it's in. Each database once, in
    the order found."""
    found: dict[Path, None] = {}
    for path in paths:
        path = path.resolve()
        database = _nearest(path if path.is_dir() else path.parent)
        if database is not None:
            found[database] = None
    return list(found)


def _nearest(start: Path) -> Path | None:
    for d in (start, *start.parents):
        for candidate in CANDIDATES:
            if (d / candidate).is_file():
                return d / candidate
        if (d / ".git").exists():
            return None
    return None
