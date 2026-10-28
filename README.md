# exolot

Analyze code locally from the command line with the language server from
SonarQube for IDE (formerly SonarLint). No SonarQube account or server needed.

> exolot is an independent project. It is not affiliated with or endorsed by
> SonarSource. "SonarQube" and "SonarLint" are trademarks of SonarSource.

## Why

The old `sonarlint-cli` was discontinued years ago. SonarSource's current
SonarQube CLI needs a SonarQube Cloud or Server account, and its code analysis
runs on the server. exolot fills the gap: fully offline, account-free analysis
on your own machine.

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
uvx exolot install             # just download and unpack the server
uvx exolot cache-dir           # show where the server is cached
```

Directories are expanded with `git ls-files` when inside a git repository (so
`.gitignore` is respected), and by walking the tree otherwise. Binary files and
files over 2 MiB are skipped.

Exit status is 0 when no issues are found, 1 when issues are found, and 2 on
errors.

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
- `-v` / `--verbose` shows the server's logs.

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
- Each run starts a fresh JVM and loads every analyzer, so expect a few
  seconds of startup time.
- The bundled analyzers are licensed by SonarSource under their own terms. exolot
  downloads them from SonarSource's releases at run time and does not
  redistribute them.

## Development

```sh
uv sync
uv run exolot --help
uv run pytest
```
