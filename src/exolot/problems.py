"""Work out which files the server couldn't analyze, and why, from what it
reports: the state of each language's analyzer (plugin), sensors that failed,
and its request for a C/C++ compilation database.

The server still publishes (empty) results for such files, so without this
they'd look clean.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

# The states sonarlint/getPluginStatuses gives, as ordinals. ACTIVE and SYNCED
# (from SonarQube in connected mode) analyze; the others don't.
PLUGIN_ACTIVE, PLUGIN_SYNCED, PLUGIN_DOWNLOADING, PLUGIN_FAILED, PLUGIN_PREMIUM, PLUGIN_UNSUPPORTED = range(6)
PLUGIN_STATE_CAUSES = {
    # The server downloads some analyzers (C, C++, C#) at run time.
    PLUGIN_DOWNLOADING: "couldn't be downloaded",
    PLUGIN_FAILED: "failed to load",
    PLUGIN_PREMIUM: "needs SonarQube Server or Cloud",
    PLUGIN_UNSUPPORTED: "isn't supported",
}

# The plugin, as getPluginStatuses names it, that analyzes each VS Code language id.
PLUGINS = {
    "c": "C",
    "cpp": "C++",
    "csharp": "C#",
    "objective-c": "Objective-C",
    "css": "CSS",
    "scss": "CSS",
    "less": "CSS",
    "html": "HTML",
    "java": "Java",
    "javascript": "JavaScript",
    "javascriptreact": "JavaScript",
    "typescript": "TypeScript",
    "typescriptreact": "TypeScript",
    "php": "PHP",
    "python": "Python",
    "go": "Go",
    "xml": "XML",
    "yaml": "YAML",
    "json": "JSON",
    "terraform": "Terraform",
    "dockerfile": "Docker",
    "shellscript": "Shell",
}

# The languages that sensors which analyze just one language family analyze,
# with that family's name. Other sensors' failures are reported by the
# sensor's name alone, as there's no telling which files they affect.
SENSORS = {
    "OmniSharp": ("C#", ("csharp",)),
    "CFamily": ("C/C++/Objective-C", ("c", "cpp", "objective-c")),
}
CFAMILY = SENSORS["CFamily"]

SENSOR_FAILED = re.compile(r"Error executing sensor: '([^']+)'")
# The start of a server log message: its level and time, then the logger and thread.
_LOG_PREFIX = re.compile(r"^\[\w+ - [^\]]*\] (?:\[[^\]]*\] )?")
# A Java exception class name at the start of a stack trace line, before its message.
_EXCEPTION_CLASS = re.compile(r"^((?:[\w$]+\.)+([\w$]+))(?:: |$)")


@dataclass
class Problem:
    """Something that kept the server from analyzing some files."""

    cause: str  # e.g. 'the OmniSharp analyzer failed (Cannot run program "dotnet")'
    reason: str  # a few words for the summary line, e.g. "analyzer failed"
    label: str | None = None  # the languages, e.g. "C#", or None if unknown
    languages: tuple[str, ...] = ()  # the VS Code language ids of the files it affects
    files: list[Path] = field(default_factory=list)

    def message(self, *, hint: bool = True) -> str:
        """A sentence about it, with the hint to see the server's log if hint."""
        if self.files:
            text = f"{self.cause}, so {len(self.files)} {self.label} file(s) were not analyzed"
        else:
            text = f"{self.cause}, so some files may not have been analyzed"
        return f"{text}; use --log-level error for details" if hint else f"{text[0].upper()}{text[1:]}."

    def summary(self) -> str:
        return f"{len(self.files)} {self.label} file(s) not analyzed ({self.reason})"


def find(
    files: Mapping[Path, str],
    plugin_states: Mapping[str, int],
    sensor_failures: Mapping[str, str | None],
    needs_compilation_database: bool,
) -> list[Problem]:
    """The problems that kept the server from analyzing some of files (each
    one's path and VS Code language id), from the states of its plugins (by
    name), the sensors that failed (by name, with the reason if known) and
    whether it asked for a compilation database. Each file counts towards the
    first problem that affects it; a problem that turns out to affect none of
    files is left out, unless it's a sensor whose files are unknown."""
    problems = []
    for language in dict.fromkeys(files.values()):
        plugin = PLUGINS.get(language)
        state = plugin_states.get(plugin) if plugin else None
        if state in PLUGIN_STATE_CAUSES:
            problems.append(
                Problem(
                    f"the {plugin} analyzer {PLUGIN_STATE_CAUSES[state]}", "analyzer unavailable", plugin, (language,)
                )
            )
    if needs_compilation_database:
        label, languages = CFAMILY
        cause = f"the {label} analyzer needs a compilation database (compile_commands.json)"
        problems.append(Problem(cause, "no compilation database", label, languages))
    for sensor, reason in sensor_failures.items():
        cause = f"the {sensor} analyzer failed" + (f" ({reason})" if reason else "")
        label, languages = SENSORS.get(sensor, (None, ()))
        problems.append(Problem(cause, "analyzer failed", label, languages))
    for path, language in files.items():
        problem = next((p for p in problems if language in p.languages), None)
        if problem is not None:
            problem.files.append(path)
    return [p for p in problems if p.files or not p.languages]


def failed_sensor(message: str) -> str | None:
    """The name of the sensor a server log message says failed, if it says so."""
    match = SENSOR_FAILED.search(message)
    return match.group(1) if match else None


def is_stack_trace(message: str) -> bool:
    return "\n\tat " in message


def stack_trace_reason(message: str) -> str | None:
    """Why the exception in a server log message's stack trace was thrown:
    the message of its root cause, or of the cause that wraps it if that one
    adds to it, e.g. 'Cannot run program "dotnet": Exec failed, ...' rather
    than just 'Exec failed, ...'."""
    lines = _LOG_PREFIX.sub("", message).splitlines()
    exceptions = lines[:1] + [line.removeprefix("Caused by: ") for line in lines if line.startswith("Caused by: ")]
    reasons = [_exception_message(line.strip()) for line in exceptions]
    reasons = [r for r in reasons if r]
    if not reasons:
        return None
    if len(reasons) > 1 and reasons[-2].endswith(f": {reasons[-1]}"):
        return reasons[-2]
    return reasons[-1]


def _exception_message(line: str) -> str:
    """The message of a stack trace's "java.io.IOException: message" line, or
    the exception's class name if it has none."""
    match = _EXCEPTION_CLASS.match(line)
    if not match:
        return line
    return line[match.end() :].strip() or match.group(2)


def summary(issue_count: int, file_count: int, problems: Iterable[Problem], changed: int | None = None) -> str:
    """The summary line: how many issues were found (and how many of them on
    changed lines, if changed isn't None) in how many of file_count files,
    and how many files weren't analyzed because of problems."""
    problems = [p for p in problems if p.files]
    text = f"{issue_count} issue(s)"
    if changed is not None:
        text += f", {changed} on changed lines,"
    text += f" in {file_count - sum(len(p.files) for p in problems)} file(s) analyzed"
    if problems:
        text += "; " + ", ".join(p.summary() for p in problems)
    return text
