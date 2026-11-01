from __future__ import annotations

import argparse
import contextlib
import functools
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import __version__, annotations, clone, config, gitdiff, markdown, sarif
from .analyze import SERVER_LOG_LEVELS, AnalysisSession, Issue, collect_files
from .server import DEFAULT_SERVER_VERSION, Server, ServerError, cache_dir, detect_platform, ensure_server

COMMANDS = ("analyze", "analyze-repo", "install", "cache-dir")


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
    server_opts.add_argument(
        "--log-level",
        choices=tuple(SERVER_LOG_LEVELS),
        help="show the server's log messages at this level and above (default: none)",
    )
    server_opts.add_argument(
        "-v",
        "--verbose",
        action="store_const",
        const="debug",
        dest="log_level",
        help="show all of the server's log messages (same as --log-level debug)",
    )

    # The options of both analyze and analyze-repo.
    analysis_opts = argparse.ArgumentParser(add_help=False)
    analysis_opts.add_argument(
        "--format", choices=("text", "json", "markdown", "github-comment", "sarif"), default="text"
    )
    analysis_opts.add_argument(
        "--link-template",
        type=_link_template,
        metavar="TEMPLATE",
        help="with --format markdown or github-comment, link each location to this URL, filling in {path} "
        "(URL-quoted, relative to the git repo's root), {line}, {column}, {end_line} and {end_column}, e.g. "
        "'https://github.com/OWNER/REPO/blob/SHA/{path}#L{line}' (default in GitHub Actions: the checked-out "
        "commit in the workflow's repository)",
    )
    analysis_opts.add_argument(
        "--no-links",
        action="store_true",
        help="with --format markdown or github-comment, don't link locations, even in GitHub Actions",
    )
    analysis_opts.add_argument(
        "--rules",
        type=Path,
        help="JSON file of rule settings, in the same format as VS Code's sonarlint.rules setting",
    )
    analysis_opts.add_argument("--node", help="Node.js executable for JavaScript/TypeScript analysis")
    analysis_opts.add_argument("--timeout", type=float, default=None, help="give up after this many seconds")
    analysis_opts.add_argument(
        "--statistics",
        action="store_true",
        help="show the number of issues for each rule, most common first, instead of the issues",
    )
    analysis_opts.add_argument(
        "--annotations",
        action="store_true",
        help="also print each issue to stderr as a GitHub Actions workflow command, which GitHub shows as an "
        "annotation on the PR's diff (issues on changed lines first, with --diff-base)",
    )
    analysis_opts.add_argument(
        "-e",
        "--exit-zero",
        action="store_true",
        help="exit with status 0 even when issues are found (still 2 if the analysis fails)",
    )

    analyze = sub.add_parser(
        "analyze", parents=[server_opts, analysis_opts], help="analyze files (the default command)"
    )
    analyze.add_argument("paths", nargs="*", type=Path, default=[Path(".")], help="files or directories")
    analyze.add_argument("--workspace", type=Path, help="workspace folder (default: current directory)")
    analyze.add_argument(
        "--diff-base",
        metavar="REF",
        help="mark the issues on lines changed since the merge base of REF and HEAD (committed or not, "
        "and in files git doesn't track yet), in the git repository the current directory is in",
    )
    analyze.add_argument(
        "--changed-only",
        action="store_true",
        help="with --diff-base, analyze only the changed files, and report and count only the issues on changed lines",
    )

    analyze_repo = sub.add_parser(
        "analyze-repo",
        parents=[server_opts, analysis_opts],
        help="clone a git repository into a temporary directory and analyze it",
        description="Fetch the latest commit (or --ref) of a git repository, without its history, into a "
        "temporary directory, analyze it there as the analyze command would, and delete it.",
    )
    analyze_repo.add_argument("source", help="the repository's URL, or a local repository's path")
    analyze_repo.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[Path(".")],
        help="files or directories in the repository, relative to its root (default: all of it)",
    )
    analyze_repo.add_argument(
        "--ref", help="the branch, tag or full commit SHA to analyze (default: the repository's default branch)"
    )
    analyze_repo.add_argument(
        "--keep",
        type=Path,
        metavar="DIR",
        help="clone into DIR, which must not exist or be empty, and keep it, instead of a temporary directory",
    )
    analyze_repo.set_defaults(workspace=None, diff_base=None, changed_only=False)

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
    if args.command in ("analyze", "analyze-repo"):
        _check_options(parser, args)

    # exolot's own progress messages (e.g. "downloading ...") show with
    # --log-level debug or info; its warnings and errors always show.
    log_level = getattr(args, "log_level", None)
    logging.basicConfig(
        level=logging.INFO if log_level in ("debug", "info") else logging.WARNING,
        format="exolot: %(message)s",
    )

    if args.command == "cache-dir":
        print(cache_dir())
        return 0
    if args.command == "install":
        return _install(args)
    if args.command == "analyze-repo":
        return _run_analyze_repo(args)
    return _run_analyze(args)


