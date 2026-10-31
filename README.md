# exolot

[![codecov](https://codecov.io/gh/skissane/exolot/graph/badge.svg)](https://codecov.io/gh/skissane/exolot)

Analyze code locally from the command line with the language server from
SonarQube for IDE (formerly SonarLint). No SonarQube account or server needed.

> exolot is an independent project. It is not affiliated with or endorsed by
> SonarSource. "SonarQube" and "SonarLint" are trademarks of SonarSource.

## Why

The old `sonarlint-cli` was discontinued years ago. SonarSource's current
SonarQube CLI needs a SonarQube Cloud or Server account, and its code analysis
runs on the server. exolot fills the gap: account-free analysis that runs
entirely on your own machine. It needs network access only to download the
language server the first time (and see the note on C/C++ and C# below).

## How it works

exolot downloads the SonarQube for IDE extension for VS Code (a `.vsix` file,
which is a zip) from the
[sonarlint-vscode GitHub releases](https://github.com/SonarSource/sonarlint-vscode/releases),
checks its sha256 digest, and unpacks the language server, the language
analyzers and the bundled Java runtime into a cache directory. It then runs the
language server headlessly, opens each file you ask it to analyze, and prints
the issues the server reports.

The idea comes from [sonarqube.nvim](https://github.com/iamkarasik/sonarqube.nvim),
which does the same thing for Neovim.

## Usage

```sh
uvx exolot                     # analyze the current directory
uvx exolot src/ tests/foo.py   # analyze specific files or directories
uvx exolot --format json .     # machine-readable output
uvx exolot --format markdown . # a Markdown table, e.g. for a PR comment
uvx exolot --format sarif .    # SARIF 2.1.0, e.g. for GitHub code scanning
uvx exolot --format github .   # GitHub Actions annotations
uvx exolot --statistics .      # count issues per rule, most common first
uvx exolot --diff-base origin/main --changed-only  # only issues on lines your branch changes
uvx exolot install             # just download and unpack the server
uvx exolot cache-dir           # show where the server is cached
```

Directories are expanded with `git ls-files` when inside a git repository (so
`.gitignore` is respected), and by walking the tree otherwise. Binary files and
files over 2 MiB are skipped.

Exit status is 0 when no issues are found, 1 when issues are found, and 2 on
errors. With `-e` / `--exit-zero` it is 0 even when issues are found, but still
2 when the analysis fails, like ruff's option of the same name.

### Options

- `--server-version TAG` picks a sonarlint-vscode release (default: the
  version exolot was tested with). Unknown versions are downloaded without
  digest verification, with a warning.
- `--platform PLATFORM` overrides the detected VSIX platform (`linux-x64`,
  `darwin-arm64`, `darwin-x64`, `win32-x64`, or `universal`).
- `--java PATH` uses a different Java executable.
- `--node PATH` sets the Node.js used for JavaScript/TypeScript analysis
  (otherwise the server looks for `node` on the `PATH`).
- `--rules FILE` reads rule settings from a JSON file, in the same format as
  VS Code's `sonarlint.rules` setting, e.g.
  `{"python:S1764": {"level": "off"}}`.
- `--statistics` prints one line per rule instead of the issues: the number of
  issues, the rule key and the rule's name, most common rule first (ties in
  rule key order), like `ruff check --statistics`. The name is left blank if
  the server can't list its rules. With `--format json` it prints a list of
  `{"code", "name", "count"}` objects. The exit status is the same as without it.
- `--format markdown` prints the issues as a GitHub-flavoured Markdown table
  (Location, Rule and Message), with characters Markdown or HTML would
  interpret escaped, and `--statistics` as a Count, Rule and Name table.
  Its paths are relative to the root of the git repository each file is in
  (so links work from any subdirectory), or to the current directory for
  files outside one.
- `--link-template TEMPLATE` (with `--format markdown`) links each location to
  a URL made from TEMPLATE, filling in `{path}` (URL-quoted, with forward
  slashes), `{line}`, `{column}`, `{end_line}` and `{end_column}`, e.g.
  `--link-template 'https://github.com/OWNER/REPO/blob/SHA/{path}#L{line}'`.
  Give the commit the code is from: in a pull request's workflow
  `GITHUB_SHA` is the merge commit, so use the PR's head SHA instead.
- `--format sarif` prints a [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html)
  log with one run: each issue is a result with its rule, message, level
  (`error`, `warning`, or `note` for the server's info and hint severities)
  and location, and each rule an issue breaks is listed with its name. Issues
  the server reports with secondary locations (`[+1 location]` at the end of
  the message) get them as related locations instead. Paths are relative to
  `%SRCROOT%`, the root of the git repository each file is in (defined in the
  run's `originalUriBaseIds` when all the files are in one repository), or
  absolute `file:` URIs for files outside one. It can't be combined with `--statistics`.
- `--format github` prints each issue as a GitHub Actions [workflow command](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands)
  (`::warning file=src/a.py,line=12,col=5,endLine=12,endColumn=9,title=python:S1234::message`),
  like `ruff check --output-format github`, which GitHub shows as annotations;
  see [Workflow annotations](#workflow-annotations). The command is `error`,
  `warning` or `notice` (for the server's info and hint severities), and paths
  are relative to the root of the git repository each file is in. With
  `--diff-base`, the issues on changed lines come first. It can't be combined
  with `--statistics`.
- `--diff-base REF` marks the issues on lines changed since the merge base of
  REF and `HEAD`, like SonarQube's "new code": lines added or modified in the
  working tree (committed or not), and every line of files git doesn't track
  yet (unless it ignores them). It looks at the git repository the current
  directory is in; issues in files outside it count as unchanged. An issue is
  on changed lines if any line of its range or of its secondary locations is
  (so a function's complexity issue counts when a change adds nesting to it),
  which takes an extra request to the server for each issue with secondary
  locations in a changed file. JSON output
  gets a `"changed": true` or `false` field, Markdown output puts the issues on
  changed lines first and collapses the rest under "Elsewhere", and text
  output ends those lines with `(changed)` and counts them in its summary.
  GitHub annotations put the issues on changed lines first.
  The exit status still counts every issue, and `--statistics` and SARIF
  output are unaffected. It exits with status 2 if git isn't installed, REF
  isn't a commit, or the merge base can't be found (in a shallow clone, such
  as `actions/checkout`'s default, fetch enough history first, e.g. with
  `fetch-depth: 0`).
- `--changed-only` (with `--diff-base`) analyzes only the files with changed
  lines, and reports only the issues on changed lines, in every format; the
  exit status and `--statistics` count only those. This lets a project adopt
  exolot in CI without fixing its existing issues first.
- `-v` / `--verbose` shows the server's logs.

## Workflow annotations

To show exolot's issues on a pull request's diff and in the workflow run's
summary, without a token or code scanning, print them as annotations:

```yaml
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: astral-sh/setup-uv@v10
      - run: uvx exolot --format github --diff-base "origin/$GITHUB_BASE_REF" .
```

GitHub shows at most 10 annotations of each type (error, warning, notice) per
step and 50 per job, so `--diff-base` puts the issues on the pull request's
changed lines first, and `--changed-only` drops the rest. Run exolot from the
repository's checkout, as annotation paths are relative to its root.

## GitHub code scanning

To show exolot's issues in a repository's Security tab and as pull request
annotations, upload its SARIF output with GitHub's `upload-sarif` action:

```yaml
jobs:
  exolot:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10
      - run: uvx exolot --format sarif --exit-zero . > exolot.sarif
      - uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: exolot.sarif
          category: exolot
```

Pin the actions to commit SHAs, as you would in your other workflows, since
this job can write security alerts. `--exit-zero` lets the upload step run when there are issues; code
scanning then decides whether a pull request check fails, by its own settings.

## Platforms

Platform-specific builds with a bundled Java runtime exist for `linux-x64`,
`darwin-arm64`, `darwin-x64` and `win32-x64`. On other platforms (such as
Linux on ARM) exolot uses the universal build, which needs Java 17 or later
from `JAVA_HOME`, the `PATH`, or `--java`.

## Notes

- The language server keeps its own state in `~/.sonarlint`, shared with any
  SonarQube for IDE installation you have.
- Telemetry is disabled.
- C/C++ and C# analyzers are not included in the VSIX; the server tries to
  download them from `binaries.sonarsource.com` when it starts.
- Each run starts a fresh JVM and loads every analyzer, so even a single file
  takes around 15 seconds.
- The bundled analyzers are licensed by SonarSource under their own terms. exolot
  downloads them from SonarSource's releases at run time and does not
  redistribute them.

## Development

Development uses [uv](https://docs.astral.sh/uv/) (0.13.6 or later) and [just](https://just.systems/) (1.58.0 or later):

```sh
just sync
uv run exolot --help
just test
just integration      # end-to-end test against the real server (downloads it, about 250 MB)
just self-analyze     # run exolot on its own code (also downloads the server)
just coverage         # tests with a coverage report, coverage.xml and junit.xml
just patch-coverage   # coverage of lines changed since origin/master
just fix              # reformat and autofix lint issues with ruff
just build smoke      # build, then check the wheel installs and runs in a fresh environment
just ci               # what CI's build job runs
```
