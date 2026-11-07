"""Settings from a project's config file: a `.exolot.toml`, or the
`[tool.exolot]` table of a `pyproject.toml`."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import rules
from .exclude import is_empty
from .jsontypes import is_json_object


class ConfigError(Exception):
    pass


@dataclass(frozen=True, kw_only=True)
class Config:
    # Markdown that --format github-comment puts after its heading.
    preamble: str | None = None
    # The C/C++ compilation database, made absolute against the config file's directory.
    compile_commands: Path | None = None
    # Glob patterns of files to skip.
    exclude: tuple[str, ...] = ()
    # The `rules` table's rule settings, checked, if it has one.
    rules: dict[str, Any] | None = None
    # The JSON file of rule settings, made absolute against the config file's directory.
    rules_file: Path | None = None
    # The file the settings came from, if any.
    path: Path | None = None


# Each setting's name in the file, with its type there.
SETTINGS = {"preamble": str, "compile-commands": str, "exclude": list, "rules": dict, "rules-file": str}
PYPROJECT = "pyproject.toml"


def find(start: Path) -> Path | None:
    """The config file for start: in start or the nearest of its parents with
    one, but no higher than the git repository start is in. In each directory,
    `.exolot.toml` comes first, then a `pyproject.toml` with a `[tool.exolot]`
    table."""
    for d in (start, *start.parents):
        if (d / ".exolot.toml").is_file():
            return d / ".exolot.toml"
        pyproject = d / PYPROJECT
        tool = _read(pyproject).get("tool") if pyproject.is_file() else None
        if is_json_object(tool) and "exolot" in tool:
            return pyproject
        if (d / ".git").exists():
            return None
    return None


def load(start: Path) -> Config:
    """The settings in start's config file (see find), or the defaults if it
    has none. Raises ConfigError if the file can't be read or a setting is
    unknown or the wrong type."""
    path = find(start)
    if path is None:
        return Config()
    data = _read(path)
    table: object
    if path.name == PYPROJECT:
        table = data["tool"]["exolot"]
        where = f"{path} [tool.exolot]"
    else:
        table = data
        where = f"{path}"
    if not is_json_object(table):
        raise ConfigError(f"{where}: should be a table")
    for key, value in table.items():
        if key not in SETTINGS:
            raise ConfigError(f"{where}: unknown setting {key!r} (known: {', '.join(SETTINGS)})")
        if not isinstance(value, SETTINGS[key]):
            raise ConfigError(f"{where}: {key} should be a {SETTINGS[key].__name__}")
    compile_commands = table.get("compile-commands")
    exclude = _exclude(table.get("exclude", []), where)
    if "rules" in table and "rules-file" in table:
        raise ConfigError(f"{where}: set rules or rules-file, not both")
    try:
        rule_settings = rules.check(table["rules"], where) if "rules" in table else None
    except ValueError as e:
        raise ConfigError(str(e)) from None
    rules_file = table.get("rules-file")
    return Config(
        preamble=table.get("preamble"),
        compile_commands=_relative_path(path, compile_commands),
        exclude=exclude,
        rules=rule_settings,
        rules_file=_relative_path(path, rules_file),
        path=path,
    )


def _relative_path(config_file: Path, value: str | None) -> Path | None:
    """value, a path relative to config_file's directory, made absolute."""
    return None if value is None else config_file.parent.joinpath(value).resolve()


def _exclude(value: list[object], where: str) -> tuple[str, ...]:
    """The exclude setting's globs. Raises ConfigError if one isn't a string
    or is empty."""
    globs = tuple(v for v in value if isinstance(v, str))
    if len(globs) != len(value):
        raise ConfigError(f"{where}: exclude should be a list of str")
    if any(is_empty(v) for v in globs):
        raise ConfigError(f"{where}: exclude has an empty glob, which would match nothing")
    return globs


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None
    except OSError as e:
        raise ConfigError(f"can't read {path}: {e}") from None
