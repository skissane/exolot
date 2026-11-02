"""Printing analysis results in each of exolot's output formats."""

from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import __version__, annotations, gitdiff, markdown, problems, sarif
from .analyze import Issue


@dataclass
class Report:
    """What every report says besides the issues: how many files there were,
    and why some of them (if any) weren't analyzed."""

    file_count: int
    unanalyzed: list[problems.Problem]

    def summary(self, issue_count: int, changed: int | None = None) -> str:
        return problems.summary(issue_count, self.file_count, self.unanalyzed, changed)

    def markdown_warnings(self) -> list[str]:
        """Markdown saying why files weren't analyzed, if any weren't,
        followed by a blank line."""
        return markdown.warnings_alert([p.sentence() for p in self.unanalyzed])


def print_findings(
    issues: list[Issue],
    report: Report,
    fmt: str,
    link_template: str | None = None,
    changes: gitdiff.Changes | None = None,
) -> None:
    """Print the issues as text, JSON or Markdown; with changes (from
    --diff-base without --changed-only), saying which are on changed lines."""
    issues = _sorted(issues)
    findings = [issue_json(i, changes) for i in issues]
    summary = report.summary(len(issues), sum(f["changed"] for f in findings) if changes is not None else None)
    if fmt == "json":
        json.dump(findings, sys.stdout, indent=2)
        print()
    elif fmt == "markdown":
        # Relative to the repo root rather than the current directory, so
        # links to the repo's code work from any subdirectory.
        findings = [{**f, "path": repo_path(i.path)} for i, f in zip(issues, findings)]
        lines = report.markdown_warnings()
        if not issues:
            lines.append("No issues found.")
        elif changes is not None:
            lines += markdown.changed_findings_sections(findings, link_template)
        else:
            lines += markdown.findings_table(findings, link_template)
        print("\n".join(lines))
        print(summary, file=sys.stderr)
    else:
        for issue, finding in zip(issues, findings):
            location = f"{display_path(issue.path)}:{issue.line}:{issue.column}"
            mark = " (changed)" if finding.get("changed") else ""
            print(f"{location}: {issue.severity} [{issue.rule}] {issue.message}{mark}")
        print(summary, file=sys.stderr)
    sys.stdout.flush()


def print_annotations(
    issues: list[Issue],
    changes: gitdiff.Changes | None = None,
    unanalyzed: list[problems.Problem] | None = None,
) -> None:
    """Print the issues to stderr as GitHub workflow commands, which the
    Actions runner turns into annotations, leaving stdout for the report.
    GitHub shows only the first few annotations of each type, so the
    warnings about files that weren't analyzed (unanalyzed), which say the
    rest can't be trusted to be complete, go first, then with changes the
    issues on changed lines. Paths are relative to the repo root, which is
    what GitHub matches them against."""
    for problem in unanalyzed or []:
        print(annotations.warning(problem.sentence()), file=sys.stderr)
    findings = [{**issue_json(i, changes), "path": repo_path(i.path)} for i in _sorted(issues)]
    for finding in sorted(findings, key=lambda f: not f.get("changed")):
        print(annotations.annotation(finding), file=sys.stderr)
    sys.stderr.flush()


def print_comment(
    issues: list[Issue],
    report: Report,
    link_template: str | None,
    preamble: str | None,
    changes: gitdiff.Changes | None = None,
) -> None:
    """Print the issues as a GitHub PR comment (--format github-comment)."""
    issues = _sorted(issues)
    findings = [{**issue_json(i, changes), "path": repo_path(i.path)} for i in issues]
    actions = _actions_urls()
    body = markdown.comment(
        findings,
        link_template=link_template,
        changed=changes is not None,
        preamble=preamble,
        commit=_head_commit(),
        run_url=actions[1] if actions else None,
        warnings=[p.sentence() for p in report.unanalyzed],
    )
    sys.stdout.write(body)
    sys.stdout.flush()
    changed = sum(f["changed"] for f in findings) if changes is not None else None
    print(report.summary(len(issues), changed), file=sys.stderr)


def print_sarif(issues: list[Issue], report: Report, names: dict[str, str]) -> None:
    issues = _sorted(issues)
    paths = {i.path for i in issues} | {loc.path for i in issues for loc in i.related}
    roots = {_repo_root(path.parent) for path in paths} - {None}
    # %SRCROOT% can only stand for one directory. GitHub code scanning doesn't
    # need it defined, as it takes paths to be relative to the checkout.
    src_root = roots.pop().as_uri() + "/" if len(roots) == 1 else None
    warnings = [p.sentence() for p in report.unanalyzed]
    log = sarif.log(issues, __version__, names, _artifact_location, src_root, warnings)
    json.dump(log, sys.stdout, indent=2)
    print()
    print(report.summary(len(issues)), file=sys.stderr)
    sys.stdout.flush()


