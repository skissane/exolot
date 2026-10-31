"""Locate, download, verify and unpack the language server from a VSIX.

The VSIX is the SonarQube for IDE extension for VS Code, published as GitHub
release assets of SonarSource/sonarlint-vscode. Platform-specific builds bundle
a JRE; the universal build does not, so on other platforms we fall back to it
and use a Java found on the system.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_SERVER_VERSION = "6.2.0+91200"

RELEASE_URL = "https://github.com/SonarSource/sonarlint-vscode/releases/download/{tag}/{asset}"

# sha256 of each release asset, keyed by tag then platform ("" = universal).
# Taken from the GitHub release metadata and checked against the downloads.
KNOWN_DIGESTS: dict[str, dict[str, str]] = {
    "6.2.0+91200": {
        "": "b0c13ecb37b6d2e8e2414f482f62ddd916eec5f3c2db0711e9c0b7bb17823850",
        "darwin-arm64": "8d59d1101ed9edfb9b7bcb99fd3df8835b779c061bdceec01acf51c7fbc56446",
        "darwin-x64": "d64a71f0fdcd6597e7b1b7fba22be46f4ea64aae92f428b7149eecfb99626963",
        "linux-x64": "054f309995789e2cb5e20a1f0e071db7ab817e6dec11ae45bcebb45d69216cac",
        "win32-x64": "9c9657d007327e0bab923185c08c3c699989af2130e25353bedb2be04910467e",
    },
}

# Only these parts of the VSIX are needed to run the server.
EXTRACT_PREFIXES = ("extension/server/", "extension/analyzers/", "extension/jre/")
EXTRACT_FILES = ("extension/package.json", "extension/LICENSE.txt", "extension/NOTICE.txt")

# Written into an install directory last, so one without it is incomplete.
COMPLETE_MARKER = ".complete"

# Analyzers passed to the server, in the order the VS Code client passes them.
# C/C++ and C# analyzers are downloaded by the server itself on demand.
ANALYZERS = (
    "sonargo.jar",
    "sonarjava.jar",
    "sonarjavasymbolicexecution.jar",
    "sonarjs.jar",
    "sonarphp.jar",
    "sonarpython.jar",
    "sonarhtml.jar",
    "sonarxml.jar",
    "sonartext.jar",
    "sonariac.jar",
    "sonarlintomnisharp.jar",
)


class ServerError(Exception):
    pass


def detect_platform() -> str:
    """Return the VSIX platform suffix for this machine, or "" for universal."""
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if sys.platform == "darwin":
        os_name = "darwin"
    elif sys.platform.startswith("linux"):
        os_name = "linux"
    elif sys.platform == "win32":
        os_name = "win32"
    else:
        return ""
    candidate = f"{os_name}-{arch}"
    return candidate if candidate in {"darwin-arm64", "darwin-x64", "linux-x64", "win32-x64"} else ""


def cache_dir() -> Path:
    if env := os.environ.get("EXOLOT_CACHE_DIR"):
        return Path(env)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "exolot" / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "exolot"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "exolot"


def asset_name(tag: str, plat: str) -> str:
    version = tag.split("+", 1)[0]
    return f"sonarlint-vscode-{plat}-{version}.vsix" if plat else f"sonarlint-vscode-{version}.vsix"


@dataclass
class Server:
    root: Path  # the extracted "extension" directory
    java: Path

    @property
    def jar(self) -> Path:
        return self.root / "server" / "sonarlint-ls.jar"

    def analyzer_paths(self) -> list[Path]:
        return [p for p in (self.root / "analyzers" / name for name in ANALYZERS) if p.exists()]

    def command(self, jvm_args: list[str] | None = None) -> list[str]:
        return [
            str(self.java),
            "-Dsonarlint.telemetry.disabled=true",
            *(jvm_args or []),
            "-jar",
            str(self.jar),
            "-stdio",
            "-analyzers",
            *(str(p) for p in self.analyzer_paths()),
        ]


def ensure_server(
    tag: str = DEFAULT_SERVER_VERSION,
    plat: str | None = None,
    java: str | None = None,
    progress: bool = True,
) -> Server:
    """Return a ready-to-run server, downloading and unpacking it if needed."""
    if plat is None:
        plat = detect_platform()
    install_dir = cache_dir() / "servers" / f"{tag}-{plat or 'universal'}"
    if not (install_dir / COMPLETE_MARKER).exists():
        _install(tag, plat, install_dir, progress)
    root = install_dir / "extension"
    return Server(root=root, java=_find_java(root, java))


def _install(tag: str, plat: str, install_dir: Path, progress: bool) -> None:
    asset = asset_name(tag, plat)
    url = RELEASE_URL.format(tag=tag.replace("+", "%2B"), asset=asset)
    expected = KNOWN_DIGESTS.get(tag, {}).get(plat)
    install_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=install_dir.parent, prefix=".download-") as tmp:
        vsix = Path(tmp) / asset
        _download(url, vsix, progress)
        digest = _sha256(vsix)
        if expected is None:
            log.warning("no known digest for %s; downloaded file has sha256 %s", asset, digest)
        elif digest != expected:
            raise ServerError(f"sha256 mismatch for {asset}: expected {expected}, got {digest}")
        staging = Path(tmp) / "staging"
        _extract(vsix, staging)
        vsix.unlink()
        (staging / COMPLETE_MARKER).write_text(f"{tag} {plat or 'universal'} {digest}\n")
        _publish(staging, install_dir)


def _publish(staging: Path, install_dir: Path) -> None:
    """Move a finished install into place, tolerating concurrent installers.

    The rename is atomic, so another exolot process either sees no install or
    a complete one. If another process got there first, keep its copy.
    """
    try:
        staging.rename(install_dir)
    except OSError:
        if (install_dir / COMPLETE_MARKER).exists():
            log.debug("%s was installed by another process", install_dir)
            return
        # A leftover directory without the marker (e.g. from an older layout).
        shutil.rmtree(install_dir, ignore_errors=True)
        staging.rename(install_dir)


def _download(url: str, dest: Path, progress: bool) -> None:
    log.info("downloading %s", url)
    # The timeout applies to each blocking read, not the whole download.
    with urllib.request.urlopen(url, timeout=60) as response, open(dest, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        last_pct = -1
        while chunk := response.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if progress and total and sys.stderr.isatty():
                pct = done * 100 // total
                if pct != last_pct:
                    print(f"\rDownloading {dest.name}: {pct}%", end="", file=sys.stderr, flush=True)
                    last_pct = pct
        if progress and total and sys.stderr.isatty():
            print(file=sys.stderr)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _extract(vsix: Path, dest: Path) -> None:
    """Extract the parts we need, restoring Unix permission bits.

    zipfile drops permission bits, so executables in the bundled JRE (java,
    and lib/jspawnhelper which Java needs to start subprocesses) would not be
    runnable without restoring them from each entry's external attributes.
    """
    dest_resolved = dest.resolve()
    with zipfile.ZipFile(vsix) as z:
        for info in z.infolist():
            name = info.filename
            if not (name.startswith(EXTRACT_PREFIXES) or name in EXTRACT_FILES):
                continue
            target = (dest / name).resolve()
            if not target.is_relative_to(dest_resolved):
                raise ServerError(f"refusing to extract {name!r} outside {dest}")
            z.extract(info, dest)
            mode = (info.external_attr >> 16) & 0o777
            if mode and os.name == "posix":
                os.chmod(target, mode)


def _find_java(root: Path, override: str | None) -> Path:
    if override:
        return Path(override)
    exe = "java.exe" if sys.platform == "win32" else "java"
    jre = root / "jre"
    if jre.is_dir():
        candidates = sorted(jre.rglob(f"bin/{exe}"), key=lambda p: len(p.parts))
        if candidates:
            return candidates[0]
    if java_home := os.environ.get("JAVA_HOME"):
        candidate = Path(java_home) / "bin" / exe
        if candidate.exists():
            return candidate
    if found := shutil.which("java"):
        return Path(found)
    raise ServerError(
        "this platform has no VSIX with a bundled Java runtime, and no Java was found; "
        "install Java 17 or later, or pass --java"
    )
