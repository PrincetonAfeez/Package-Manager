"""Shared JSON loading helpers.

The manifest, lockfile, and registry index are all authoritative project files,
so they are parsed with duplicate-key detection. JSON normally keeps the last
value for a repeated key, which would silently drop an earlier dependency entry.
"""

from __future__ import annotations

import json
from typing import Any


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


def loads_no_duplicate_keys(text: str) -> Any:
    """Parse JSON text, raising ``ValueError`` if any object has duplicate keys.

    ``json.JSONDecodeError`` (a ``ValueError`` subclass) is still raised for
    syntactically malformed input, so callers should catch it first if they want
    to distinguish the two cases.
    """

    return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
