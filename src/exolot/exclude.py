"""Exclude globs: the files that --exclude and the config's `exclude` skip."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

# File names are case-insensitive by default on macOS and Windows, so globs are too.
CASE_INSENSITIVE = sys.platform in ("darwin", "win32")


@dataclass(frozen=True)
class Exclude:
    """One exclude glob and the directory it's relative to: the current
    directory for --exclude, the config file's directory for the config's.

    Like .gitignore: a glob with no `/` (other than a trailing one) matches a
    file or directory name at any depth; one with a `/` (such as a leading
    one) matches the path relative to base. A leading `./` is dropped, `**`
    matches any number of directories, a match on a directory skips
    everything under it, and a trailing `/` matches only directories."""

    pattern: str
    base: Path

    def matches(self, path: Path) -> bool:
        """Whether this glob skips path, an absolute, resolved file path."""
        pattern, anchored, dir_only = _normalize(self.pattern)
        if not pattern:
            return False
        try:
            parts = list(path.relative_to(self.base.resolve()).parts)
        except ValueError:
            parts = None
        if CASE_INSENSITIVE:
            pattern = pattern.lower()
            parts = None if parts is None else [p.lower() for p in parts]
        if not anchored:
            # Outside base, only the file's own name is checked, so that its
            # parents above base don't count.
            names = parts if parts is not None else [path.name.lower() if CASE_INSENSITIVE else path.name]
            if dir_only:
                names = names[:-1]
            return any(fnmatchcase(name, pattern) for name in names)
        if parts is None:
            return False
        pattern_parts = pattern.split("/")
        # The file itself, then each directory it's in.
        lengths = range(1, len(parts)) if dir_only else range(1, len(parts) + 1)
        return any(_match_parts(parts[:n], pattern_parts) for n in lengths)


def is_excluded(path: Path, excludes: list[Exclude] | tuple[Exclude, ...]) -> bool:
    """Whether any of excludes skips path, an absolute, resolved file path."""
    return any(exclude.matches(path) for exclude in excludes)


def _normalize(pattern: str) -> tuple[str, bool, bool]:
    """pattern without a leading `./` or `/` or a trailing `/`; whether it's
    relative to base rather than matching names at any depth; and whether
    it matches only directories."""
    while pattern.startswith("./"):
        pattern = pattern[2:]
    dir_only = pattern.endswith("/")
    pattern = pattern.rstrip("/")
    anchored = "/" in pattern
    return pattern.lstrip("/"), anchored, dir_only


def _match_parts(path_parts: list[str], pattern_parts: list[str]) -> bool:
    if not pattern_parts:
        return not path_parts
    pattern = pattern_parts[0]
    if pattern == "**":
        return any(_match_parts(path_parts[i:], pattern_parts[1:]) for i in range(len(path_parts) + 1))
    if not path_parts or not fnmatchcase(path_parts[0], pattern):
        return False
    return _match_parts(path_parts[1:], pattern_parts[1:])
