"""Shallow-cloning a git repository for the analyze-repo command."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# github.com repository URLs, over HTTPS or SSH, with or without ".git".
_GITHUB_URL = re.compile(
    r"(?:https://(?:[^@/]+@)?github\.com/|ssh://git@github\.com/|git@github\.com:)"
    r"(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?",
    re.IGNORECASE,
)


class CloneError(Exception):
    """git isn't installed, or couldn't fetch the repository or ref."""


def clone(source: str, dest: Path, ref: str | None = None) -> str:
    """Fetch ref (a branch, tag or full commit SHA; default: the remote's
    HEAD) of the repository at source (a URL or a local path) into dest, a
    new or empty directory, with no history, and check it out. Returns the
    commit's SHA. Raises CloneError."""
    _git("init", "--quiet", str(dest))
    # Fetching from the URL rather than a remote doesn't store it, so a
    # URL's credentials aren't written to the clone's .git/config. "--"
    # stops a source or ref starting with "-" being taken for an option.
    _git("-C", str(dest), "fetch", "--quiet", "--depth", "1", "--", source, ref or "HEAD")
    _git("-C", str(dest), "checkout", "--quiet", "--detach", "FETCH_HEAD")
    return _git("-C", str(dest), "rev-parse", "HEAD").strip()


def _git(*args: str) -> str:
    try:
        proc = subprocess.run(["git", *args], capture_output=True, text=True)
    except OSError as e:
        raise CloneError(f"can't run git: {e}") from None
    if proc.returncode != 0:
        detail = proc.stderr.strip() or f"exit status {proc.returncode}"
        raise CloneError(f"git {args[2] if args[0] == '-C' else args[0]} failed: {detail}")
    return proc.stdout


def github_link_template(source: str, commit: str) -> str | None:
    """A --link-template to commit's files on GitHub, if source is a
    github.com repository URL."""
    match = _GITHUB_URL.fullmatch(source)
    if not match:
        return None
    return f"https://github.com/{match['owner']}/{match['repo']}/blob/{commit}/{{path}}#L{{line}}"
