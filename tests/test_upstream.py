import pytest

from exolot import upstream
from exolot.server import asset_name
from exolot.upstream import Pins, PinsError, parse

DIGEST = "sha256:" + "ab" * 32

VALID = f"""
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
        ("[releases]", "current should be a str"),
        ('current = "1"\nreleases = 1', "releases should be a table"),
        ('current = "1"\n[releases.2]', "current release 1 isn't in releases"),
        ('current = "1"\n[releases]\n1 = "x"', "releases.1 should be a table"),
        ('current = "1"\n[releases.1]\n"a.vsix" = "ab"', "releases.1: a.vsix should be 'sha256:'"),
        (f'current = "1"\n[releases.1]\n"a.vsix" = "{DIGEST.upper()}"', "releases.1: a.vsix should be 'sha256:'"),
        ('current = "1"\n[releases.1]\n"a.vsix" = 1', "releases.1: a.vsix should be 'sha256:'"),
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
