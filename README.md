# exolot

Analyze code locally from the command line with the language server from
SonarQube for IDE (formerly SonarLint). No SonarQube account or server needed.

> exolot is an independent project. It is not affiliated with or endorsed by
> SonarSource. "SonarQube" and "SonarLint" are trademarks of SonarSource.

## Why

The old `sonarlint-cli` was discontinued years ago. SonarSource's current
SonarQube CLI needs a SonarQube Cloud or Server account and runs its code
analysis on the server.
exolot fills the gap with account-free analysis that runs entirely on your own
machine. It needs network access only to download the language server the first
time (and see the note on C/C++ and C# below).

## How it works

exolot downloads the SonarQube for IDE extension for VS Code (a `.vsix` zip
file) from the [sonarlint-vscode GitHub
releases](https://github.com/SonarSource/sonarlint-vscode/releases) and checks
its sha256 digest. It unpacks the language server, the language
analyzers and the bundled Java runtime into a cache directory. It then runs the
language server headlessly, opens each file you ask it to analyze and prints
the issues the server reports.

The idea comes from [sonarqube.nvim](https://github.com/iamkarasik/sonarqube.nvim),
which does the same thing for Neovim.

## Usage

```sh
uvx exolot                     # analyze the current directory
uvx exolot src/ tests/foo.py   # analyze specific files or directories
uvx exolot --format json .     # machine-readable output
uvx exolot --format markdown . # a Markdown table, e.g. for a PR comment
uvx exolot --format github-comment . # a report to post as a PR comment
uvx exolot --format sarif .    # SARIF 2.1.0, e.g. for GitHub code scanning
uvx exolot --annotations .     # also show the issues as GitHub Actions annotations
uvx exolot --statistics .      # count issues per rule, most common first
uvx exolot --select python:S1764 . # only the issues of these rules
uvx exolot --rule-param python:S107.max=5 . # set a rule's parameter
uvx exolot --diff-base origin/main --changed-only  # only issues on lines your branch changes
uvx exolot analyze-repo https://github.com/psf/requests  # analyze someone else's code
uvx exolot install             # just download and unpack the server
uvx exolot cache-dir           # show where the server is cached
```

Directories are expanded with `git ls-files` inside a git repository (so
`.gitignore` is respected) and by walking the tree otherwise. Binary files and
files over 2 MiB are skipped.

When the server can't analyze some language, exolot prints a warning for each
cause and says in the summary line how many files weren't analyzed, e.g.
`0 issue(s) in 12 file(s) analyzed; 30 C# file(s) not analyzed (analyzer failed)`.
It spots analyzers the server couldn't download or load, analyzers that failed
(e.g. C# analysis needs `dotnet` installed) and C, C++ and Objective-C files
without a compilation database (see [C, C++ and Objective-C](#c-c-and-objective-c)).
It also warns about errors and warnings the server shows, such as not finding
the Node.js it needs. The `markdown` and `github-comment` formats show these
warnings above the findings, `--annotations` shows them before the issues'
annotations and `sarif` records them as tool execution notifications.
`--log-level error` shows the server's own account of what went wrong. They're
warnings rather than errors, so they don't change the exit status.

Exit status is 0 when no issues are found, 1 when issues are found and 2 on
errors. With `-e` / `--exit-zero` it is 0 even when issues are found, while an
analysis failure still exits with 2 (like ruff's option of the same name).

### C, C++ and Objective-C

The server's C/C++ analyzer needs a compilation database
(`compile_commands.json`) that says how each file is compiled. Make one with
your build, e.g. with [Bear](https://github.com/rizsotto/Bear) (`bear -- make`)
or CMake (`-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`). Bear's database lists only
the files it saw compiled, not headers
([Bear#204](https://github.com/rizsotto/Bear/issues/204)). If header files
get no issues, [compdb](https://github.com/Sarcasm/compdb) can add them (e.g.
`compdb -p . list > /tmp/with-headers.json` for `--compile-commands`).
exolot uses, in this order:

1. `--compile-commands PATH`.
2. The config file's `compile-commands` setting (see [Configuration](#configuration)).
3. The `compile_commands.json` or `build/compile_commands.json` nearest each
   C, C++ or Objective-C file in its directory or an ancestor directory. The
   search stops at the git repository root (or the filesystem root outside a
   repository, as clangd does). `--log-level info` shows which one it found.

The server takes one database for all the files. If different files find
different databases, exolot doesn't send any C, C++ or Objective-C files to the
server. It always skips files that find none. It warns that those files weren't
analyzed. It doesn't check that the database has an entry for each file,
leaving files without an entry to the analyzer. A nonexistent path given with
`--compile-commands` or the config file is an error (exit status 2).

### Analyzing a repository without cloning it yourself

`exolot analyze-repo SOURCE [PATH...]` fetches one commit of the git
repository at SOURCE (a URL or a local repository path) into a temporary
directory without its history or submodules. It analyzes the checkout as
`exolot analyze` would from the clone's root and then deletes the directory.
PATHs are relative to the repository's root and limit the analysis to those
files or directories. Files named by options such as `--rules` and
`--compile-commands` are relative to the current directory, not the clone.
It takes the same options as `analyze` (below) except `--workspace`,
`--diff-base` and `--changed-only`, plus:

- `--ref REF` analyzes a branch, tag or full commit SHA instead of the
  repository's default branch.
- `--keep DIR` clones into DIR (which must not exist or be empty) and leaves
  it there.

It reads the repository's own `.exolot.toml` or `pyproject.toml` (see
[Configuration](#configuration)). For a github.com repository,
`--format markdown` and `github-comment` link each location to that commit
on GitHub unless you give `--link-template` or `--no-links`. For any other
repository they link only when you give `--link-template`, even in GitHub
Actions. GitHub places `--annotations` on files in the workflow's own
checkout, so in a workflow they're only useful for the workflow's own
repository. For another repository, a file at the same path would get the wrong
annotations. `--timeout` covers only the analysis, not fetching the
repository. `git` must be installed, and fetching a private repository uses
git's usual credentials. It exits with status 2 if the repository or REF can't
be fetched.

### Options

- `--server-version TAG` picks a sonarlint-vscode release (default: the
  version exolot was tested with). Unknown versions are downloaded without
  digest verification, with a warning.
- `--platform PLATFORM` overrides the detected VSIX platform (`linux-x64`,
  `darwin-arm64`, `darwin-x64`, `win32-x64`, or `universal`).
- `--java PATH` uses a different Java executable.
- `--node PATH` sets the Node.js used for JavaScript/TypeScript analysis
  (otherwise the server looks for `node` on the `PATH`).
- `--compile-commands PATH` gives the compilation database for C, C++ and
  Objective-C files (see [C, C++ and Objective-C](#c-c-and-objective-c)).
- `--exclude GLOB` skips files matching `GLOB` (repeat it to skip more). As in
  `.gitignore`, a glob with no `/` except perhaps a trailing one matches a
  file or directory name at any depth (`--exclude '*.m'`, `--exclude vendor`).
  Any other glob matches the path relative to the current directory
  (`--exclude src/generated`, or relative to the repository's root for
  `analyze-repo`), so it only applies under that directory. `**` matches any
  number of directories, a trailing `/` matches only directories and
  excluding a directory skips everything under it. Unlike `.gitignore`,
  there's no `!` to re-include files. Separate directories with `/` even on
  Windows. Matching ignores case on macOS and Windows. Excluded files are
  skipped even when you name them as `PATH`s, so a hook that passes exolot a
  list of files still honours the excludes.
- `--rules FILE` reads rule settings from a JSON file in the format of VS
  Code's `sonarlint.rules` setting. The file is an object of rule keys, each
  with an optional `level` (`"on"` or `"off"`) and optional `parameters`, e.g.
  `{"python:S1764": {"level": "off"}, "python:S107": {"level": "on", "parameters": {"max": "5"}}}`.
  Malformed settings are an error (exit status 2). It replaces the config
  file's `rules` or `rules-file` (see [Configuration](#configuration)) rather
  than adding to them.
- `--select RULE[,RULE...]` reports only the issues of the given rules, like
  `ruff check --select` (e.g. `--select python:S1764,python:S107`, repeatable).
  It turns the selected rules on while keeping any parameters from the rule
  settings. A selected rule runs even when `--rules`, the config file's `rules`
  or `rules-file` or the default turns it off. Other rules are still analyzed,
  but their issues aren't reported or counted in the exit status. A malformed
  rule key is an error (exit status 2). A rule the server doesn't know gets a
  warning as a likely typo (unless the server can't list its rules).
- `--rule-param RULE.NAME=VALUE` sets one of a rule's parameters, e.g.
  `--rule-param python:S107.max=5` (repeat it to set more). It applies on top
  of the rule settings (`--rules` or the config file's `rules` or
  `rules-file`), leaving the rule's level and other parameters as they are. It
  doesn't turn a rule on. Use `--select` or the rule settings for that, e.g.
  `--select python:S107 --rule-param python:S107.max=1`. The parameter's name
  follows the rule key's last `.` and its value (which may be empty) follows
  the first `=`. A malformed argument is an error (exit status 2). The server
  doesn't say which parameters a rule has, so a misspelt name is silently
  ignored.
- `--statistics` prints one line per rule instead of the issues, like
  `ruff check --statistics`. Each line shows the issue count, the rule key and
  the rule's name, ordered from most common to least (with ties in rule key
  order). The name is left blank if the server can't list its rules. With
  `--format json` it prints a list of `{"code", "name", "count"}` objects. The
  exit status is the same as without it.
- `--format markdown` prints the issues as a GitHub-flavoured Markdown table
  (Location, Rule and Message), escaping characters Markdown or HTML would
  interpret. With `--statistics` it prints a Count, Rule and Name table. Its
  paths are relative to the root of the git repository each file is in (so
  links work from any subdirectory). Files outside one get paths relative to
  the current directory, or absolute paths if they're outside it too.
- `--link-template TEMPLATE` (with `--format markdown` or `github-comment`)
  links each location to a URL made from TEMPLATE, e.g.
  `--link-template 'https://github.com/OWNER/REPO/blob/SHA/{path}#L{line}'`.
  It fills in `{path}` (URL-quoted with forward slashes), `{line}`, `{column}`,
  `{end_line}` and `{end_column}`. Give the commit the code is from: in a pull
  request workflow `GITHUB_SHA` is the merge commit, so use the PR's head SHA
  instead. In GitHub Actions (when `GITHUB_ACTIONS` is `true`), it defaults to
  links to the commit checked out in the current directory's git repository in
  the workflow's repository (`GITHUB_SERVER_URL` and `GITHUB_REPOSITORY`), so
  the links match the code analyzed.
  `--no-links` turns that off.
- `--format github-comment` prints a Markdown report for a pull request
  comment. It includes an "exolot's findings" heading, the `preamble` from the
  project's config file (see below), the commit analyzed and (in GitHub
  Actions) a link to the workflow run. Then it lists the issues in
  `--format markdown`'s tables with a count, or with `--diff-base` puts those
  on changed lines first. Long reports are cut short to stay under GitHub's
  65,536-character comment limit, with a note saying so.
  exolot doesn't post the comment itself; use `gh pr comment --body-file` or an
  action that posts or updates a comment. It can't be combined with
  `--statistics`.
- `--format sarif` prints a [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html)
  log with one run. Each issue is a result with its rule, message, location and
  level (`error`, `warning`, or `note` for the server's info and hint
  severities), and each violated rule is listed with its name. Issues the
  server reports with secondary locations (`[+1 location]` at the end of the
  message) get them as related locations instead. Paths are relative to
  `%SRCROOT%`, the root of the git repository each file is in (defined in the
  run's `originalUriBaseIds` when all files are in one repository). Files
  outside a repository use absolute `file:` URIs. It can't be combined with
  `--statistics`.
- `--diff-base REF` marks the issues on lines changed since the merge base of
  REF and `HEAD`, like SonarQube's "new code". Changed lines include lines
  added or modified in the working tree (committed or not) and every line of
  untracked files that git doesn't ignore. It looks at the git repository the
  current directory is in, and issues in files outside it count as unchanged.
  An issue is on changed lines if any line of its range or of its secondary
  locations is (so a function's complexity issue counts when a change adds
  nesting to it). Checking secondary locations takes an extra request to the
  server for each such issue in a changed file. JSON output gets a `"changed"`
  boolean field, Markdown output puts changed-line issues first and collapses
  the rest under "Elsewhere", and text output ends those lines with `(changed)`
  and counts them in its summary. `--annotations` puts the issues on changed
  lines first. The exit status still counts every issue, and `--statistics` and
  SARIF output are unaffected. It exits with status 2 if git isn't installed,
  REF isn't a commit or the merge base can't be found. In a shallow clone such
  as `actions/checkout`'s default, fetch enough history first (e.g. with
  `fetch-depth: 0`).
- `--changed-only` (with `--diff-base`) analyzes only the files with changed
  lines and reports only the issues on changed lines in every format. The exit
  status and `--statistics` count only those issues. This lets a project adopt
  exolot in CI without fixing its existing issues first.
- `--annotations` also prints each issue to stderr as a GitHub Actions
  [workflow command](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands)
  (`::warning file=src/a.py,line=12,col=5,endLine=12,endColumn=9,title=python:S1234::message`),
  which GitHub shows as an annotation whatever `--format` prints on stdout (see
  [Workflow annotations](#workflow-annotations)). The command is `error`,
  `warning` or `notice` (for the server's info and hint severities). Paths are
  relative to the root of the git repository each file is in. Files outside a
  repository get paths relative to the current directory, or absolute paths if
  they're outside that too (GitHub can't place either on a diff, so their
  annotations show only in the run). Warnings about files that weren't analyzed
  come first as `::warning` annotations with no file, followed by the issues on
  changed lines when `--diff-base` is used.
- `--log-level LEVEL` shows the server's log messages at `LEVEL` and above,
  where `LEVEL` is `debug`, `info`, `warn` or `error` (by default exolot
  shows none of them). The server only sends `debug` messages when asked for
  them, so the other levels also make it log less. At any level, messages
  without a level show too, and so does anything the server writes to stderr
  (e.g. the JVM's own errors). Errors the server logs while it shuts down,
  such as `ClosedSelectorException`, show only with `debug`. With `debug` or `info`, exolot also shows its
  own progress messages, such as when it downloads the server.
- `-v` / `--verbose` shows all of the server's log messages, the same as
  `--log-level debug`.

## Configuration

exolot reads settings from `.exolot.toml` or the `[tool.exolot]` table of
`pyproject.toml` in the current directory or the nearest parent directory that
has one. It stops searching at the root of the git repository. In each
directory, `.exolot.toml` comes first and a `pyproject.toml` without a
`[tool.exolot]` table is skipped. An unknown setting is an error (exit
status 2). The settings are:

- `preamble`: Markdown that `--format github-comment` puts after its heading,
  e.g. how the project wants its contributors to treat the issues:

  ```toml
  [tool.exolot]
  preamble = "Fix the issues on lines you changed; the rest can wait."
  ```

- `compile-commands`: the C/C++ compilation database, relative to the config
  file's directory, e.g. `compile-commands = "build/compile_commands.json"`.
  `--compile-commands` overrides it.

- `exclude`: a list of file globs to skip, matched like `--exclude`'s but
  relative to the config file's directory, e.g.
  `exclude = ["vendor", "*.m", "generated/**/*.py"]`. `--exclude` adds to it.

- `rules`: rule settings, like `--rules`'s file but as a table, e.g. to turn
  a rule off and set another's parameters in `pyproject.toml` (in
  `.exolot.toml`, the table is `[rules]`):

  ```toml
  [tool.exolot.rules]
  "python:S1764" = { level = "off" }
  "python:S107" = { level = "on", parameters = { max = 5 } }
  ```

  Parameters may be numbers or booleans as well as strings, and exolot passes
  them to the server as strings.

- `rules-file`: a JSON file of rule settings in `--rules`'s format, relative
  to the config file's directory, e.g. `rules-file = "sonarlint-rules.json"`.
  Set `rules` or `rules-file`, not both. `--rules` overrides either.

## Workflow annotations

To show exolot's issues on a pull request's diff and in the workflow run's
summary, without a token or code scanning, add `--annotations`:

```yaml
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: astral-sh/setup-uv@v10
      - run: uvx exolot --annotations --diff-base "origin/$GITHUB_BASE_REF" .
```

The Actions runner turns the `::` lines exolot prints on stderr into
annotations, leaving stdout free for a report in any format. For example,
`--format github-comment --exit-zero > comment.md` writes a report to post as a
PR comment from the same run (`--exit-zero` keeps issues from failing the step
and skipping the comment step). Don't redirect stderr away from the step's log,
or the runner won't see the annotations.

GitHub shows at most 10 annotations of each type (error, warning, notice) per
step and 50 per job. Warnings that some files weren't analyzed (meaning the
issues may be incomplete) come first on the run's summary rather than the diff
so they aren't cut off. Then `--diff-base` puts the issues on the pull
request's changed lines first, and `--changed-only` drops the rest. Run exolot
from the repository's checkout, as annotation paths are relative to its root.

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
this job can write security alerts. `--exit-zero` lets the upload step run when
there are issues, and code scanning then decides from its own settings whether
a pull request check fails.

## Platforms

Platform-specific builds with a bundled Java runtime exist for `linux-x64`,
`darwin-arm64`, `darwin-x64` and `win32-x64`. On other platforms (such as
Linux on ARM) exolot uses the universal build, which needs Java 17 or later
from `JAVA_HOME`, the `PATH` or `--java`.

## Notes

- Each run gives the language server its own temporary state directory and
  deletes it afterwards, so exolot doesn't touch `~/.sonarlint` and concurrent
  runs don't race on its database. The C/C++ and C# analyzers it downloads are
  kept next to the server in exolot's cache (`exolot cache-dir`) for later
  runs. If you set `SONARLINT_USER_HOME`, the server uses that directory
  instead, and exolot leaves it in place.
- Telemetry is disabled.
- C/C++ and C# analyzers are not included in the VSIX, and the server tries to
  download them from `binaries.sonarsource.com` when it starts. If it can't,
  exolot warns that those files weren't analyzed.
- Each run starts a fresh JVM and loads every analyzer, so even a single file
  takes around 15 seconds.
- The bundled analyzers are licensed by SonarSource under their own terms.
  exolot downloads them from SonarSource's releases at run time and does not
  redistribute them.

## Development

Development uses [uv](https://docs.astral.sh/uv/) (0.13.6 or later) and [just](https://just.systems/) (1.58.0 or later):

```sh
just sync
uv run exolot --help
just test
just integration      # end-to-end test against the real server (downloads it, about 250 MB)
just self-analyze     # run exolot on its own code (also downloads the server)
just coverage         # tests with a coverage report and coverage.xml
just patch-coverage   # coverage of lines changed since origin/master
just fix              # reformat and autofix lint issues with ruff
just build smoke      # build, then check the wheel installs and runs in a fresh environment
just ci               # what CI's build job runs
```
