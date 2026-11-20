"""The pinned sonarlint-vscode releases, read from the bundled upstream.toml.

`repoutils github-releases bump` writes upstream.toml, configured in
pyproject.toml's [tool.repoutils.github-releases.sonarlint-vscode], and the
Bump sonarlint-vscode workflow runs it daily, so exolot only reads it. `repo`
is the repository whose releases it pins, `current` is the release exolot uses
by default, and each [releases."<tag>"] table maps each of that release's
assets to its digest, as GitHub's releases API gives it. Earlier releases are
kept, so `--server-version <tag>` still verifies its download.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from importlib import resources

from .jsontypes import is_json_object

# The repository whose release assets exolot downloads, which upstream.toml must pin.
REPO = "SonarSource/sonarlint-vscode"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class PinsError(Exception):
    pass


@dataclass(frozen=True)
class Pins:
    current: str  # the release tag exolot uses by default
    # Each pinned release's assets' digests, keyed by tag then asset filename,
    # in the releases API's "sha256:<hex>" form.
    releases: dict[str, dict[str, str]]

    def digest(self, tag: str, asset: str) -> str | None:
        """asset's sha256 as hex, or None if it isn't pinned."""
        digest = self.releases.get(tag, {}).get(asset)
        return None if digest is None else digest.removeprefix("sha256:")


def parse(text: str) -> Pins:
    """The pins in text, the contents of a pins file. Raises PinsError if
    it isn't valid TOML or isn't laid out as upstream.toml is."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise PinsError(str(e)) from None
    if data.get("repo") != REPO:
        raise PinsError(f"repo should be {REPO!r}")
    current = data.get("current")
    if not isinstance(current, str):
        raise PinsError("current should be a str")
    releases = data.get("releases")
    if not is_json_object(releases):
        raise PinsError("releases should be a table")
    if current not in releases:
        raise PinsError(f"current release {current} isn't in releases")
    pinned: dict[str, dict[str, str]] = {}
    for tag, assets in releases.items():
        if not is_json_object(assets):
            raise PinsError(f"releases.{tag} should be a table")
        pinned[tag] = {}
        for asset, digest in assets.items():
            if not (isinstance(digest, str) and DIGEST.fullmatch(digest)):
                raise PinsError(f"releases.{tag}: {asset} should be 'sha256:' and 64 lowercase hex digits")
            pinned[tag][asset] = digest
    return Pins(current=current, releases=pinned)


def load() -> Pins:
    """The pins bundled with exolot."""
    text = resources.files("exolot").joinpath("upstream.toml").read_text(encoding="utf-8")
    try:
        return parse(text)
    except PinsError as e:
        raise PinsError(f"bundled upstream.toml: {e}") from None