def print_statistics(issues: list[Issue], report: Report, fmt: str, names: dict[str, str]) -> None:
    """Print one line per rule, most issues first, like ``ruff check --statistics``."""
    counts = Counter(issue.rule for issue in issues)
    rows = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if fmt == "json":
        stats = [{"code": rule, "name": names.get(rule, ""), "count": count} for rule, count in rows]
        json.dump(stats, sys.stdout, indent=2)
        print()
    elif fmt == "markdown":
        table = markdown.statistics_table(rows, names) if rows else ["No issues found."]
        print("\n".join(report.markdown_warnings() + table))
        print(report.summary(len(issues)), file=sys.stderr)
    else:
        count_width = max((len(str(count)) for _, count in rows), default=0)
        rule_width = max((len(rule) for rule, _ in rows), default=0)
        for rule, count in rows:
            print(f"{count:>{count_width}}\t{rule:<{rule_width}}\t{names.get(rule, '')}".rstrip())
        print(report.summary(len(issues)), file=sys.stderr)
    sys.stdout.flush()


def actions_link_template() -> str | None:
    """In GitHub Actions, a link template for the checked-out commit in the
    workflow's repository."""
    actions = _actions_urls()
    commit = _head_commit()
    if not actions or not commit:
        return None
    # Doubled braces, so a brace in the URL isn't taken for a field.
    return actions[0].replace("{", "{{").replace("}", "}}") + f"/blob/{commit}/{{path}}#L{{line}}"


def on_changed_lines(issue: Issue, changes: gitdiff.Changes) -> bool:
    """Whether any line of issue's range, or of its secondary locations (if
    fetched), is changed."""
    return any(changes.touches(loc.path, loc.line, loc.end_line) for loc in (issue, *issue.related))


def issue_json(issue: Issue, changes: gitdiff.Changes | None = None) -> dict[str, object]:
    finding: dict[str, object] = {
        "path": display_path(issue.path),
        "line": issue.line,
        "column": issue.column,
        "endLine": issue.end_line,
        "endColumn": issue.end_column,
        "rule": issue.rule,
        "severity": issue.severity,
        "message": issue.message,
    }
    if changes is not None:
        finding["changed"] = on_changed_lines(issue, changes)
    return finding


def display_path(path: Path) -> str:
    """path relative to the current directory if it's under it, else absolute."""
    try:
        relpath = os.path.relpath(path)
        if Path(relpath).parts[:1] == ("..",):
            return str(path if path.is_absolute() else path.absolute())
        return relpath
    except ValueError:  # different drive on Windows
        return str(path)


def repo_path(path: Path) -> str:
    """path relative to the root of the git repository holding it, or as
    display_path gives it when it's in none."""
    root = _repo_root(path.parent)
    return path.relative_to(root).as_posix() if root else display_path(path)


def _sorted(issues: list[Issue]) -> list[Issue]:
    return sorted(issues, key=lambda i: (str(i.path), i.line, i.column, i.rule))


@functools.cache
def _repo_root(directory: Path) -> Path | None:
    """The nearest of directory and its parents with a .git directory or file
    (a submodule's or worktree's), if any."""
    for d in (directory, *directory.parents):
        if (d / ".git").exists():
            return d
    return None


def _artifact_location(path: Path) -> dict[str, str]:
    """A SARIF artifactLocation for path: relative to %SRCROOT%, the root of
    the git repository holding it, as GitHub code scanning expects, or its
    absolute file URI when it's in none."""
    root = _repo_root(path.parent)
    if root is None:
        return {"uri": path.as_uri()}
    return {"uri": urllib.parse.quote(path.relative_to(root).as_posix()), "uriBaseId": "%SRCROOT%"}


def _actions_urls() -> tuple[str, str | None] | None:
    """In GitHub Actions, the URLs of the workflow's repository and of its run
    (if known)."""
    server = os.environ.get("GITHUB_SERVER_URL")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if os.environ.get("GITHUB_ACTIONS") != "true" or not server or not repo:
        return None
    repo_url = f"{server.rstrip('/')}/{repo}"
    run_id = os.environ.get("GITHUB_RUN_ID")
    return repo_url, f"{repo_url}/actions/runs/{run_id}" if run_id else None


def _head_commit() -> str | None:
    """The commit checked out in the git repository the current directory is
    in, if it's in one."""
    try:
        proc = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "HEAD"], capture_output=True, text=True)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None
