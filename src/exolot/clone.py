"""Shallow-cloning a git repository for the analyze-repo command."""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import urllib.parse
from collections.abc import Iterator
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


# Variables that point git at a particular repository, which git sets when
# running hooks, so exolot run from a hook would otherwise clone into that.
_REPO_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
)


@contextlib.contextmanager
def without_repo_env() -> Iterator[None]:
    """Unset the variables that point git at a particular repository while
    in this context, so every git command run in it, such as the one listing
    a clone's files, uses the repository its directory is in."""
    saved = {name: os.environ.pop(name) for name in _REPO_ENV if name in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def _git(*args: str) -> str:
    env = {k: v for k, v in os.environ.items() if k not in _REPO_ENV}
    try:
        proc = subprocess.run(["git", *args], capture_output=True, text=True, env=env)
    except OSError as e:
        raise CloneError(f"can't run git: {e}") from None
    if proc.returncode != 0:
        detail = _without_credentials(proc.stderr.strip()) or f"exit status {proc.returncode}"
        raise CloneError(f"git {args[2] if args[0] == '-C' else args[0]} failed: {detail}")
    return proc.stdout


def _without_credentials(message: str) -> str:
    """message with the user name and password left out of any URL in it,
    even one in quotes."""
    return "".join(_word_without_credentials(word) for word in re.split(r"(\s+)", message))


def _word_without_credentials(word: str) -> str:
    start = word.find("://")
    if start < 0:
        return word
    start += 3
    end = word.find("/", start)
    at = word.rfind("@", start, len(word) if end < 0 else end)
    return word if at < 0 else word[:start] + word[at + 1 :]


def github_link_template(source: str, commit: str) -> str | None:
    """A --link-template to commit's files on GitHub, if source is a
    github.com repository URL."""
    match = _GITHUB_URL.fullmatch(source)
    if not match:
        return None
    return f"https://github.com/{match['owner']}/{match['repo']}/blob/{commit}/{{path}}#L{{line}}"


def display_source(source: str) -> str:
    """source with any user name and password (such as a token in an HTTPS
    URL) left out, to show in messages and logs."""
    parts = urllib.parse.urlsplit(source)
    if not parts.scheme or "@" not in parts.netloc:
        return source
    return parts._replace(netloc=parts.netloc.rpartition("@")[2]).geturl()
