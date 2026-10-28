import os
import stat
import zipfile

import pytest

from exolot import server
from exolot.server import ServerError, _extract, asset_name


def _add(z, name, data, mode):
    info = zipfile.ZipInfo(name)
    info.external_attr = mode << 16
    z.writestr(info, data)


def test_asset_name():
    assert asset_name("6.2.0+91200", "linux-x64") == "sonarlint-vscode-linux-x64-6.2.0.vsix"
    assert asset_name("6.2.0+91200", "") == "sonarlint-vscode-6.2.0.vsix"


@pytest.mark.skipif(os.name != "posix", reason="permission bits are POSIX-only")
def test_extract_restores_modes_and_filters(tmp_path):
    vsix = tmp_path / "x.vsix"
    with zipfile.ZipFile(vsix, "w") as z:
        _add(z, "extension/jre/j/bin/java", b"#!", 0o755)
        _add(z, "extension/jre/j/lib/jspawnhelper", b"#!", 0o755)
        _add(z, "extension/server/sonarlint-ls.jar", b"jar", 0o644)
        _add(z, "extension/images/logo.png", b"png", 0o644)
    dest = tmp_path / "out"
    _extract(vsix, dest)
    assert os.stat(dest / "extension/jre/j/bin/java").st_mode & stat.S_IXUSR
    assert os.stat(dest / "extension/jre/j/lib/jspawnhelper").st_mode & stat.S_IXUSR
    assert (dest / "extension/server/sonarlint-ls.jar").exists()
    assert not (dest / "extension/images").exists()


def test_extract_rejects_path_traversal(tmp_path):
    vsix = tmp_path / "x.vsix"
    with zipfile.ZipFile(vsix, "w") as z:
        _add(z, "extension/server/../../../evil", b"x", 0o644)
    with pytest.raises(ServerError):
        _extract(vsix, tmp_path / "out")


@pytest.mark.parametrize(
    "plat,machine,expected",
    [
        ("linux", "x86_64", "linux-x64"),
        ("linux", "aarch64", ""),
        ("darwin", "arm64", "darwin-arm64"),
        ("win32", "AMD64", "win32-x64"),
        ("win32", "ARM64", ""),
        ("freebsd14", "amd64", ""),
    ],
)
def test_detect_platform(monkeypatch, plat, machine, expected):
    monkeypatch.setattr(server.sys, "platform", plat)
    monkeypatch.setattr(server.platform, "machine", lambda: machine)
    assert server.detect_platform() == expected
