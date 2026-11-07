"""The issues the server finds, and their secondary locations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from .jsontypes import is_json_object

SEVERITY_NAMES = {1: "error", 2: "warning", 3: "info", 4: "hint"}


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
    related: list[Location] = field(default_factory=list[Location])


def from_diagnostic(path: Path, diagnostic: dict[str, Any]) -> Issue:
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


def flow_locations(path: Path, action: dict[str, Any]) -> list[Location]:
    """The locations in a SonarLint.ShowAllLocations code action, or none if
    action is some other code action. path is the issue's file, for locations
    that don't name theirs."""
    command = action.get("command")
    if not is_json_object(command):
        return []
    command_name: str | None = command.get("command")
    if command_name != "SonarLint.ShowAllLocations":
        return []
    arguments: list[dict[str, Any]] = command.get("arguments") or []
    flows: list[dict[str, Any]] = [flow for arg in arguments for flow in arg.get("flows") or ()]
    locations = [_location(path, loc) for flow in flows for loc in flow.get("locations") or ()]
    return [loc for loc in locations if loc is not None]


def _location(path: Path, loc: dict[str, Any]) -> Location | None:
    """A flow location from the server as a Location, or None if it has no range."""
    text_range = loc.get("textRange")
    if not text_range:
        return None
    # Not its filePath, which on Windows the server gives as /C:/...
    uri: str | None = loc.get("uri")
    return Location(
        path=Path(url2pathname(urlparse(uri).path)) if uri else path,
        line=text_range["startLine"],
        column=text_range["startLineOffset"] + 1,
        end_line=text_range["endLine"],
        end_column=text_range["endLineOffset"] + 1,
        message=loc.get("message") or "",
    )
