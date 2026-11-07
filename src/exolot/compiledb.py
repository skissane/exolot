"""Find the compilation database (compile_commands.json) that the server's
C/C++ analyzer needs: without one, it fails rather than analyze C, C++ and
Objective-C files."""

from __future__ import annotations

import logging
from pathlib import Path

from . import problems
from .files import language_id

log = logging.getLogger(__name__)

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


def choose(files: list[Path]) -> tuple[Path | None, problems.Problem | None]:
    """The compilation database for the C, C++ and Objective-C files among
    files, found as find does, and the Problem saying why the server won't
    be sent those it isn't for, if there are any. The server takes one
    database for the workspace, so if more than one is found, it's for none
    of them."""
    label, languages = problems.CFAMILY
    cfamily = [f for f in files if language_id(f) in languages]
    if not cfamily:
        return None, None
    found = find(cfamily)
    skipped = found.pop(None, [])
    database = None
    if len(found) > 1:
        skipped = cfamily
        cause = (
            f"there's more than one compilation database ({', '.join(map(str, found))}); "
            "choose one with --compile-commands"
        )
    else:
        # For these files, if another database is used for the others.
        where = " for some files" if found else ""
        cause = (
            f"no compilation database ({NAME}) was found{where}; make one, e.g. with bear or CMake, "
            "or pass --compile-commands"
        )
        if found:
            (database,) = found
            log.info("using the compilation database %s", database)
    if not skipped:
        return database, None
    return database, problems.Problem(
        cause, "no compilation database", label, languages, files=skipped, in_server_log=False
    )