def _platform(args: argparse.Namespace) -> str | None:
    """The VSIX platform --platform asks for: None to detect it, or "" for
    the universal VSIX."""
    return "" if args.platform == "universal" else args.platform


def _ensure_server(args: argparse.Namespace) -> Server | None:
    """The language server, downloaded and unpacked if need be, or None
    after saying why it couldn't be."""
    try:
        return ensure_server(args.server_version, _platform(args), args.java)
    except (ServerError, OSError) as e:
        print(f"exolot: {e}", file=sys.stderr)
        return None


def _install(args: argparse.Namespace) -> int:
    server = _ensure_server(args)
    if server is None:
        return 2
    plat = _platform(args)
    shown = plat if plat is not None else detect_platform()
    print(f"Language server {args.server_version} ({shown or 'universal'})")
    print(f"  installed in {server.root}")
    print(f"  using Java {server.java}")
    return 0


def _run_analyze(args: argparse.Namespace) -> int:
    # Check the inputs before possibly downloading the server.
    try:
        inputs = _load_inputs(args)
    except (OSError, ValueError, gitdiff.GitError, config.ConfigError) as e:
        print(f"exolot: {e}", file=sys.stderr)
        return 2
    if not inputs.files:
        print("exolot: no files to analyze", file=sys.stderr)
        return 0
    server = _ensure_server(args)
    if server is None:
        return 2
    try:
        issues = _analyze(server, args, inputs)
    except (OSError, RuntimeError) as e:  # TimeoutError is an OSError
        print(f"exolot: {e}", file=sys.stderr)
        return 2
    return 1 if issues and not args.exit_zero else 0


def _run_analyze_repo(args: argparse.Namespace) -> int:
    """Clone the repository and analyze it from its root, so paths, the
    config file and the commit shown are the clone's."""
    problem = _repo_input_problem(args)
    if problem:
        print(f"exolot: {problem}", file=sys.stderr)
        return 2
    _resolve_local_options(args)
    try:
        # From a git hook, git would otherwise look at the hook's repository.
        with clone.without_repo_env():
            return _clone_and_analyze(args)
    except clone.CloneError as e:
        print(f"exolot: {e}", file=sys.stderr)
        return 2


def _clone_and_analyze(args: argparse.Namespace) -> int:
    """Clone into --keep DIR or a temporary directory, and analyze it there.
    Raises CloneError."""
    if args.keep is not None:
        dest = args.keep.resolve()
        commit = _clone_into_keep(args, dest)
        return _analyze_clone(args, dest, commit)
    # The language server has exited by the time the directory is deleted,
    # so on Windows nothing in it should still be open.
    with tempfile.TemporaryDirectory(prefix="exolot-") as tmp:
        dest = Path(tmp).resolve()
        return _analyze_clone(args, dest, _clone(args, dest))


def _repo_input_problem(args: argparse.Namespace) -> str | None:
    """Why the paths or --keep can't be used, if they can't: a path isn't
    inside the repository, or --keep isn't a new or empty directory."""
    for path in args.paths:
        if path.anchor or ".." in path.parts:  # anchor: also "/x" and "C:x" on Windows
            return f"{path} isn't a path inside the repository"
    keep = args.keep
    if keep is not None and keep.exists() and (not keep.is_dir() or any(keep.iterdir())):
        return f"{keep} isn't an empty directory"
    return None


