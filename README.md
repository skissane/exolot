# exolot

Analyze code locally from the command line with the language server from SonarQube for IDE (formerly SonarLint) no SonarQube account or server needed.

> exolot is an independent project. It is not affiliated with or endorsed by
> SonarSource. "SonarQube" and "SonarLint" are trademarks of SonarSource.

## Why

The old `sonarlint-cli` was discontinued years ago.
SonarSource's current SonarQube CLI needs a SonarQube Cloud or Server account.
Also its code analysis runs on the server.
Exolot fills the gap: account-free analysis that runs entirely on your own machine.
It needs network access only to download the language server the first time (and see the note on C/C++ and C# below).

## How it works

Exolot downloads the SonarQube for IDE extension for VS Code (a `.vsix` file.
This is a zip) from the [sonarlint-vscode GitHub releases](https://github.com/SonarSource/sonarlint-vscode/releases) checks its sha256 digest and unpacks the language server.
The language analyzers and the bundled Java runtime into a cache directory it then runs the language server headlessly.
Opens each file you ask it to analyze and prints the issues the server reports.

The idea comes from [sonarqube.nvim](https://github.com/iamkarasik/sonarqube.nvim) this does the same thing for Neovim.

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

Directories are expanded with `git ls-files` when inside a git repository (so `.gitignore` is respected) and by walking the tree otherwise.
Binary files and files over 2 MiB are skipped.

When the server can't analyze some language.
Exolot prints a warning for each cause and says in the summary line how many files weren't analyzed.
`0 issue(s) in 12 file(s) analyzed.
30 C# file(s) not analyzed (analyzer failed)`.
The causes it spots are an analyzer the server couldn't download or load an analyzer that failed (e.g c# analysis needs `dotnet` installed) and C.
C++ and Objective-C files without a compilation database (see [C c++ and Objective-C](#c-c-and-objective-c)).
It also warns about the errors and warnings the server shows.
Such as not finding the Node.js it needs.
The `markdown` and `github-comment` formats show these warnings above the findings `--annotations` before the issues' annotations.
Also `sarif` as the run's tool execution notifications.
`--log-level error` shows the server's own account of what went wrong they're warnings not errors so they don't change the exit status.

Exit status is 0 when no issues are found 1 when issues are found and 2 on errors.
With `-e` / `--exit-zero` it is 0 even when issues are found but still 2 when the analysis fails like ruff's option of the same name.

### C, C++ and Objective-C

The server's C/C++ analyzer needs a compilation database (`compile_commands.json`) this says how each file is compiled make one with your build.
With [Bear](https://github.com/rizsotto/Bear) (`bear -- make`) or CMake (`-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`).
Bear's database lists only the files it saw compiled not headers ([Bear#204](https://github.com/rizsotto/Bear/issues/204)) if header files get no issues [compdb](https://github.com/Sarcasm/compdb) can add them `compdb -p  list > /tmp/with-headers.json` then pass that file as `--compile-commands` exolot uses in this order:.

1. `--compile-commands PATH`.
   2.
   The config file's `compile-commands` setting (see [Configuration](#configuration)) 3.
   The `compile_commands.json` or `build/compile_commands.json` nearest each C c++ or Objective-C file.
   In its directory or the directories above it.
   Up to the root of the git repository it's in (or the filesystem's root outside one as clangd does) `--log-level info` shows which one it found.

The server takes one database for all the files so if different files find different ones exolot doesn't send any C c++ or Objective-C files to the server.
It also doesn't send the files that find none it warns that those files weren't analyzed.
It doesn't check that the database has an entry for each file.
What the analyzer does with a file that has none is up to it.
A path given with `--compile-commands` or the config file that doesn't exist is an error (exit status 2).

### Analyzing a repository without cloning it yourself

`exolot analyze-repo SOURCE [PATH...]` fetches one commit of the git repository at SOURCE (a URL.
Or a local repository's path) into a temporary directory without its history or submodules.
Analyzes it as `exolot analyze` would from the clone's root and deletes the directory pATHs relative to the repository's root.
Limit the analysis to those files or directories files named by its options such as as `--rules` and `--compile-commands` are relative to the current directory not the clone.
It takes the same options as `analyze` (below) except `--workspace` `--diff-base` and `--changed-only` plus:.

- `--ref REF` analyzes a branch.
  Tag or full commit SHA instead of the repository's default branch.
  - `--keep DIR` clones into DIR (which must not exist or be empty) and leaves it there.

It reads the repository's own `.exolot.toml` or `pyproject.toml` (see [Configuration](#configuration)) for a github.com repository.
`--format markdown` and `github-comment` link each location to that commit on GitHub unless you give `--link-template` or `--no-links`.
For any other repository they link only if you give `--link-template` even in GitHub Actions.
GitHub places `--annotations` on files in the workflow's own checkout.
So in a workflow they're only useful for the workflow's own repository: for another one.
A file at the same path would get the wrong annotations `--timeout` covers only the analysis not fetching the repository `git` must be installed.
Also fetching a private repository uses git's usual credentials.
It exits with status 2 if the repository or REF can't be fetched.

### Options

- `--server-version TAG` picks a sonarlint-vscode release (default: the version exolot was tested with).
  Unknown versions are downloaded without digest verification with a warning.
  - `--platform PLATFORM` overrides the detected VSIX platform (`linux-x64`.
  `darwin-arm64` `darwin-x64` `win32-x64` or `universal`).
  - `--java PATH` uses a different Java executable.
  - `--node PATH` sets the Node.js used for JavaScript/TypeScript analysis (otherwise the server looks for `node` on the `PATH`).
  - `--compile-commands PATH` gives the compilation database for C.
  C++ and Objective-C files (see [C c++ and Objective-C](#c-c-and-objective-c)).
  - `--exclude GLOB` skips files matching `GLOB`.
  Repeat it to skip more as in `.gitignore`.
  A glob with no `/` except perhaps a trailing one matches a file or directory name at any depth (`--exclude '*.m'` `--exclude vendor`).
  Also any other glob matches the path relative to the current directory (`--exclude src/generated` for `analyze-repo` relative to the repository's root).
  So it only applies to files under that directory `**` matches any number of directories a trailing `/` matches only directories.
  Also excluding a directory skips everything under it unlike `.gitignore` there's no `!` to re-include files separate directories with `/` even on Windows matching ignores case on macOS and Windows.
  Excluded files are skipped even when you name them as `PATH`s.
  So a hook that passes exolot a list of files still honours the excludes.
  - `--rules FILE` reads rule settings from a JSON file.
  In the same format as VS Code's `sonarlint.rules` setting: an object of rule keys.
  Each with an optional `level` of `"on"` or `"off"` and the rule's optional `parameters` `{"python:S1764": {"level": "off"} "python:S107": {"level": "on" "parameters": {"max": "5"}}}`.
  Malformed settings are an error (exit status 2).
  It replaces the config file's `rules` or `rules-file` (see [Configuration](#configuration)) rather than adding to them.
  - `--select RULE[,RULE...]` reports only the issues of the given rules.
  Like `ruff check --select` `--select python:S1764,python:S107` repeat it to select more it turns the selected rules on.
  Keeping any parameters the rule settings give them.
  So a rule shows up even if `--rules` or the config file's `rules` or `rules-file` turn it off or it's off by default other rules are still analyzed.
  But their issues aren't reported or counted in the exit status.
  A malformed rule key is an error (exit status 2).
  Also a rule the server doesn't know gets a warning.
  As it's likely a typo (unless the server can't list its rules).
  - `--rule-param RULE.NAME=VALUE` sets one of a rule's parameters.
  E.g `--rule-param python:S107.max=5` repeat it to set more.
  It applies on top of the rule settings (`--rules` or the config file's `rules` or `rules-file`).
  Leaving the rule's level and other parameters as they are.
  So it doesn't turn a rule on: use `--select` or the rule settings for that `--select python:S107 --rule-param python:S107.max=1`.
  The parameter's name follows the rule key's last `.`.
  Also its value (which may be empty) follows the first `=`.
  A malformed argument is an error (exit status 2).
  The server doesn't say which parameters a rule has so a misspelt name is silently ignored.
  - `--statistics` prints one line per rule instead of the issues: the number of issues.
  The rule key and the rule's name.
  Most common rule first (ties in rule key order) like `ruff check --statistics`.
  The name is left blank if the server can't list its rules.
  With `--format json` it prints a list of `{"code" "name" "count"}` objects.
  The exit status is the same as without it.
  - `--format markdown` prints the issues as a GitHub-flavoured Markdown table (Location.
  Rule and Message).
  With characters Markdown or HTML would interpret escaped and `--statistics` as a Count rule and Name table.
  Its paths are relative to the root of the git repository each file is in (so links work from any subdirectory).
  Files outside one get paths relative to the current directory.
  Or absolute paths if they're outside it too.
  - `--link-template TEMPLATE` (with `--format markdown` or `github-comment`) links each location to a URL made from TEMPLATE.
  Filling in `{path}` (URL-quoted with forward slashes) `{line}` `{column}` `{end_line}` and `{end_column}` `--link-template 'https://github.com/OWNER/REPO/blob/SHA/{path}#L{line}'`.
  Give the commit the code is from: in a pull request's workflow `GITHUB_SHA` is the merge commit so use the PR's head SHA instead.
  In GitHub Actions (when `GITHUB_ACTIONS` is `true`).
  It defaults to links to the commit checked out in the current directory's git repository.
  In the workflow's repository (`GITHUB_SERVER_URL` and `GITHUB_REPOSITORY`) so the links match the code analyzed `--no-links` turns that off.
  - `--format github-comment` prints a Markdown report for a pull request comment: an "exolot's findings" heading.
  The `preamble` from the project's config file (see below) the commit analyzed and in GitHub Actions a link to the workflow run.
  Then the issues in `--format markdown`'s tables with a count.
  Or with `--diff-base` those on changed lines first it's cut short with a note saying so.
  To stay under GitHub's 65,536-character limit for a comment.
  Exolot doesn't post it: use `gh pr comment --body-file`.
  Or an action that posts or updates a comment it can't be combined with `--statistics`.
  - `--format sarif` prints a [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html) log with one run: each issue is a result with its rule.
  Message level (`error` `warning`.
  Or `note` for the server's info and hint severities) and location.
  Also each rule an issue breaks is listed with its name.
  Issues the server reports with secondary locations (`[+1 location]` at the end of the message) get them as related locations instead paths are relative to `%SRCROOT%`.
  The root of the git repository each file is in (defined in the run's `originalUriBaseIds` when all the files are in one repository).
  Or absolute `file:` URIs for files outside one it can't be combined with `--statistics`.
  - `--diff-base REF` marks the issues on lines changed since the merge base of REF and `HEAD`.
  Like SonarQube's "new code": lines added or modified in the working tree (committed or not).
  Also every line of files git doesn't track yet (unless it ignores them).
  It looks at the git repository the current directory is in.
  Issues in files outside it count as unchanged.
  An issue is on changed lines if any line of its range or of its secondary locations is (so a function's complexity issue counts when a change adds nesting to it).
  This takes an extra request to the server for each issue with secondary locations in a changed file.
  JSON output gets a `"changed": true` or `false` field.
  Markdown output puts the issues on changed lines first and collapses the rest under "Elsewhere".
  Also text output ends those lines with `(changed)` and counts them in its summary.
  `--annotations` puts the issues on changed lines first the exit status still counts every issue and `--statistics` and SARIF output are unaffected.
  It exits with status 2 if git isn't installed rEF isn't a commit.
  Or the merge base can't be found (in a shallow clone such as as `actions/checkout`'s default fetch enough history first with `fetch-depth: 0`).
  - `--changed-only` (with `--diff-base`) analyzes only the files with changed lines.
  Also reports only the issues on changed lines in every format.
  The exit status and `--statistics` count only those.
  This lets a project adopt exolot in CI without fixing its existing issues first.
  - `--annotations` also prints each issue to stderr as a GitHub Actions [workflow command](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands) (`::warning file=src/a.py,line=12,col=5,endLine=12,endColumn=9,title=python:S1234::message`).
  This GitHub shows as an annotation whatever `--format` prints on stdout see [Workflow annotations](#workflow-annotations) the command is `error`.
  `warning` or `notice` (for the server's info and hint severities).
  Also paths are relative to the root of the git repository each file is in (files outside one get paths relative to the current directory or absolute if they're outside that too gitHub can't place either on a diff.
  So their annotations show only in the run).
  Warnings about files that weren't analyzed come first as `::warning` annotations with no file.
  Then with `--diff-base` the issues on changed lines.
  - `--log-level LEVEL` shows the server's log messages at `LEVEL` and above.
  There `LEVEL` is `debug` `info`.
  `warn` or `error` (by default exolot shows none of them).
  The server only sends `debug` messages when asked for them.
  So the other levels also make it log less at any level messages without a level show too.
  Also so does anything the server writes to stderr (e.g the JVM's own errors).
  Errors the server logs while it shuts down such as as `ClosedSelectorException` show only with `debug` with `debug` or `info` exolot also shows its own progress messages such as as when it downloads the server.
  - `-v` / `--verbose` shows all of the server's log messages.
  The same as `--log-level debug`.

## Configuration

Exolot reads settings from a `.exolot.toml` file.
Or the `[tool.exolot]` table of a `pyproject.toml`.
In the current directory or the nearest parent that has one (but not above the root of the git repository it's in) in each directory `.exolot.toml` comes first.
A `pyproject.toml` without a `[tool.exolot]` table is skipped.
An unknown setting is an error (exit status 2) the settings are:.

- `preamble`: Markdown that `--format github-comment` puts after its heading, e.g.
  How the project wants its contributors to treat the issues:.

  ```toml
  [tool.exolot]
  preamble = "Fix the issues on lines you changed; the rest can wait."
  ```

- `compile-commands`: the C/C++ compilation database.
  Relative to the config file's directory `compile-commands = "build/compile_commands.json"` `--compile-commands` overrides it.

- `exclude`: a list of file globs to skip.
  Matched like `--exclude`'s but relative to the config file's directory `exclude = ["vendor" "*.m" "generated/**/*.py"]` `--exclude` adds to it.

- `rules`: rule settings.
  Like `--rules`'s file but as a table.
  To turn a rule off and set another's parameters in a `pyproject.toml` (in a `.exolot.toml` the table is `[rules]`):.

  ```toml
  [tool.exolot.rules]
  "python:S1764" = { level = "off" }
  "python:S107" = { level = "on", parameters = { max = 5 } }
  ```

Parameters may be numbers or booleans as well as strings.
Exolot passes them to the server as strings.

- `rules-file`: a JSON file of rule settings in `--rules`'s format.
  Relative to the config file's directory `rules-file = "sonarlint-rules.json"` set `rules` or `rules-file` not both `--rules` overrides either.

## Workflow annotations

To show exolot's issues on a pull request's diff and in the workflow run's summary without a token or code scanning add `--annotations`:.

```yaml
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: astral-sh/setup-uv@v10
      - run: uvx exolot --annotations --diff-base "origin/$GITHUB_BASE_REF" .
```

The Actions runner turns the `::` lines exolot prints on stderr into annotations.
So stdout is free for a report in any format.
`--format github-comment --exit-zero > comment.md` to post as a PR comment from the same run (`--exit-zero` so the issues don't fail the step and skip the one that posts it).
Don't redirect stderr away from the step's log or the runner won't see them.

GitHub shows at most 10 annotations of each type (error warning notice) per step and 50 per job.
So that a warning that some files weren't analyzed (meaning the issues may be incomplete) isn't cut off those come first.
On the run's summary rather than the diff.
Then `--diff-base` puts the issues on the pull request's changed lines first and `--changed-only` drops the rest run exolot from the repository's checkout.
As annotation paths are relative to its root.

## GitHub code scanning

To show exolot's issues in a repository's Security tab and as pull request annotations, upload its SARIF output with GitHub's `upload-sarif` action:.

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

Pin the actions to commit SHAs as you would in your other workflows since this job can write security alerts.
`--exit-zero` lets the upload step run when there are issues.
Code scanning then decides whether a pull request check fails by its own settings.

## Platforms

Platform-specific builds with a bundled Java runtime exist for `linux-x64` `darwin-arm64` `darwin-x64` and `win32-x64`.
On other platforms (such as Linux on ARM) exolot uses the universal build.
This needs Java 17 or later from `JAVA_HOME` the `PATH` or `--java`.

## Notes

- Each run gives the language server its own temporary state directory and deletes it afterwards.
  So exolot doesn't touch `~/.sonarlint` and concurrent runs don't race on its database.
  The C/C++ and C# analyzers it downloads are kept next to the server in exolot's cache (`exolot cache-dir`) for later runs if you set `SONARLINT_USER_HOME` the server uses that directory instead and exolot leaves it in place.
  - Telemetry is disabled.
  - C/C++ and C# analyzers are not included in the VSIX.
  The server tries to download them from `binaries.sonarsource.com` when it starts if it can't exolot warns that those files weren't analyzed.
  - Each run starts a fresh JVM and loads every analyzer.
  So even a single file takes around 15 seconds.
  - The bundled analyzers are licensed by SonarSource under their own terms.
  Exolot downloads them from SonarSource's releases at run time and does not redistribute them.

## Development

Development uses [uv](https://docs.astral.sh/uv/) (0.13.6 or later) and [just](https://just.systems/) (1.58.0 or later):.

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
