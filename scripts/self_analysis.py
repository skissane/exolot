"""Report exolot's findings on its own code as Markdown, and post the report to
a PR as a comment, hiding the comments earlier runs posted. Stdlib-only.

`report` turns `exolot --format json` output into Markdown, putting the
findings on lines a PR changes first. `post` posts that Markdown to a PR. They
are separate so CI can run `report` in the job that runs exolot (which has the
git history) and `post` in a job that has a write-capable token but runs
nothing else."""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
from pathlib import Path

from scripts import github_comments

# Marks the comments `post` posts, so the next run can find and hide them.
MARKER = "<!-- exolot-self-analysis -->"

# GitHub rejects a comment body over 65,536 characters; leave room for the
# truncation note.
MAX_BODY_CHARS = 65_000

# What the comment says about how to treat the findings. AGENTS.md has the rest.
POLICY = (
    "**For information only.** Fix the findings worth fixing; it's fine to ignore the rest, "
    "which don't block the PR, and there's no need to suppress them with a rules file, "
    "`NOSONAR` or `noqa`. See {agents} for more."
)

_HUNK_RE = re.compile(r"^@@ -\S+ \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")


def changed_lines(base: str) -> dict[str, set[int]]:
    """The lines of each file that the changes since base's merge base add or
    change, by path relative to the repo root."""
    diff = subprocess.run(
        ["git", "diff", "--unified=0", "--no-color", "--no-ext-diff", "--no-renames", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return parse_diff(diff)


def parse_diff(diff: str) -> dict[str, set[int]]:
    lines: dict[str, set[int]] = {}
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            path = target[2:] if target.startswith("b/") else None
        elif path is not None and (m := _HUNK_RE.match(line)):
            start = int(m["start"])
            count = 1 if m["count"] is None else int(m["count"])
            lines.setdefault(path, set()).update(range(start, start + count))
    return lines


def _escape(text: str) -> str:
    """text with the characters that would format it, end a table cell or
    start an HTML tag backslash-escaped, on one line."""
    text = " ".join(text.split())
    return re.sub(r"([\\`*_\[\]<>|~&])", r"\\\1", text)


def _table(findings: list[dict], link) -> list[str]:
    rows = ["| Location | Rule | Message |", "| --- | --- | --- |"]
    for f in findings:
        location = f"{f['path']}:{f['line']}"
        url = link(f)
        cell = f"[{_escape(location)}]({url})" if url else _escape(location)
        rows.append(f"| {cell} | {_escape(f['rule'])} | {_escape(f['message'])} |")
    return rows


def _findings_section(findings: list[dict], changed: dict[str, set[int]] | None, link) -> list[str]:
    if not findings:
        return ["No findings."]
    if changed is None:
        return [f"### Findings ({len(findings)})", ""] + _table(findings, link)
    new = [f for f in findings if f["line"] in changed.get(f["path"], ())]
    old = [f for f in findings if f not in new]
    out = [f"### On lines this PR changes ({len(new)})", ""]
    out += _table(new, link) if new else ["None."]
    if old:
        out += ["", "<details>", f"<summary>Elsewhere ({len(old)})</summary>", ""]
        out += _table(old, link) + ["", "</details>"]
    return out


def _truncate(body: str, run_url: str | None) -> str:
    if len(body) <= MAX_BODY_CHARS:
        return body
    cut = body[: body.rfind("\n", 0, MAX_BODY_CHARS)]
    where = f"[this workflow run]({run_url})" if run_url else "the workflow run"
    return f"{cut}\n\n_Report truncated; run `just self-analyze` for all of it, or see {where}._\n"


def build_report(
    findings: list[dict],
    *,
    changed: dict[str, set[int]] | None = None,
    repo: str | None = None,
    commit: str | None = None,
    run_url: str | None = None,
) -> str:
    """The comment body for exolot's JSON findings. With changed (from
    changed_lines), the findings on changed lines come first and the rest are
    collapsed."""
    findings = sorted(
        ({**f, "path": f["path"].replace("\\", "/")} for f in findings),
        key=lambda f: (f["path"], f["line"], f["column"], f["rule"]),
    )
    blob = f"https://github.com/{repo}/blob/{commit}" if repo and commit else None

    def link(f: dict) -> str | None:
        return f"{blob}/{f['path']}#L{f['line']}" if blob else None

    agents = f"[AGENTS.md]({blob}/AGENTS.md)" if blob else "AGENTS.md"
    out = [MARKER, "## exolot's findings on itself", "", POLICY.format(agents=agents), ""]
    if commit or run_url:
        analyzed = "Analysis"
        if commit:
            analyzed += f" of {commit}"
        if run_url:
            analyzed += f", from [this workflow run]({run_url})"
        out += [f"{analyzed}.", ""]
    out += _findings_section(findings, changed, link)
    return _truncate("\n".join(out) + "\n", run_url)


def _report(args) -> None:
    findings = json.loads(args.findings.read_text())
    changed = changed_lines(args.base) if args.base else None
    body = build_report(findings, changed=changed, repo=args.repo, commit=args.commit, run_url=args.run_url)
    if args.output:
        args.output.write_text(body)
    else:
        sys.stdout.write(body)


def _post(args) -> None:
    body = args.body.read_text()
    token = os.environ.get("GITHUB_TOKEN") or github_comments.gh_output("auth", "token")
    repo = args.repo or github_comments.gh_output("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
    if args.commit:
        # An older commit's run can finish after a newer one's, and mustn't
        # post over its report.
        head = github_comments.pr_head(repo, args.pr, token)
        if not head.startswith(args.commit):
            print(f"Not posting: the report is for {args.commit}, but PR #{args.pr}'s head is now {head}.")
            return
    # Post first, so a failure leaves the old report showing rather than none.
    posted = github_comments.request(
        "POST", f"{github_comments.API_URL}/repos/{repo}/issues/{args.pr}/comments", token, json_body={"body": body}
    )
    hidden = github_comments.hide_comments(repo, args.pr, MARKER, token, keep=posted["node_id"])
    print(f"Posted exolot's findings to PR #{args.pr}, and hid {hidden} earlier report(s).")


def main(argv: list[str]) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="owner/name (default: $GITHUB_REPOSITORY; for post, else gh's current repo)",
    )
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    report = sub.add_parser("report", parents=[common], help="turn exolot's JSON output into Markdown")
    report.add_argument("findings", type=Path, help="the output of `exolot --format json`")
    report.add_argument("--base", help="put the findings on lines changed since this commit's merge base first")
    report.add_argument("--commit", help="the commit analyzed, for links to the code")
    report.add_argument("--run-url", help="URL of the workflow run that analyzed it")
    report.add_argument("-o", "--output", type=Path, help="write here instead of to stdout")

    post = sub.add_parser(
        "post",
        parents=[common],
        help="post a report to a PR, hiding earlier ones; comments with $GITHUB_TOKEN, defaulting to `gh auth token`",
    )
    post.add_argument("pr", type=int, help="pull request number")
    post.add_argument("body", type=Path, help="the report, from `report`")
    post.add_argument(
        "--commit",
        help="commit the report is for; if it isn't (a prefix of) the PR's head, nothing is posted",
    )
    args = parser.parse_args(argv)

    try:
        if args.command == "report":
            _report(args)
        else:
            _post(args)
    except subprocess.CalledProcessError as e:
        print(f"{' '.join(e.cmd)} failed:\n{e.stderr}", file=sys.stderr)
        return 1
    except urllib.error.HTTPError as e:
        with e:
            detail = e.read().decode(errors="replace")
        print(f"HTTP {e.code} from {e.filename}:\n{detail}", file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
