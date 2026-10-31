"""SARIF 2.1.0 output, e.g. for GitHub code scanning."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from .analyze import Issue, Location

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFORMATION_URI = "https://github.com/skissane/exolot"
# SARIF has no level for the LSP's info and hint severities, so they're notes.
LEVELS = {"error": "error", "warning": "warning", "info": "note", "hint": "note"}


def log(
    issues: Iterable[Issue],
    version: str,
    rule_names: Mapping[str, str],
    artifact_location: Callable[[Path], dict[str, str]],
) -> dict[str, Any]:
    """A SARIF log with one run holding issues as results, in the order given.

    The driver's rules are the rules the issues break, with their names (from
    rule_names, where it has them) as short descriptions. artifact_location
    gives the artifactLocation of a file, e.g. its path relative to a uriBaseId.
    """
    issues = list(issues)
    rule_ids = sorted({issue.rule for issue in issues})
    rule_index = {rule: i for i, rule in enumerate(rule_ids)}
    rules: list[dict[str, Any]] = []
    for rule in rule_ids:
        descriptor: dict[str, Any] = {"id": rule}
        if rule_names.get(rule):
            descriptor["shortDescription"] = {"text": rule_names[rule]}
        rules.append(descriptor)
    results = []
    for issue in issues:
        result: dict[str, Any] = {
            "ruleId": issue.rule,
            "ruleIndex": rule_index[issue.rule],
            "level": LEVELS.get(issue.severity, "warning"),
            "message": {"text": issue.message},
            "locations": [_location(issue, artifact_location)],
        }
        if issue.related:
            result["relatedLocations"] = [
                {"id": i, **_location(loc, artifact_location)} for i, loc in enumerate(issue.related, start=1)
            ]
        results.append(result)
    return {
        "$schema": SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {"name": "exolot", "version": version, "informationUri": INFORMATION_URI, "rules": rules}
                },
                "columnKind": "utf16CodeUnits",
                "results": results,
            }
        ],
    }


def _location(item: Issue | Location, artifact_location: Callable[[Path], dict[str, str]]) -> dict[str, Any]:
    location: dict[str, Any] = {
        "physicalLocation": {
            "artifactLocation": artifact_location(item.path),
            "region": {
                "startLine": item.line,
                "startColumn": item.column,
                "endLine": item.end_line,
                "endColumn": item.end_column,
            },
        }
    }
    if isinstance(item, Location) and item.message:
        location["message"] = {"text": item.message}
    return location
