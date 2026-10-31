"""Check that every workflow step that installs uv or just pins the version
the project requires: pyproject.toml's [tool.uv] required-version minimum and
the justfile's minimum-version."""

import re
import sys
import tomllib
from pathlib import Path

# (action, the `with:` input that pins its version)
UV = ("astral-sh/setup-uv", "version")
JUST = ("extractions/setup-just", "just-version")

_STEP_RE = re.compile(r"^(?P<indent>\s*)- ")
_USES_RE = re.compile(r"^\s*(?:- )?uses:\s*[\"']?(?P<action>[^@\s\"']+)@")
_JUST_MIN_RE = re.compile(r"^set minimum-version := '(?P<version>[^']+)'$", re.MULTILINE)


def steps(text: str) -> list[list[str]]:
    """The outermost YAML sequence items in a workflow (so each job step, but
    not a list nested in one), each as its lines: an item runs from its `- `
    line up to the next line (ignoring blanks and comments) indented no deeper
    than that `- `."""
    result: list[list[str]] = []
    current: list[str] | None = None
    indent = -1
    for line in text.splitlines():
        stripped = line.strip()
        if current is not None and (
            not stripped or stripped.startswith("#") or len(line) - len(line.lstrip()) > indent
        ):
            current.append(line)
        elif match := _STEP_RE.match(line):
            current = [line]
            indent = len(match["indent"])
            result.append(current)
        else:
            current = None
    return result


def pins(text: str, action: str, key: str) -> list[str | None]:
    """The value of key in each step of a workflow that uses action, or None
    where that step doesn't set it."""
    # The whole value, less a trailing comment and quotes, so an unexpected
    # one (`${{ env.UV }}`, `latest`) is reported as written.
    key_re = re.compile(rf"^\s*{re.escape(key)}:\s*(?P<value>.*?)\s*(?:\s#.*)?$")
    found: list[str | None] = []
    for step in steps(text):
        if any((m := _USES_RE.match(line)) and m["action"] == action for line in step):
            values = [m["value"].strip("\"'") for line in step if (m := key_re.match(line))]
            found.append(values[0] if values else None)
    return found


def minimums(root: Path) -> dict[tuple[str, str], str]:
    with (root / "pyproject.toml").open("rb") as f:
        required = tomllib.load(f)["tool"]["uv"]["required-version"]
    if not required.startswith(">="):
        raise ValueError(f"[tool.uv] required-version {required!r} isn't of the form >=X.Y.Z")
    match = _JUST_MIN_RE.search((root / "justfile").read_text())
    if match is None:
        raise ValueError("justfile has no `set minimum-version := '...'`")
    return {UV: required.removeprefix(">="), JUST: match["version"]}


def problems(root: Path) -> tuple[list[str], dict[tuple[str, str], int]]:
    """Each pin that's missing or differs from the minimum, and how many steps
    use each action. No step using one is a problem too, as it more likely
    means steps() or _USES_RE no longer recognize them than that CI stopped
    installing uv or just."""
    want = minimums(root)
    workflows = sorted((root / ".github" / "workflows").glob("*.y*ml"))
    found = []
    counts = dict.fromkeys(want, 0)
    for path in workflows:
        text = path.read_text()
        for (action, key), version in want.items():
            for pin in pins(text, action, key):
                counts[action, key] += 1
                if pin != version:
                    setting = f"{key}: {pin}" if pin else f"no {key}"
                    found.append(f"{path.relative_to(root).as_posix()}: a {action} step has {setting}, not {version}")
    found += [f"no workflow has a {action} step" for (action, _), count in counts.items() if not count]
    return found, counts


def main(root: Path = Path()) -> int:
    found, counts = problems(root)
    for problem in found:
        print(problem, file=sys.stderr)
    if found:
        return 1
    want = minimums(root)
    print(f"workflows pin uv {want[UV]} in {counts[UV]} steps and just {want[JUST]} in {counts[JUST]} steps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
