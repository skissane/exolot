import os
import stat
import zipfile

import pytest

from exolot import server
from exolot.server import ServerError, _extract, _publish, asset_name


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


def test_publish_keeps_existing_complete_install(tmp_path):
    install = tmp_path / "install"
    install.mkdir()
    (install / ".complete").write_text("theirs")
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / ".complete").write_text("ours")
    (staging / "extra").write_text("x")  # non-empty, so rename onto it fails on every OS
    (install / "extra").write_text("x")
    _publish(staging, install)
    assert (install / ".complete").read_text() == "theirs"


def test_publish_replaces_incomplete_install(tmp_path):
    install = tmp_path / "install"
    install.mkdir()
    (install / "junk").write_text("x")
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / ".complete").write_text("ours")
    _publish(staging, install)
    assert (install / ".complete").read_text() == "ours"
    assert not (install / "junk").exists()


def _fake_release(tmp_path, monkeypatch, tag="1.0", plat="linux-x64"):
    """Serve a tiny VSIX for tag and plat from a file:// RELEASE_URL, with the
    cache in tmp_path, and return the VSIX's sha256."""
    asset = asset_name(tag, plat)
    release = tmp_path / "releases" / tag
    release.mkdir(parents=True)
    with zipfile.ZipFile(release / asset, "w") as z:
        _add(z, "extension/server/sonarlint-ls.jar", b"jar", 0o644)
        _add(z, "extension/images/logo.png", b"png", 0o644)
    monkeypatch.setattr(server, "RELEASE_URL", (tmp_path / "releases").as_uri() + "/{tag}/{asset}")
    monkeypatch.setenv("EXOLOT_CACHE_DIR", str(tmp_path / "cache"))
    return server._sha256(release / asset)


def test_ensure_server_installs_then_uses_the_cache(tmp_path, monkeypatch):
    digest = _fake_release(tmp_path, monkeypatch)
    monkeypatch.setitem(server.KNOWN_DIGESTS, "1.0", {"linux-x64": digest})
    s = server.ensure_server("1.0", "linux-x64", java="myjava")
    install = tmp_path / "cache" / "servers" / "1.0-linux-x64"
    assert s.root == install / "extension"
    assert s.jar.read_bytes() == b"jar"
    assert not (s.root / "images").exists()
    assert (install / server.COMPLETE_MARKER).read_text() == f"1.0 linux-x64 {digest}\n"
    assert not list((tmp_path / "cache" / "servers").glob(".download-*"))

    # A second call uses the install rather than downloading again.
    monkeypatch.setattr(server, "_install", lambda *args: pytest.fail("downloaded again"))
    assert server.ensure_server("1.0", "linux-x64", java="myjava") == s


def test_ensure_server_rejects_a_digest_mismatch(tmp_path, monkeypatch):
    _fake_release(tmp_path, monkeypatch)
    monkeypatch.setitem(server.KNOWN_DIGESTS, "1.0", {"linux-x64": "0" * 64})
    with pytest.raises(ServerError, match="sha256 mismatch"):
        server.ensure_server("1.0", "linux-x64", java="myjava")
    assert not (tmp_path / "cache" / "servers" / "1.0-linux-x64").exists()


def test_ensure_server_warns_about_an_unknown_version(tmp_path, monkeypatch, caplog):
    digest = _fake_release(tmp_path, monkeypatch, plat="")
    monkeypatch.setattr(server, "detect_platform", lambda: "")
    s = server.ensure_server("1.0", java="myjava")
    assert s.root == tmp_path / "cache" / "servers" / "1.0-universal" / "extension"
    assert f"no known digest for sonarlint-vscode-1.0.vsix; downloaded file has sha256 {digest}" in caplog.text


def _java_exe():
    return "java.exe" if server.sys.platform == "win32" else "java"


def test_find_java_prefers_the_override(tmp_path):
    assert server._find_java(tmp_path, "/my/java") == server.Path("/my/java")


def test_find_java_uses_the_bundled_jre(tmp_path, monkeypatch):
    java = tmp_path / "jre" / "jdk-21" / "bin" / _java_exe()
    java.parent.mkdir(parents=True)
    java.write_text("")
    monkeypatch.setenv("JAVA_HOME", str(tmp_path / "elsewhere"))
    assert server._find_java(tmp_path, None) == java


def test_find_java_falls_back_to_java_home_then_path(tmp_path, monkeypatch):
    home = tmp_path / "home"
    java = home / "bin" / _java_exe()
    java.parent.mkdir(parents=True)
    java.write_text("")
    monkeypatch.setenv("JAVA_HOME", str(home))
    assert server._find_java(tmp_path, None) == java

    monkeypatch.setenv("JAVA_HOME", str(tmp_path / "missing"))
    monkeypatch.setattr(server.shutil, "which", lambda name: "/usr/bin/java")
    assert server._find_java(tmp_path, None) == server.Path("/usr/bin/java")


def test_find_java_fails_without_any_java(tmp_path, monkeypatch):
    monkeypatch.delenv("JAVA_HOME", raising=False)
    monkeypatch.setattr(server.shutil, "which", lambda name: None)
    with pytest.raises(ServerError, match="no Java was found"):
        server._find_java(tmp_path, None)


@pytest.mark.parametrize(
    "plat,env,expected",
    [
        ("linux", {"XDG_CACHE_HOME": "/xdg"}, "/xdg/exolot"),
        ("linux", {}, "~/.cache/exolot"),
        ("darwin", {}, "~/Library/Caches/exolot"),
        ("win32", {"LOCALAPPDATA": "/appdata"}, "/appdata/exolot/Cache"),
        ("win32", {}, "~/AppData/Local/exolot/Cache"),
        ("linux", {"EXOLOT_CACHE_DIR": "/mine", "XDG_CACHE_HOME": "/xdg"}, "/mine"),
    ],
)
def test_cache_dir(monkeypatch, plat, env, expected):
    for name in ("EXOLOT_CACHE_DIR", "XDG_CACHE_HOME", "LOCALAPPDATA"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(server.sys, "platform", plat)
    assert server.cache_dir() == server.Path(expected).expanduser()
