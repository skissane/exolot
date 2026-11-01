"""Find the compilation database (compile_commands.json) that the server's
C/C++ analyzer needs: without one, it fails rather than analyze C, C++ and
Objective-C files."""

from __future__ import annotations

from pathlib import Path

NAME = "compile_commands.json"
# Where to look in each directory: the directory itself (e.g. made by
# `bear -- make`), then CMake's usual build directory.
CANDIDATES = (Path(NAME), Path("build") / NAME)


def find(files: list[Path]) -> dict[Path | None, list[Path]]:
    """The compilation database for each of files, with the files it's for:
    the nearest one in the file's directory or the directories above it (see
    CANDIDATES), but no higher than the git repository it's in. None maps to
    the files without one."""
    # Many files share directories, so look in each directory only once.
    nearest: dict[Path, Path | None] = {}

    def lookup(directory: Path) -> Path | None:
        if directory not in nearest:
            # Resolved, as e.g. a compile_commands.json symlink to the one in
            # build/ is the same database.
            here = next(((directory / c).resolve() for c in CANDIDATES if (directory / c).is_file()), None)
            at_top = (directory / ".git").exists() or directory.parent == directory
            nearest[directory] = here or (None if at_top else lookup(directory.parent))
        return nearest[directory]

    found: dict[Path | None, list[Path]] = {}
    for path in files:
        found.setdefault(lookup(path.resolve().parent), []).append(path)
    return found
