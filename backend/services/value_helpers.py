"""Small, pure value coercions shared across domains.

Extracted verbatim from ``core.py``. Deliberately dependency-free so any layer
can use them without dragging in configuration, database, or module code.
"""
from __future__ import annotations

from typing import Any


def int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def unique_ints(values: list[int | None]) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value is None or value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result
