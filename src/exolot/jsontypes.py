"""Narrowing parsed JSON (or TOML) for the type checker."""

from __future__ import annotations

from typing import Any, TypeGuard


def is_json_object(value: object) -> TypeGuard[dict[str, Any]]:
    """Whether value, parsed from JSON or TOML, is an object (a table, in
    TOML). Their keys are always strings, so only the values are unknown,
    unlike after isinstance(value, dict), which leaves the keys unknown too."""
    return isinstance(value, dict)
