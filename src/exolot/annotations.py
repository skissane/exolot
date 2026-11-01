"""GitHub Actions workflow command output, which GitHub shows as annotations."""

from __future__ import annotations

from collections.abc import Mapping

# The annotation command for each LSP severity: GitHub has none below notice.
COMMANDS = {"error": "error", "warning": "warning", "info": "notice", "hint": "notice"}


def escape_data(text: str) -> str:
    """text escaped for a workflow command's message."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(text: str) -> str:
    """text escaped for a workflow command's property value."""
    return escape_data(text).replace(":", "%3A").replace(",", "%2C")


def warning(message: str, title: str = "exolot") -> str:
    """A workflow command for a warning about the run rather than a line of
    code, which GitHub shows on the run's summary page."""
    return f"::warning title={escape_property(title)}::{escape_data(message)}"


def annotation(finding: Mapping) -> str:
    """The workflow command for a finding (a dict as in exolot's JSON output):
    ``::warning file=PATH,line=N,col=N,endLine=N,endColumn=N,title=RULE::MESSAGE``,
    with a forward-slashed path."""
    command = COMMANDS.get(finding["severity"], "warning")
    properties = {
        "file": finding["path"].replace("\\", "/"),
        "line": finding["line"],
        "col": finding["column"],
        "endLine": finding.get("endLine", finding["line"]),
        "endColumn": finding.get("endColumn", finding["column"]),
        "title": finding["rule"],
    }
    props = ",".join(f"{name}={escape_property(str(value))}" for name, value in properties.items())
    return f"::{command} {props}::{escape_data(finding['message'])}"