def _resolve_local_options(args: argparse.Namespace) -> None:
    """Make the options naming local files absolute, as they're relative to
    the current directory, not the clone."""
    if args.rules is not None:
        args.rules = args.rules.resolve()
    for name in ("java", "node"):
        value = getattr(args, name)
        # A path, such as ./java (or C:java on Windows), rather than a name to look up on PATH.
        if value is not None and os.path.dirname(value):
            setattr(args, name, str(Path(value).resolve()))


def _clone(args: argparse.Namespace, dest: Path) -> str:
    """Clone the repository into dest, returning the commit. Raises CloneError."""
    source = args.source
    if Path(source).exists():
        source = str(Path(source).resolve())  # relative to the current directory, not the clone
    return clone.clone(source, dest, args.ref)


def _clone_into_keep(args: argparse.Namespace, dest: Path) -> str:
    """Clone into --keep DIR, returning the commit. If that fails or is
    interrupted, remove what it made (DIR was new or empty), so the same DIR
    can be used again, and re-raise."""
    created = not dest.exists()
    try:
        return _clone(args, dest)
    except BaseException:  # also Ctrl-C
        if created:
            shutil.rmtree(dest, ignore_errors=True)
        else:
            # .git, and any files a checkout wrote before it failed.
            for child in dest.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
        raise


def _analyze_clone(args: argparse.Namespace, dest: Path, commit: str) -> int:
    """Analyze the clone of commit in dest."""
    print(f"exolot: analyzing {clone.display_source(args.source)} at {commit}", file=sys.stderr)
    if not args.link_template and not args.no_links:
        # Link to the repository's own code; without that, don't link to
        # the workflow's repository in GitHub Actions, which isn't it.
        args.link_template = clone.github_link_template(args.source, commit)
        args.no_links = args.link_template is None
    with contextlib.chdir(dest):
        return _run_analyze(args)


