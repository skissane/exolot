from pathlib import Path

import pytest
from repoutils import release_pins
from repoutils.commands import github_releases

from exolot import upstream
from exolot.server import asset_name
from exolot.upstream import Pins, PinsError, parse

DIGEST = "sha256:" + "ab" * 32
REPO = 'repo = "SonarSource/sonarlint-vscode"\n'
ROOT = Path(__file__).parent.parent

VALID = f"""
repo = "SonarSource/sonarlint-vscode"
current = "2.0+2"

[releases."2.0+2"]
"a-2.0.vsix" = "{DIGEST}"

[releases."1.0+1"]
"a-1.0.vsix" = "{DIGEST}"
"""


def test_parse() -> None:
    assert parse(VALID) == Pins(
        current="2.0+2",
        releases={"2.0+2": {"a-2.0.vsix": DIGEST}, "1.0+1": {"a-1.0.vsix": DIGEST}},
    )


def test_digest() -> None:
    pins = parse(VALID)
    assert pins.digest("1.0+1", "a-1.0.vsix") == "ab" * 32
    assert pins.digest("1.0+1", "a-2.0.vsix") is None
    assert pins.digest("3.0", "a-1.0.vsix") is None


def test_the_bundled_pins_cover_every_platform_of_the_current_release() -> None:
    pins = upstream.load()
    platforms = ("", "darwin-arm64", "darwin-x64", "linux-x64", "win32-x64")
    assert set(pins.releases[pins.current]) == {asset_name(pins.current, p) for p in platforms}


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("current = ", "Invalid value"),
        ('current = "1"\n[releases.1]\n"a.vsix" = "' + DIGEST + '"', "repo should be 'SonarSource/sonarlint-vscode'"),
        ('repo = "a/b"\ncurrent = "1"\n[releases.1]\n"a.vsix" = "' + DIGEST + '"', "repo should be"),
        (REPO + "[releases]", "current should be a str"),
        (REPO + 'current = "1"\nreleases = 1', "releases should be a table"),
        (REPO + 'current = "1"\n[releases.2]', "current release 1 isn't in releases"),
        (REPO + 'current = "1"\n[releases]\n1 = "x"', "releases.1 should be a table"),
        (REPO + 'current = "1"\n[releases.1]\n"a.vsix" = "ab"', "releases.1: a.vsix should be 'sha256:'"),
        (
            REPO + f'current = "1"\n[releases.1]\n"a.vsix" = "{DIGEST.upper()}"',
            "releases.1: a.vsix should be 'sha256:'",
        ),
        (REPO + 'current = "1"\n[releases.1]\n"a.vsix" = 1', "releases.1: a.vsix should be 'sha256:'"),
    ],
)
def test_parse_rejects(text: str, error: str) -> None:
    with pytest.raises(PinsError, match=error):
        parse(text)


def test_load_names_the_bundled_file(monkeypatch: pytest.MonkeyPatch) -> None:
    def bad(text: str) -> Pins:
        raise PinsError("broken")

    monkeypatch.setattr(upstream, "parse", bad)
    with pytest.raises(PinsError, match="^bundled upstream.toml: broken$"):
        upstream.load()


def test_parse_reads_what_repoutils_writes() -> None:
    pins = release_pins.Pins(upstream.REPO)
    release_pins.add(pins, "1.0+1", {"a-1.0.vsix": DIGEST})
    release_pins.add(pins, "2.0+2", {"a-2.0.vsix": DIGEST})
    assert parse(release_pins.render(pins)) == parse(VALID)


def test_repoutils_reads_the_bundled_pins_as_configured() -> None:
    """pyproject.toml's [tool.repoutils.github-releases] table names the
    bundled file, and repoutils reads it as exolot does."""
    [config] = github_releases.upstreams(ROOT)
    assert config.repo == upstream.REPO
    assert config.file.resolve() == (ROOT / "src" / "exolot" / "upstream.toml").resolve()
    pins = release_pins.read(config.file, config.repo)
    assert pins.current == upstream.load().current
    assert pins.releases == upstream.load().releases
    # It rewrites the file as it is, so its first bump changes only what it adds.
    assert release_pins.render(pins) == config.file.read_text(encoding="utf-8")
