# AGENTS.md

Notes for AI coding agents (and humans) working on exolot.
See `README.md` for what exolot does, how it works, and how to run the tests.

## Commands

CI (`.github/workflows/build.yml`) calls the `justfile`'s recipes rather than running commands inline, so run `just ci` before opening a PR to run everything CI runs.
`just check` runs every check without fixing anything or running tests, `just fix` applies every autofix, and `just --list` shows the individual recipes.
When you add a step to CI, add it as a recipe and include it in `check`, `fix` or `ci` as fits, so `just ci` keeps matching CI.

## Issue labels

Issues are labelled `dimension:value`.
When you file an issue, give it one `type:` and one `priority:` label, a `size:` label unless it's a parent issue, and any `concern:` labels that apply.

- `type:` (exactly one): `bug` (something behaves wrongly), `feature` (a new capability), `improvement` (makes something that already works better), `maintenance` (refactors, dead code, CI, dependencies; no visible change) or `docs` (documentation only).
- `priority:` (exactly one), defined by what to do about it: `p0` (drop everything: a release is broken, e.g. `uvx exolot` fails, or it reports wrong results), `p1` (do next), `p2` (worth doing when convenient) or `p3` (someday/maybe).
- `size:` (exactly one, except on parent issues), by how many PRs it takes rather than hours: `s` (one small PR), `m` (one PR that needs some design) or `l` (several PRs).
  An `l` issue should become a parent issue with sub-issues; parent issues get no `size:` label, their sub-issues do.
- `concern:` (zero or more):
  - `security`: a security risk or hardening, e.g. verifying the VSIX or JRE download.
  - `upstream`: depends on how SonarSource's VSIX or language server behaves, so a new VSIX release can break or change it.
  - `platform`: specific to an OS or architecture, e.g. linux-arm64, which has no platform VSIX.
  - `breaking`: changes CLI flags, output or exit codes that users' scripts rely on.

  These are separate from `type:`, as a security problem can be a bug, a missing feature or a maintenance job.

`question` is for issues that ask something rather than report or request something.
Close duplicates and things that won't be done with GitHub's "duplicate" and "not planned" close reasons; there are no labels for them.

An open issue with no `priority:` label is untriaged; find them with `is:open -label:priority:p0 -label:priority:p1 -label:priority:p2 -label:priority:p3`.
When asked what to work on next, start from the `priority:p1` issues.
Update an issue's labels when you learn more about it, e.g. a fix turns out bigger than its `size:`, or it's split into sub-issues and so loses its `size:`.
Use only these labels: applying a label that doesn't exist creates a new grey one, so a typo or a new value silently adds to the scheme.
Propose a new dimension or value to the owner rather than inventing one.
