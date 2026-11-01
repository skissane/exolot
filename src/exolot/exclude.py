"""Exclude globs: the files that --exclude and the config's `exclude` skip."""

from __future__ import annotations

import functools
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
    `/` or `./`) matches the path relative to base. `**` matches any number
    of directories, a match on a directory skips everything under it, and a
    trailing `/` matches only directories. There's no `!` negation."""

    pattern: str
    base: Path

    def matches(self, path: Path) -> bool:
        """Whether this glob skips path, an absolute file path."""
        pattern, anchored, dir_only = _normalize(_fold(self.pattern))
        if not pattern:
            return False
        parts = _relative_parts(path, self.base)
        if not anchored:
            # Outside base, only the file's own name is checked, so that its
            # parents above base don't count.
            names = parts if parts is not None else (_fold(path.name),)
            if dir_only:
                names = names[:-1]
            return any(fnmatchcase(name, pattern) for name in names)
        if parts is None:
            return False
        pattern_parts = tuple(pattern.split("/"))
        # The file itself, then each directory it's in.
        lengths = range(1, len(parts)) if dir_only else range(1, len(parts) + 1)
        return any(_match_parts(parts[:n], pattern_parts) for n in lengths)


def is_excluded(path: Path, excludes: list[Exclude] | tuple[Exclude, ...]) -> bool:
    """Whether any of excludes skips path, an absolute file path."""
    return any(exclude.matches(path) for exclude in excludes)


def _fold(text: str) -> str:
    """text in the case that matching compares."""
    return text.lower() if CASE_INSENSITIVE else text


def _relative_parts(path: Path, base: Path) -> tuple[str, ...] | None:
    """path's parts relative to base, case-folded, or None if it isn't under
    base. base is compared both as given and resolved, since path may be
    either."""
    parts = tuple(_fold(part) for part in path.parts)
    for b in (base.absolute(), base.resolve()):
        base_parts = tuple(_fold(part) for part in b.parts)
        if parts[: len(base_parts)] == base_parts:
            return parts[len(base_parts) :]
    return None


def _normalize(pattern: str) -> tuple[str, bool, bool]:
    """pattern without a leading `./` or `/` or a trailing `/` or `/**`;
    whether it's relative to base rather than matching names at any depth;
    and whether it matches only directories."""
    anchored = pattern.startswith("./")
    while pattern.startswith("./"):
        pattern = pattern[2:]
    dir_only = pattern.endswith("/")
    pattern = pattern.rstrip("/")
    anchored = anchored or "/" in pattern
    pattern = pattern.lstrip("/")
    # `dir/**` is everything under dir, which is the same as `dir/`.
    while pattern.endswith("/**"):
        pattern = pattern.removesuffix("/**")
        dir_only = True
    return pattern, anchored, dir_only


@functools.cache
def _match_parts(path_parts: tuple[str, ...], pattern_parts: tuple[str, ...]) -> bool:
    """Whether path_parts match pattern_parts, where `**` matches any number
    of parts. Cached, so that several `**`s don't take exponential time."""
    if not pattern_parts:
        return not path_parts
    pattern = pattern_parts[0]
    if pattern == "**":
        return any(_match_parts(path_parts[i:], pattern_parts[1:]) for i in range(len(path_parts) + 1))
    if not path_parts or not fnmatchcase(path_parts[0], pattern):
        return False
    return _match_parts(path_parts[1:], pattern_parts[1:])
