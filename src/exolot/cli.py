from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path

from . import __version__, markdown
from .analyze import AnalysisSession, Issue, collect_files
from .server import DEFAULT_SERVER_VERSION, ServerError, cache_dir, detect_platform, ensure_server

COMMANDS = ("analyze", "install", "cache-dir")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exolot",
        description="Analyze code locally with the SonarQube for IDE language server, no account needed.",
    )
    parser.add_argument("--version", action="version", version=f"exolot {__version__}")
    sub = parser.add_subparsers(dest="command")

    server_opts = argparse.ArgumentParser(add_help=False)
    server_opts.add_argument(
        "--server-version",
        default=DEFAULT_SERVER_VERSION,
        help="sonarlint-vscode release tag to use (default: %(default)s)",
    )
    server_opts.add_argument(
        "--platform",
        default=None,
        help="VSIX platform, e.g. linux-x64, or 'universal' (default: detected)",
    )
    server_opts.add_argument("--java", help="Java executable to use instead of the bundled one")
    server_opts.add_argument("-v", "--verbose", action="store_true", help="show server logs")

    analyze = sub.add_parser("analyze", parents=[server_opts], help="analyze files (the default command)")
    analyze.add_argument("paths", nargs="*", type=Path, default=[Path(".")], help="files or directories")
    analyze.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    analyze.add_argument(
        "--link-template",
        type=_link_template,
        metavar="TEMPLATE",
        help="with --format markdown, link each location to this URL, filling in {path} (URL-quoted), {line}, "
        "{column}, {end_line} and {end_column}, e.g. 'https://github.com/OWNER/REPO/blob/SHA/{path}#L{line}'",
    )
    analyze.add_argument(
        "--rules",
        type=Path,
        help="JSON file of rule settings, in the same format as VS Code's sonarlint.rules setting",
    )
    analyze.add_argument("--node", help="Node.js executable for JavaScript/TypeScript analysis")
    analyze.add_argument("--workspace", type=Path, help="workspace folder (default: current directory)")
    analyze.add_argument("--timeout", type=float, default=None, help="give up after this many seconds")
    analyze.add_argument(
        "--statistics",
        action="store_true",
        help="show the number of issues for each rule, most common first, instead of the issues",
    )
    analyze.add_argument(
        "-e",
        "--exit-zero",
        action="store_true",
        help="exit with status 0 even when issues are found (still 2 if the analysis fails)",
    )

    sub.add_parser("install", parents=[server_opts], help="download and unpack the language server")
    sub.add_parser("cache-dir", help="print the cache directory")
    return parser


def _link_template(value: str) -> str:
    try:
        return markdown.check_link_template(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "analyze")
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "link_template", None) and (args.format != "markdown" or args.statistics):
        parser.error("--link-template needs --format markdown, without --statistics")

    logging.basicConfig(
        level=logging.INFO if getattr(args, "verbose", False) else logging.WARNING,
        format="exolot: %(message)s",
    )

    if args.command == "cache-dir":
        print(cache_dir())
        return 0

    plat = args.platform
    if plat == "universal":
        plat = ""

    if args.command == "analyze":
        # Check the inputs before possibly downloading the server.
        try:
            files = collect_files(args.paths)
            rules = json.loads(args.rules.read_text()) if args.rules else None
        except (OSError, ValueError) as e:
            print(f"exolot: {e}", file=sys.stderr)
            return 2
        if not files:
            print("exolot: no files to analyze", file=sys.stderr)
            return 0

    try:
        server = ensure_server(args.server_version, plat, args.java)
    except (ServerError, OSError) as e:
        print(f"exolot: {e}", file=sys.stderr)
        return 2

    if args.command == "install":
        shown = plat if plat is not None else detect_platform()
        print(f"Language server {args.server_version} ({shown or 'universal'})")
        print(f"  installed in {server.root}")
        print(f"  using Java {server.java}")
        return 0

    workspace = args.workspace or Path.cwd()

    try:
        with AnalysisSession(server, workspace, rules=rules, node=args.node, verbose=args.verbose) as session:
            issues = session.analyze(files, timeout=args.timeout)
            # Report before the server shuts down, which can take a few seconds.
            if args.statistics:
                _report_statistics(issues, len(files), args.format, session.rule_names() if issues else {})
            else:
                _report(issues, len(files), args.format, args.link_template)
    except (OSError, RuntimeError) as e:  # TimeoutError is an OSError
        print(f"exolot: {e}", file=sys.stderr)
        return 2
    return 1 if issues and not args.exit_zero else 0


def _report(issues: list[Issue], file_count: int, fmt: str, link_template: str | None = None) -> None:
    issues = sorted(issues, key=lambda i: (str(i.path), i.line, i.column, i.rule))
    if fmt == "json":
        json.dump([_issue_json(i) for i in issues], sys.stdout, indent=2)
        print()
    elif fmt == "markdown":
        lines = markdown.findings_table(map(_issue_json, issues), link_template) if issues else ["No issues found."]
        print("\n".join(lines))
        print(f"{len(issues)} issue(s) in {file_count} file(s) analyzed", file=sys.stderr)
    else:
        for issue in issues:
            location = f"{_display_path(issue.path)}:{issue.line}:{issue.column}"
            print(f"{location}: {issue.severity} [{issue.rule}] {issue.message}")
        print(f"{len(issues)} issue(s) in {file_count} file(s) analyzed", file=sys.stderr)
    sys.stdout.flush()


def _report_statistics(issues: list[Issue], file_count: int, fmt: str, names: dict[str, str]) -> None:
    """Print one line per rule, most issues first, like ``ruff check --statistics``."""
    counts = Counter(issue.rule for issue in issues)
    rows = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if fmt == "json":
        stats = [{"code": rule, "name": names.get(rule, ""), "count": count} for rule, count in rows]
        json.dump(stats, sys.stdout, indent=2)
        print()
    elif fmt == "markdown":
        print("\n".join(markdown.statistics_table(rows, names) if rows else ["No issues found."]))
        print(f"{len(issues)} issue(s) in {file_count} file(s) analyzed", file=sys.stderr)
    else:
        count_width = max((len(str(count)) for _, count in rows), default=0)
        rule_width = max((len(rule) for rule, _ in rows), default=0)
        for rule, count in rows:
            print(f"{count:>{count_width}}\t{rule:<{rule_width}}\t{names.get(rule, '')}".rstrip())
        print(f"{len(issues)} issue(s) in {file_count} file(s) analyzed", file=sys.stderr)
    sys.stdout.flush()


def _display_path(path: Path) -> str:
    try:
        return os.path.relpath(path)
    except ValueError:  # different drive on Windows
        return str(path)


def _issue_json(issue: Issue) -> dict[str, object]:
    return {
        "path": _display_path(issue.path),
        "line": issue.line,
        "column": issue.column,
        "endLine": issue.end_line,
        "endColumn": issue.end_column,
        "rule": issue.rule,
        "severity": issue.severity,
        "message": issue.message,
    }
