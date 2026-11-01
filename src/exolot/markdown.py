"""Markdown output: findings and statistics as GitHub-flavoured Markdown tables,
and findings as a PR comment."""

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


# GitHub rejects a comment over 65,536 characters. Leave room for the
# truncation note, and for a marker a script posting the comment might add.
MAX_COMMENT_CHARS = 65_000


def warnings_alert(messages: Iterable[str]) -> list[str]:
    """A GitHub warning alert (a quote elsewhere) listing messages, then a
    blank line, or nothing if there are none."""
    messages = list(messages)
    if not messages:
        return []
    return ["> [!WARNING]", *(f"> - {escape(m)}" for m in messages), ""]


def comment(
    findings: list[Mapping],
    *,
    link_template: str | None = None,
    changed: bool = False,
    preamble: str | None = None,
    commit: str | None = None,
    run_url: str | None = None,
    warnings: Iterable[str] = (),
) -> str:
    """A PR comment reporting findings (dicts as in exolot's JSON output, with
    "changed" if changed): a heading, the preamble, the commit analyzed and the
    workflow run that analyzed it, the warnings, then the findings, those on
    changed lines first if changed. It's cut short to fit in a GitHub comment."""
    out = ["## exolot's findings", ""]
    if preamble and preamble.strip():
        out += [preamble.strip(), ""]
    if commit or run_url:
        analyzed = "Analysis"
        if commit:
            analyzed += f" of {commit}"
        if run_url:
            analyzed += f", from [this workflow run]({run_url})"
        out += [f"{analyzed}.", ""]
    out += warnings_alert(warnings)
    if not findings:
        out.append("No issues found.")
    elif changed:
        out += changed_findings_sections(findings, link_template)
    else:
        out += [f"### Findings ({len(findings)})", ""] + findings_table(findings, link_template)
    return _truncate("\n".join(out) + "\n", run_url)


def _truncate(body: str, run_url: str | None) -> str:
    if len(body) <= MAX_COMMENT_CHARS:
        return body
    cut = body[: body.rfind("\n", 0, MAX_COMMENT_CHARS)]
    # Close a section the cut lands in, so the note isn't collapsed in it.
    if cut.count("<details>") > cut.count("</details>"):
        cut += "\n\n</details>"
    where = f" or see [this workflow run]({run_url})" if run_url else ""
    return f"{cut}\n\n_Report truncated: run exolot yourself for all of it{where}._\n"
