"""Rule settings: which rules to turn on or off, and their parameters, in the
format of VS Code's `sonarlint.rules` setting, e.g.
`{"python:S1764": {"level": "off"}, "python:S107": {"level": "on", "parameters": {"max": "5"}}}`.
They come from --rules, or the config file's `rules` or `rules-file`."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# A rule key, `repository:key`, as the setting's schema has it.
RULE_KEY = re.compile(r"[^:]+:[^:]+")
LEVELS = ("on", "off")
PARAMETER_TYPES = (str, int, float, bool)


def load(path: Path) -> dict[str, Any]:
    """The rule settings in the JSON file at path. Raises OSError if it can't
    be read, or ValueError if it isn't JSON or the settings are malformed."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: {e}") from None
    return check(value, str(path))


def check(value: object, where: str) -> dict[str, Any]:
    """value, rule settings from where, with each parameter's value made a
    string, as the setting's schema has them. Raises ValueError if they're malformed:
    not an object of rule keys to objects with only a `level` of "on" or
    "off" and `parameters` of scalar values."""
    if not isinstance(value, dict):
        raise ValueError(f"{where}: rules should be an object of rule keys to settings")
    checked: dict[str, Any] = {}
    for key, setting in value.items():
        checked[key] = _check_rule(key, setting, f"{where}: rule {key!r}")
    return checked


def _check_rule(key: str, setting: object, where: str) -> dict[str, Any]:
    if not RULE_KEY.fullmatch(key):
        raise ValueError(f"{where}: rule keys look like 'python:S1764'")
    if not isinstance(setting, dict):
        raise ValueError(f'{where}: should be an object, e.g. {{"level": "off"}}')
    unknown = set(setting) - {"level", "parameters"}
    if unknown:
        raise ValueError(f"{where}: unknown setting {sorted(unknown)[0]!r} (known: level, parameters)")
    checked: dict[str, Any] = {}
    if "level" in setting:
        if setting["level"] not in LEVELS:
            raise ValueError(f'{where}: level should be "on" or "off"')
        checked["level"] = setting["level"]
    if "parameters" in setting:
        checked["parameters"] = _check_parameters(setting["parameters"], where)
    return checked


def _check_parameters(parameters: object, where: str) -> dict[str, str]:
    if not isinstance(parameters, dict):
        raise ValueError(f"{where}: parameters should be an object")
    checked: dict[str, str] = {}
    for name, value in parameters.items():
        if not isinstance(value, PARAMETER_TYPES):
            raise ValueError(f"{where}: parameter {name!r} should be a string, number or boolean")
        checked[name] = _parameter_string(value)
    return checked


def _parameter_string(value: str | int | float | bool) -> str:
    """value as the string the server parses a parameter from."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
