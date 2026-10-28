from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import __version__
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
    analyze.add_argument("--format", choices=("text", "json"), default="text")
    analyze.add_argument(
        "--rules",
        type=Path,
        help="JSON file of rule settings, in the same format as VS Code's sonarlint.rules setting",
    )
    analyze.add_argument("--node", help="Node.js executable for JavaScript/TypeScript analysis")
    analyze.add_argument("--workspace", type=Path, help="workspace folder (default: current directory)")
    analyze.add_argument("--timeout", type=float, default=None, help="give up after this many seconds")

    sub.add_parser("install", parents=[server_opts], help="download and unpack the language server")
    sub.add_parser("cache-dir", help="print the cache directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "analyze")
    args = build_parser().parse_args(argv)

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
    try:
        server = ensure_server(args.server_version, plat, args.java)
    except (ServerError, OSError) as e:
        print(f"exolot: {e}", file=sys.stderr)
        return 2

    if args.command == "install":
        print(f"Language server {args.server_version} ({plat if plat is not None else detect_platform() or 'universal'})")
        print(f"  installed in {server.root}")
        print(f"  using Java {server.java}")
        return 0

    files = collect_files(args.paths)
    if not files:
        print("exolot: no files to analyze", file=sys.stderr)
        return 0
    rules = json.loads(args.rules.read_text()) if args.rules else None
    workspace = args.workspace or Path.cwd()

    try:
        with AnalysisSession(server, workspace, rules=rules, node=args.node, verbose=args.verbose) as session:
            issues = session.analyze(files, timeout=args.timeout)
            # Report before the server shuts down, which can take a few seconds.
            _report(issues, len(files), args.format)
    except (RuntimeError, TimeoutError) as e:
        print(f"exolot: {e}", file=sys.stderr)
        return 2
    return 1 if issues else 0


def _report(issues: list[Issue], file_count: int, fmt: str) -> None:
    issues = sorted(issues, key=lambda i: (str(i.path), i.line, i.column, i.rule))
    if fmt == "json":
        json.dump([_issue_json(i) for i in issues], sys.stdout, indent=2)
        print()
    else:
        for issue in issues:
            print(f"{_display_path(issue.path)}:{issue.line}:{issue.column}: {issue.severity} [{issue.rule}] {issue.message}")
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