def _check_options(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Exit with a usage error if the analyze command's options don't go
    together."""
    linkable = args.format in ("markdown", "github-comment") and not args.statistics
    if args.link_template and not linkable:
        parser.error("--link-template needs --format markdown or github-comment, without --statistics")
    if args.no_links and (not linkable or args.link_template):
        parser.error("--no-links needs --format markdown or github-comment, without --statistics or --link-template")
    if args.statistics and args.format in ("sarif", "github-comment"):
        parser.error(f"--statistics can't be used with --format {args.format}")
    if args.changed_only and args.diff_base is None:
        parser.error("--changed-only needs --diff-base")


@dataclass
class _Inputs:
    """What the analyze command reads before starting the server."""

    files: list[Path]
    rules: dict | None
    changes: gitdiff.Changes | None
    settings: config.Config


def _load_inputs(args: argparse.Namespace) -> _Inputs:
    """The files to analyze (only the changed ones, with --changed-only), the
    rule settings, the changes since --diff-base and the config file's
    settings. Raises OSError, ValueError, GitError or ConfigError."""
    files = collect_files(args.paths)
    rules = json.loads(args.rules.read_text()) if args.rules else None
    changes = gitdiff.changes_since(args.diff_base) if args.diff_base is not None else None
    settings = config.load(Path.cwd())
    if changes is not None and args.changed_only:
        changed_files = changes.files()
        files = [f for f in files if f in changed_files]
    return _Inputs(files, rules, changes, settings)


def _analyze(server: Server, args: argparse.Namespace, inputs: _Inputs) -> list[Issue]:
    """Analyze the files and print the report, returning the issues it
    counts (only those on changed lines, with --changed-only)."""
    changes = inputs.changes
    workspace = args.workspace or Path.cwd()
    log_level = SERVER_LOG_LEVELS[args.log_level] if args.log_level else None
    with AnalysisSession(server, workspace, rules=inputs.rules, node=args.node, log_level=log_level) as session:
        issues = session.analyze(inputs.files, timeout=args.timeout)
        if args.format == "sarif" and issues:
            session.add_related_locations(issues)
        elif changes is not None and (args.changed_only or args.annotations or not args.statistics):
            _add_changed_related_locations(session, issues, changes)
        if changes is not None and args.changed_only:
            issues = [i for i in issues if _on_changed_lines(i, changes)]
        # Report before the server shuts down, which can take a few seconds.
        _report_any(session, issues, args, inputs)
    return issues


def _report_any(session: AnalysisSession, issues: list[Issue], args: argparse.Namespace, inputs: _Inputs) -> None:
    """Print the report --format and --statistics ask for, and with
    --annotations, the annotations. With --changed-only, every issue is on a
    changed line, so none are marked as such."""
    file_count = len(inputs.files)
    changes = None if args.changed_only else inputs.changes
    if args.statistics:
        _report_statistics(issues, file_count, args.format, session.rule_names() if issues else {})
    elif args.format == "sarif":
        _report_sarif(issues, file_count, session.rule_names() if issues else {})
    elif args.format == "github-comment":
        _report_comment(issues, file_count, args, inputs.settings, changes)
    else:
        _report(issues, file_count, args.format, _links(args), changes)
    if args.annotations:
        _print_annotations(issues, changes)


def _report(
    issues: list[Issue],
    file_count: int,
    fmt: str,
    link_template: str | None = None,
    changes: gitdiff.Changes | None = None,
) -> None:
    """Print the issues; with changes (from --diff-base without
    --changed-only), saying which are on changed lines."""
    issues = sorted(issues, key=lambda i: (str(i.path), i.line, i.column, i.rule))
    findings = [_issue_json(i, changes) for i in issues]
    summary = f"{len(issues)} issue(s)"
    if changes is not None:
        summary += f", {sum(f['changed'] for f in findings)} on changed lines,"
    summary += f" in {file_count} file(s) analyzed"
    if fmt == "json":
        json.dump(findings, sys.stdout, indent=2)
        print()
    elif fmt == "markdown":
        # Relative to the repo root rather than the current directory, so
        # links to the repo's code work from any subdirectory.
        findings = [{**f, "path": _repo_path(i.path)} for i, f in zip(issues, findings)]
        if not issues:
            lines = ["No issues found."]
        elif changes is not None:
            lines = markdown.changed_findings_sections(findings, link_template)
        else:
            lines = markdown.findings_table(findings, link_template)
        print("\n".join(lines))
        print(summary, file=sys.stderr)
    else:
        for issue, finding in zip(issues, findings):
            location = f"{_display_path(issue.path)}:{issue.line}:{issue.column}"
            mark = " (changed)" if finding.get("changed") else ""
            print(f"{location}: {issue.severity} [{issue.rule}] {issue.message}{mark}")
        print(summary, file=sys.stderr)
    sys.stdout.flush()


def _print_annotations(issues: list[Issue], changes: gitdiff.Changes | None = None) -> None:
    """Print the issues to stderr as GitHub workflow commands, which the
    Actions runner turns into annotations, leaving stdout for the report.
    GitHub shows only the first few annotations of each type, so with changes
    those on changed lines go first. Paths are relative to the repo root,
    which is what GitHub matches them against."""
    issues = sorted(issues, key=lambda i: (str(i.path), i.line, i.column, i.rule))
    findings = [{**_issue_json(i, changes), "path": _repo_path(i.path)} for i in issues]
    for finding in sorted(findings, key=lambda f: not f.get("changed")):
        print(annotations.annotation(finding), file=sys.stderr)
    sys.stderr.flush()


def _report_comment(
    issues: list[Issue],
    file_count: int,
    args: argparse.Namespace,
    settings: config.Config,
    changes: gitdiff.Changes | None = None,
) -> None:
    issues = sorted(issues, key=lambda i: (str(i.path), i.line, i.column, i.rule))
    findings = [{**_issue_json(i, changes), "path": _repo_path(i.path)} for i in issues]
    actions = _actions_urls()
    body = markdown.comment(
        findings,
        link_template=_links(args),
        changed=changes is not None,
        preamble=settings.preamble,
        commit=_head_commit(),
        run_url=actions[1] if actions else None,
    )
    sys.stdout.write(body)
    sys.stdout.flush()
    summary = f"{len(issues)} issue(s)"
    if changes is not None:
        summary += f", {sum(f['changed'] for f in findings)} on changed lines,"
    print(f"{summary} in {file_count} file(s) analyzed", file=sys.stderr)


def _links(args: argparse.Namespace) -> str | None:
    """The link template for Markdown locations: --link-template's, or in
    GitHub Actions (unless --no-links), one for the checked-out commit in the
    workflow's repository."""
    if args.link_template or args.no_links or args.format not in ("markdown", "github-comment"):
        return args.link_template
    actions = _actions_urls()
    commit = _head_commit()
    if not actions or not commit:
        return None
    # Doubled braces, so a brace in the URL isn't taken for a field.
    return actions[0].replace("{", "{{").replace("}", "}}") + f"/blob/{commit}/{{path}}#L{{line}}"


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


def _report_sarif(issues: list[Issue], file_count: int, names: dict[str, str]) -> None:
    issues = sorted(issues, key=lambda i: (str(i.path), i.line, i.column, i.rule))
    paths = {i.path for i in issues} | {loc.path for i in issues for loc in i.related}
    roots = {_repo_root(path.parent) for path in paths} - {None}
    # %SRCROOT% can only stand for one directory. GitHub code scanning doesn't
    # need it defined, as it takes paths to be relative to the checkout.
    src_root = roots.pop().as_uri() + "/" if len(roots) == 1 else None
    json.dump(sarif.log(issues, __version__, names, _artifact_location, src_root), sys.stdout, indent=2)
    print()
    print(f"{len(issues)} issue(s) in {file_count} file(s) analyzed", file=sys.stderr)
    sys.stdout.flush()


def _artifact_location(path: Path) -> dict[str, str]:
    """A SARIF artifactLocation for path: relative to %SRCROOT%, the root of
    the git repository holding it, as GitHub code scanning expects, or its
    absolute file URI when it's in none."""
    root = _repo_root(path.parent)
    if root is None:
        return {"uri": path.as_uri()}
    return {"uri": urllib.parse.quote(path.relative_to(root).as_posix()), "uriBaseId": "%SRCROOT%"}


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


def _repo_path(path: Path) -> str:
    """path relative to the root of the git repository holding it, or as
    _display_path gives it when it's in none."""
    root = _repo_root(path.parent)
    return path.relative_to(root).as_posix() if root else _display_path(path)


@functools.cache
def _repo_root(directory: Path) -> Path | None:
    """The nearest of directory and its parents with a .git directory or file
    (a submodule's or worktree's), if any."""
    for d in (directory, *directory.parents):
        if (d / ".git").exists():
            return d
    return None


def _add_changed_related_locations(session: AnalysisSession, issues: list[Issue], changes: gitdiff.Changes) -> None:
    """Fill in the secondary locations of the issues in changed files whose
    own range is unchanged, as one of those might be changed, e.g. the
    nesting a change adds to a function with a complexity issue."""
    changed_files = changes.files()
    candidates = [i for i in issues if i.path in changed_files and not _on_changed_lines(i, changes)]
    if candidates:
        session.add_related_locations(candidates, keep_message=True)


def _on_changed_lines(issue: Issue, changes: gitdiff.Changes) -> bool:
    """Whether any line of issue's range, or of its secondary locations (if
    fetched), is changed."""
    return any(changes.touches(loc.path, loc.line, loc.end_line) for loc in (issue, *issue.related))


def _issue_json(issue: Issue, changes: gitdiff.Changes | None = None) -> dict[str, object]:
    finding: dict[str, object] = {
        "path": _display_path(issue.path),
        "line": issue.line,
        "column": issue.column,
        "endLine": issue.end_line,
        "endColumn": issue.end_column,
        "rule": issue.rule,
        "severity": issue.severity,
        "message": issue.message,
    }
    if changes is not None:
        finding["changed"] = _on_changed_lines(issue, changes)
    return finding
