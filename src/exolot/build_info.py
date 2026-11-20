"""The commit a build of exolot comes from.

repoutils' ``repoutils-build-info`` hatchling hook (enabled in
``pyproject.toml``) writes ``build_info.json`` into the sdist and the wheel,
such as ``{"commit": "<sha>", "dirty": false}``. exolot reads the file itself
rather than importing repoutils, which is a build requirement, not a runtime
dependency. A source checkout and an editable install have no file, and so no
commit.
"""

import json
from dataclasses import dataclass
from importlib.resources import files

from .jsontypes import is_json_object

FILE = "build_info.json"


@dataclass(frozen=True)
class BuildInfo:
    # The full hash of the commit the build comes from, or None if unknown.
    commit: str | None
    # Whether a file differed from that commit, or None if unknown.
    dirty: bool | None


UNKNOWN = BuildInfo(None, None)


def read() -> BuildInfo:
    """The build's commit, or UNKNOWN if there's no file or it isn't valid."""
    try:
        data = json.loads(files("exolot").joinpath(FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return UNKNOWN
    if not is_json_object(data):
        return UNKNOWN
    commit = data.get("commit")
    dirty = data.get("dirty")
    return BuildInfo(
        commit if isinstance(commit, str) and commit else None,
        dirty if isinstance(dirty, bool) else None,
    )


def describe(version: str, info: BuildInfo) -> str:
    """One line, as ``exolot --version`` prints it, such as
    ``exolot 0.5.0 (0123456789ab)``."""
    line = f"exolot {version}"
    if info.commit is not None:
        line += f" ({info.commit[:12]}{' with uncommitted changes' if info.dirty else ''})"
    return line
