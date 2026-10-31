"""Run the language server headlessly over a set of files and collect issues."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from .lsp import LspClient
from .server import Server

log = logging.getLogger(__name__)

# VS Code language ids, which is what the server expects in didOpen.
LANGUAGE_IDS = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascriptreact",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "typescriptreact",
    ".vue": "vue",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
    ".java": "java",
    ".php": "php",
    ".go": "go",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".tf": "terraform",
    ".bicep": "bicep",
    ".sh": "shellscript",
    ".bash": "shellscript",
    ".properties": "properties",
}

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache"}
MAX_FILE_SIZE = 2 * 1024 * 1024
SEVERITY_NAMES = {1: "error", 2: "warning", 3: "info", 4: "hint"}


@dataclass
class Issue:
    path: Path
    line: int  # 1-based
    column: int  # 1-based
    end_line: int
    end_column: int
    rule: str
    message: str
    severity: str
    raw: dict[str, Any] = field(repr=False)


def language_id(path: Path) -> str:
    if path.name == "Dockerfile" or path.name.startswith("Dockerfile."):
        return "dockerfile"
    return LANGUAGE_IDS.get(path.suffix.lower(), "plaintext")


def collect_files(paths: list[Path]) -> list[Path]:
    """Expand directories into the files under them, skipping ignored and binary files."""
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"no such file or directory: {path}")
        candidates = [path] if path.is_file() else _list_dir(path)
        for f in candidates:
            f = f.resolve()
            if f not in seen and _is_analyzable(f):
                seen.add(f)
                result.append(f)
    return result


def _list_dir(directory: Path) -> list[Path]:
    git = shutil.which("git")
    if git:
        proc = subprocess.run(
            [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=directory,
            capture_output=True,
        )
        if proc.returncode == 0:
            return [directory / name for name in proc.stdout.decode().split("\0") if name]
    files = []
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        files.extend(Path(dirpath) / name for name in filenames)
    return files


def _is_analyzable(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_SIZE:
            return False
        with open(path, "rb") as f:
            return b"\0" not in f.read(8192)
    except OSError:
        return False


class AnalysisSession:
    """One language server process analyzing one workspace folder."""

    def __init__(
        self,
        server: Server,
        workspace: Path,
        rules: dict[str, Any] | None = None,
        node: str | None = None,
        jvm_args: list[str] | None = None,
        verbose: bool = False,
    ):
        self.server = server
        self.workspace = workspace.resolve()
        self.rules = rules or {}
        self.node = node
        self.jvm_args = jvm_args
        self.verbose = verbose
        self._cond = threading.Condition()
        self._published: dict[str, list[dict[str, Any]]] = {}
        self._active_progress: set[Any] = set()
        self._last_event = time.monotonic()
        self._folder_configured = threading.Event()
        self._proc: subprocess.Popen[bytes] | None = None
        self._client: LspClient | None = None

    def __enter__(self) -> AnalysisSession:
        try:
            self._start()
        except BaseException:
            self._kill()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _start(self) -> None:
        cmd = self.server.command(self.jvm_args)
        log.debug("starting %s", cmd)
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None if self.verbose else subprocess.DEVNULL,
        )
        client = self._client = LspClient(self._proc)
        client.on_notification("textDocument/publishDiagnostics", self._on_diagnostics)
        client.on_notification("$/progress", self._on_progress)
        client.on_notification("window/logMessage", self._on_log)
        client.on_request("workspace/configuration", self._on_configuration)
        client.on_request("window/workDoneProgress/create", lambda params: None)
        client.on_request("sonarlint/isOpenInEditor", lambda uri: True)
        client.on_request("sonarlint/isIgnoredByScm", lambda uri: False)
        client.on_request("sonarlint/shouldAnalyseFile", lambda params: {"shouldBeAnalysed": True})
        client.on_request("sonarlint/filterOutExcludedFiles", lambda params: params)
        client.on_request("sonarlint/listFilesInFolder", lambda params: {"foundFiles": []})
        client.on_request("sonarlint/canShowMissingRequirementsNotification", lambda params: "error_only")
        client.on_request("sonarlint/hasJoinedIdeLabs", lambda params: False)
        client.start()

        root_uri = self.workspace.as_uri()
        client.request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": root_uri,
                "workspaceFolders": [{"uri": root_uri, "name": self.workspace.name}],
                "capabilities": {
                    "workspace": {"configuration": True, "workspaceFolders": True},
                    "window": {"workDoneProgress": True},
                },
                "initializationOptions": {
                    "productKey": "vscode",
                    "productName": "exolot",
                    "productVersion": __version__,
                    "workspaceName": self.workspace.name,
                    "showVerboseLogs": self.verbose,
                    "firstSecretDetected": True,
                    "enableNotebooks": False,
                    "clientNodePath": self.node,
                    "connections": {"sonarqube": [], "sonarcloud": []},
                    "rules": self.rules,
                    "focusOnNewCode": False,
                    "automaticAnalysis": True,
                    "additionalAttributes": {},
                },
            },
        ).result(timeout=300)
        client.notify("initialized", {})
        # Files opened before the server has fetched the folder's settings get
        # analyzed twice, so wait for that first.
        if not self._folder_configured.wait(timeout=30):
            log.warning("server did not ask for folder settings; continuing anyway")

    def _settings(self) -> dict[str, Any]:
        return {
            "rules": self.rules,
            "disableTelemetry": True,
            "pathToNodeExecutable": self.node,
            "automaticAnalysis": True,
            "focusOnNewCode": False,
            "output": {"showVerboseLogs": self.verbose},
        }

    def _on_configuration(self, params: dict[str, Any]) -> list[Any]:
        if any(item.get("scopeUri") for item in params["items"]):
            self._folder_configured.set()
        return [self._settings() if item.get("section") == "sonarlint" else None for item in params["items"]]

    def _touch(self) -> None:
        self._last_event = time.monotonic()
        self._cond.notify_all()

    def _on_diagnostics(self, params: dict[str, Any]) -> None:
        with self._cond:
            self._published[params["uri"]] = params["diagnostics"]
            self._touch()

    def _on_progress(self, params: dict[str, Any]) -> None:
        kind = params.get("value", {}).get("kind")
        with self._cond:
            if kind == "begin":
                self._active_progress.add(params["token"])
            elif kind == "end":
                self._active_progress.discard(params["token"])
            self._touch()

    def _on_log(self, params: dict[str, Any]) -> None:
        if self.verbose:
            log.info("server: %s", params.get("message", "").rstrip())

    def analyze(
        self,
        files: list[Path],
        settle: float = 1.0,
        stall: float = 30.0,
        timeout: float | None = None,
    ) -> list[Issue]:
        """Open every file, then wait for the server to finish analyzing them.

        The server publishes diagnostics asynchronously and may publish a file
        more than once (e.g. an empty list before the real results). Analysis
        runs are bracketed by $/progress begin/end, so we treat the session as
        done once every file has been published, no progress is active, and
        nothing has arrived for ``settle`` seconds. If some files are never
        published after ``stall`` quiet seconds, the analysis is incomplete and
        we raise rather than report a partial result as clean.
        """
        assert self._client is not None
        deadline = None if timeout is None else time.monotonic() + timeout
        uris = {f.as_uri(): f for f in files}
        with self._cond:
            for uri in uris:
                self._published.pop(uri, None)
        for uri, path in uris.items():
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("analysis did not finish in time")
            text = path.read_text(encoding="utf-8", errors="replace")
            self._client.notify(
                "textDocument/didOpen",
                {"textDocument": {"uri": uri, "languageId": language_id(path), "version": 1, "text": text}},
            )
        with self._cond:
            self._touch()
            while True:
                if self._client.closed.is_set():
                    raise RuntimeError("language server exited unexpectedly")
                now = time.monotonic()
                quiet = now - self._last_event
                missing = [u for u in uris if u not in self._published]
                if not self._active_progress:
                    if not missing and quiet >= settle:
                        break
                    if missing and quiet >= stall:
                        names = ", ".join(str(uris[u]) for u in missing[:5])
                        more = f" and {len(missing) - 5} more" if len(missing) > 5 else ""
                        raise RuntimeError(f"the server never reported results for {names}{more}")
                if deadline is not None and now >= deadline:
                    raise TimeoutError("analysis did not finish in time")
                self._cond.wait(timeout=0.2)
            published = {uri: self._published.get(uri, []) for uri in uris}
        return [_to_issue(uris[uri], d) for uri, diags in published.items() for d in diags]

    def rule_names(self, timeout: float = 60) -> dict[str, str]:
        """Map each rule key the server knows, e.g. python:S1764, to its title.

        Best effort: returns what it can, or an empty dict if the server
        doesn't answer, since names only make the output friendlier.
        """
        assert self._client is not None
        try:
            by_language = self._client.request("sonarlint/listAllRules").result(timeout=timeout)
            return {
                str(rule["key"]): str(rule.get("name", ""))
                for rules in by_language.values()
                for rule in rules
                if "key" in rule
            }
        except Exception:
            log.debug("could not list the server's rules", exc_info=True)
            return {}

    def close(self) -> None:
        if self._client is not None and self._proc is not None and self._proc.poll() is None:
            try:
                self._client.request("shutdown").result(timeout=30)
                self._client.notify("exit")
                self._proc.wait(timeout=30)
            except Exception:
                log.debug("clean shutdown failed; killing server", exc_info=True)
        self._kill()

    def _kill(self) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait()
        if self._client is not None:
            self._client.close()


def _to_issue(path: Path, diagnostic: dict[str, Any]) -> Issue:
    start = diagnostic["range"]["start"]
    end = diagnostic["range"]["end"]
    return Issue(
        path=path,
        line=start["line"] + 1,
        column=start["character"] + 1,
        end_line=end["line"] + 1,
        end_column=end["character"] + 1,
        rule=str(diagnostic.get("code", "")),
        message=diagnostic.get("message", ""),
        severity=SEVERITY_NAMES.get(diagnostic.get("severity", 2), "warning"),
        raw=diagnostic,
    )
