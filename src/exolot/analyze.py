"""Run the language server headlessly over a set of files and collect issues."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from . import __version__, problems
from .lsp import LspClient
from .server import Server

log = logging.getLogger(__name__)
# The server's own log messages, at the level the server gave each one.
# AnalysisSession filters them by its log_level, so this logger passes them all.
server_log = logging.getLogger("exolot.languageserver")
server_log.setLevel(logging.DEBUG)

# The levels the server's log messages start with, as in "[Warn - 12:34:56.789] ...".
SERVER_LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}
_SERVER_LOG_PREFIX = re.compile(r"\[(\w+) - ")

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
# What the server appends to the message of an issue with secondary locations.
MORE_LOCATIONS = re.compile(r" \[\+\d+ locations?\]$")


@dataclass
class Location:
    """A secondary location of an issue, e.g. the other side of a comparison."""

    path: Path
    line: int  # 1-based
    column: int  # 1-based
    end_line: int
    end_column: int
    message: str


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
    related: list[Location] = field(default_factory=list)


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
        log_level: int | None = None,
    ):
        """``log_level`` is the lowest level of the server's log messages to
        log to the ``exolot.languageserver`` logger (one of ``SERVER_LOG_LEVELS``'
        values), or None to log none of them. Messages without a level are
        always logged, at INFO. With any level, the server's stderr is passed
        through too."""
        self.server = server
        self.workspace = workspace.resolve()
        self.rules = rules or {}
        self.node = node
        self.jvm_args = jvm_args
        self.log_level = log_level
        self._cond = threading.Condition()
        self._published: dict[str, list[dict[str, Any]]] = {}
        self._active_progress: set[Any] = set()
        self._last_event = time.monotonic()
        self._folder_configured = threading.Event()
        self._proc: subprocess.Popen[bytes] | None = None
        self._client: LspClient | None = None
        # What the server has said about analyzers that couldn't analyze:
        # the sensors that failed, with the reason if known, in order.
        self._sensor_failures: dict[str, str | None] = {}
        self._failed_sensor: str | None = None  # awaiting its stack trace
        self._needs_compilation_database = False
        self._shutting_down = False

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
            stderr=None if self.log_level is not None else subprocess.DEVNULL,
        )
        client = self._client = LspClient(self._proc)
        client.on_notification("textDocument/publishDiagnostics", self._on_diagnostics)
        client.on_notification("$/progress", self._on_progress)
        client.on_notification("window/logMessage", self._on_log)
        client.on_notification("window/showMessage", self._on_show_message)
        client.on_notification("sonarlint/needCompilationDatabase", self._on_need_compilation_database)
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
                    "showVerboseLogs": self._verbose_logs,
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
            "output": {"showVerboseLogs": self._verbose_logs},
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

    @property
    def _verbose_logs(self) -> bool:
        # The server only sends Debug messages when asked for verbose logs.
        return self.log_level is not None and self.log_level <= logging.DEBUG

    def _on_log(self, params: dict[str, Any]) -> None:
        message = params.get("message", "").rstrip()
        self._note_sensor_failure(message)
        # After shutdown the server logs errors, e.g. ClosedSelectorException,
        # that are just noise, so they show only with verbose logs.
        if self.log_level is None or (self._shutting_down and not self._verbose_logs):
            return
        prefix = _SERVER_LOG_PREFIX.match(message)
        level = SERVER_LOG_LEVELS.get(prefix.group(1).lower()) if prefix else None
        if level is None:
            server_log.info("server: %s", message)
        elif level >= self.log_level:
            server_log.log(level, "server: %s", message)

    def _note_sensor_failure(self, message: str) -> None:
        """Note a sensor's failure from the server's log: one message names
        the sensor and a later one has the stack trace, with the reason."""
        sensor = problems.failed_sensor(message)
        if sensor is not None:
            self._sensor_failures.setdefault(sensor, None)
            self._failed_sensor = sensor
        elif self._failed_sensor is not None and problems.is_stack_trace(message):
            if self._sensor_failures.get(self._failed_sensor) is None:
                self._sensor_failures[self._failed_sensor] = problems.stack_trace_reason(message)
            self._failed_sensor = None

    def _on_show_message(self, params: dict[str, Any]) -> None:
        """The server shows errors and warnings to the user this way, e.g.
        when it can't find the Node.js it needs to analyze JavaScript."""
        message = str(params.get("message", "")).strip()
        if params.get("type") in (1, 2):  # Error, Warning
            log.warning("warning: %s", message)
        else:
            log.info("%s", message)

    def _on_need_compilation_database(self, params: Any) -> None:
        self._needs_compilation_database = True

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
            while not self._finished(uris, settle, stall):
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("analysis did not finish in time")
                self._cond.wait(timeout=0.2)
            published = {uri: self._published.get(uri, []) for uri in uris}
        return [_to_issue(uris[uri], d) for uri, diags in published.items() for d in diags]

    def _finished(self, uris: dict[str, Path], settle: float, stall: float) -> bool:
        """Whether the server has finished analyzing the files at uris: every
        one is published, no progress is active and nothing has arrived for
        ``settle`` seconds. Raises if the server has exited, or has gone
        ``stall`` seconds without publishing some of them. Call with
        ``self._cond`` held."""
        assert self._client is not None
        if self._client.closed.is_set():
            raise RuntimeError("language server exited unexpectedly")
        if self._active_progress:
            return False
        quiet = time.monotonic() - self._last_event
        missing = [u for u in uris if u not in self._published]
        if missing and quiet >= stall:
            names = ", ".join(str(uris[u]) for u in missing[:5])
            more = f" and {len(missing) - 5} more" if len(missing) > 5 else ""
            raise RuntimeError(f"the server never reported results for {names}{more}")
        return not missing and quiet >= settle

    def unanalyzed(self, files: list[Path], timeout: float = 10) -> list[problems.Problem]:
        """Why the server couldn't analyze some of files, which it has
        analyzed: what kept each analyzer that couldn't from analyzing, with
        the files it would have analyzed."""
        languages = {path: language_id(path) for path in files}
        return problems.find(
            languages, self._plugin_states(timeout), self._sensor_failures, self._needs_compilation_database
        )

    def _plugin_states(self, timeout: float) -> dict[str, int]:
        """The state of each of the server's plugins (analyzers), by name.
        Best effort: an empty dict if the server doesn't say."""
        assert self._client is not None
        try:
            result = self._client.request(
                "sonarlint/getPluginStatuses", {"configScopeId": self.workspace.as_uri()}
            ).result(timeout=timeout)
            return {str(p["pluginName"]): p["state"] for p in result["pluginStatuses"]}
        except Exception:
            log.debug("could not get the server's plugin statuses", exc_info=True)
            return {}

    def rule_names(self, timeout: float = 10) -> dict[str, str]:
        """Map each rule key the server knows, e.g. python:S1764, to its title.

        Best effort: returns what it can, or an empty dict if the server
        doesn't answer, since names only make the output friendlier.
        """
        assert self._client is not None
        try:
            by_language = self._client.request("sonarlint/listAllRules").result(timeout=timeout)
            return {
                str(rule["key"]): str(rule.get("name") or "")
                for rules in by_language.values()
                for rule in rules
                if "key" in rule
            }
        except Exception:
            log.debug("could not list the server's rules", exc_info=True)
            return {}

    def add_related_locations(self, issues: list[Issue], timeout: float = 10, *, keep_message: bool = False) -> None:
        """Fill in the secondary locations of each issue whose message says it
        has some (``[+1 location]``), and take that note off its message
        unless keep_message.

        The server only gives them out in the "show all locations" code action
        it offers for the issue, so this asks for that. Best effort: an issue
        the server gives no locations for, or that timeout seconds (for all the
        issues together) run out before, is left as it is.
        """
        assert self._client is not None
        deadline = time.monotonic() + timeout
        for issue in issues:
            if not MORE_LOCATIONS.search(issue.message):
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log.debug("ran out of time getting secondary locations")
                break
            try:
                actions = self._client.request(
                    "textDocument/codeAction",
                    {
                        "textDocument": {"uri": issue.path.as_uri()},
                        "range": issue.raw["range"],
                        "context": {"diagnostics": [issue.raw]},
                    },
                ).result(timeout=remaining)
                issue.related = [loc for action in actions or [] for loc in _flow_locations(issue.path, action)]
            except Exception:
                log.debug("could not get the locations of %s", issue, exc_info=True)
            if issue.related and not keep_message:
                issue.message = MORE_LOCATIONS.sub("", issue.message)

    def close(self) -> None:
        if self._client is not None and self._proc is not None and self._proc.poll() is None:
            self._shutting_down = True
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


def _flow_locations(path: Path, action: dict[str, Any]) -> list[Location]:
    """The locations in a SonarLint.ShowAllLocations code action, or none if
    action is some other code action. path is the issue's file, for locations
    that don't name theirs."""
    command = action.get("command")
    if not isinstance(command, dict) or command.get("command") != "SonarLint.ShowAllLocations":
        return []
    flows = [flow for arg in command.get("arguments") or [] for flow in arg.get("flows") or []]
    locations = [_location(path, loc) for flow in flows for loc in flow.get("locations") or []]
    return [loc for loc in locations if loc is not None]


def _location(path: Path, loc: dict[str, Any]) -> Location | None:
    """A flow location from the server as a Location, or None if it has no range."""
    text_range = loc.get("textRange")
    if not text_range:
        return None
    # Not its filePath, which on Windows the server gives as /C:/...
    uri = loc.get("uri")
    return Location(
        path=Path(url2pathname(urlparse(uri).path)) if uri else path,
        line=text_range["startLine"],
        column=text_range["startLineOffset"] + 1,
        end_line=text_range["endLine"],
        end_column=text_range["endLineOffset"] + 1,
        message=loc.get("message") or "",
    )
