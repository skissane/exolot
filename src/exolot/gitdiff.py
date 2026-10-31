"""The lines a change adds or modifies, for --diff-base: like SonarQube's "new
code", the findings on them are the ones a change introduces or touches."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_HUNK_RE = re.compile(r"^@@ -\d+(?:,(?P<old>\d+))? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")
# The escapes in the C-style quoted paths git gives for names with control
# characters, double quotes or backslashes in them.
_ESCAPE_RE = re.compile(r"\\([0-7]{1,3}|.)")
_ESCAPES = {"a": "\a", "b": "\b", "t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r"}


class GitError(Exception):
    """git isn't installed, or couldn't work out the changes."""


@dataclass
class Changes:
    """The changed lines of each file, by absolute (resolved) path. A file
    git doesn't track yet is new, so all of its lines count as changed."""

    lines: dict[Path, set[int]] = field(default_factory=dict)
    new_files: set[Path] = field(default_factory=set)

    def touches(self, path: Path, line: int, end_line: int | None = None) -> bool:
        """Whether any of the lines from line to end_line (default: just line)
        of path (as collect_files gives it: resolved) is changed."""
        if path in self.new_files:
            return True
        changed = self.lines.get(path, ())
        return any(n in changed for n in range(line, max(line, end_line or line) + 1))

    def files(self) -> set[Path]:
        """The files with changed lines."""
        return set(self.lines) | self.new_files


def changes_since(base: str, cwd: Path | None = None) -> Changes:
    """The lines added or modified in the working tree of the git repository
    cwd (default: the current directory) is in, since the merge base of base
    and HEAD: committed or not, plus the files git doesn't track yet (and
    doesn't ignore). Raises GitError if git fails, e.g. base doesn't name a
    commit or, in a shallow clone, the merge base hasn't been fetched."""
    toplevel = _git(["rev-parse", "--show-toplevel"], cwd, "not in a git repository")
    root = Path(toplevel.removesuffix("\n")).resolve()
    _git(["rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"], root, f"can't find commit {base!r}")
    merge_base = _git(
        ["merge-base", base, "HEAD"],
        root,
        f"can't find the merge base of {base!r} and HEAD (in a shallow clone, fetch more history)",
    ).strip()
    diff = _git(
        [
            "diff",
            # Whatever the user's diff.interHunkContext, so there are no
            # context lines.
            "--unified=0",
            "--inter-hunk-context=0",
            "--no-color",
            # The files' own lines, not what a textconv driver makes of them.
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            # Whatever the user's diff.noprefix or diff.mnemonicPrefix.
            "--src-prefix=a/",
            "--dst-prefix=b/",
            merge_base,
            "--",
        ],
        root,
        "git diff failed",
    )
    untracked = _git(["ls-files", "-z", "--others", "--exclude-standard"], root, "git ls-files failed")
    return Changes(
        lines={(root / path).resolve(): lines for path, lines in parse_diff(diff).items()},
        new_files={(root / path).resolve() for path in untracked.split("\0") if path},
    )


def _git(args: list[str], cwd: Path | None, what: str) -> str:
    # core.quotePath=false, so paths with non-ASCII characters come out as they are.
    cmd = ["git", "-c", "core.quotePath=false", *args]
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, encoding="utf-8", errors="surrogateescape")
    except FileNotFoundError:
        raise GitError("--diff-base needs git, which isn't installed") from None
    if proc.returncode != 0:
        detail = proc.stderr.strip()
        raise GitError(f"{what}: {detail}" if detail else what)
    return proc.stdout


def parse_diff(diff: str) -> dict[str, set[int]]:
    """The lines of each file, by its path in the diff, that a
    `git diff --unified=0` adds or modifies."""
    lines: dict[str, set[int]] = {}
    path = None
    # Lines left in the current hunk, which can look like headers: a removed
    # "-- x" shows as "--- x" and an added "++ x" as "+++ x".
    in_hunk = 0
    for line in diff.splitlines():
        if in_hunk and line[:1] in ("+", "-"):
            in_hunk -= 1
        elif line.startswith("+++ "):
            # Git ends the header with a tab when the path has a space in it.
            target = line[4:]
            target = _unquote(target) if target.startswith('"') else target.split("\t", 1)[0]
            path = target[2:] if target.startswith("b/") else None
        elif m := _HUNK_RE.match(line):
            start = int(m["start"])
            count = 1 if m["count"] is None else int(m["count"])
            in_hunk = (1 if m["old"] is None else int(m["old"])) + count
            if path is not None:
                lines.setdefault(path, set()).update(range(start, start + count))
    return lines


def _unquote(quoted: str) -> str:
    """A path as git quotes it ("b/a\\tb"), unquoted. With core.quotePath
    off, git escapes only ASCII characters, so each octal escape is one."""
    return _ESCAPE_RE.sub(
        lambda m: chr(int(m[1], 8)) if m[1][0].isdigit() else _ESCAPES.get(m[1], m[1]),
        quoted[1 : quoted.rindex('"')],
    )
