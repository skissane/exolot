"""Markdown output: findings and statistics as GitHub-flavoured Markdown tables."""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable, Mapping

# The fields a --link-template can use, with example values to check it with.
LINK_FIELDS = {"path": "src/a.py", "line": 1, "column": 1, "end_line": 1, "end_column": 1}


def escape(text: str) -> str:
    """text on one line, with the characters that would format it, end a table
    cell or start an HTML tag or entity backslash-escaped."""
    text = " ".join(text.split())
    return re.sub(r"([\\`*_\[\]<>|~&])", r"\\\1", text)


def check_link_template(template: str) -> str:
    """template, if it's non-empty and formats with LINK_FIELDS; otherwise
    ValueError saying why."""
    if not template:
        raise ValueError("empty link template")
    try:
        template.format_map(LINK_FIELDS)
    except KeyError as e:
        fields = ", ".join("{" + name + "}" for name in LINK_FIELDS)
        raise ValueError(f"unknown field {e} in link template (it can use {fields})") from None
    except (ValueError, IndexError, AttributeError, TypeError) as e:
        raise ValueError(f"bad link template {template!r}: {e}") from None
    return template


def link(template: str, finding: Mapping) -> str:
    """The URL template gives for a finding (as in exolot's JSON output), with
    its path URL-quoted so the path can't end the Markdown link early."""
    return template.format_map(
        {
            "path": urllib.parse.quote(finding["path"]),
            "line": finding["line"],
            "column": finding["column"],
            "end_line": finding.get("endLine", finding["line"]),
            "end_column": finding.get("endColumn", finding["column"]),
        }
    )


def findings_table(findings: Iterable[Mapping], link_template: str | None = None) -> list[str]:
    """The lines of a Location | Rule | Message table of findings (dicts as in
    exolot's JSON output), in the order given. Paths use forward slashes, and
    with link_template each location links to the code."""
    rows = ["| Location | Rule | Message |", "| --- | --- | --- |"]
    for f in findings:
        f = {**f, "path": f["path"].replace("\\", "/")}
        location = escape(f"{f['path']}:{f['line']}")
        cell = f"[{location}]({link(link_template, f)})" if link_template else location
        rows.append(f"| {cell} | {escape(f['rule'])} | {escape(f['message'])} |")
    return rows


def statistics_table(rows: Iterable[tuple[str, int]], names: Mapping[str, str]) -> list[str]:
    """The lines of a Count | Rule | Name table, from (rule, count) pairs."""
    out = ["| Count | Rule | Name |", "| ---: | --- | --- |"]
    out += [f"| {count} | {escape(rule)} | {escape(names.get(rule, ''))} |" for rule, count in rows]
    return out


def changed_findings_sections(
    findings: Iterable[Mapping], link_template: str | None = None, heading: str = "On changed lines"
) -> list[str]:
    """The lines of a heading and table of the findings (dicts as in exolot's
    JSON output with --diff-base) whose "changed" is true, then the rest in a
    collapsed "Elsewhere" section, if there are any."""
    findings = list(findings)
    new = [f for f in findings if f.get("changed")]
    old = [f for f in findings if not f.get("changed")]
    out = [f"### {heading} ({len(new)})", ""]
    out += findings_table(new, link_template) if new else ["None."]
    if old:
        out += ["", "<details>", f"<summary>Elsewhere ({len(old)})</summary>", ""]
        out += findings_table(old, link_template) + ["", "</details>"]
    return out
