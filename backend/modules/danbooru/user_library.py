"""Tag-name normalization and favorite-tag combo helpers.

Extracted verbatim from ``core.py``'s Blacklist Tags and Favorite Tags sections.
They move together because the combo helpers normalize through
``normalize_tag_name``. No inbound dependency on ``core``.

The historical underscore-prefixed names are kept as aliases because the
user-library router still imports them by those names through the compatibility
facade; they are re-exported by ``core`` unchanged.
"""
from __future__ import annotations

import json
import re
from typing import Any

from models import FavoriteTagComboInfo


def normalize_tag_name(tag_name: str) -> str:
    return re.sub(r"\s+", "_", tag_name.strip().lower())


def normalize_combo_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        name = normalize_tag_name(tag)
        if not name or name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized


def combo_key(tags: list[str]) -> str:
    return "\n".join(sorted(tags))


def combo_name(name: str | None, tags: list[str]) -> str:
    if name and name.strip():
        return name.strip()
    return " + ".join(tag.replace("_", " ") for tag in tags[:4])


def combo_from_row(row: dict[str, Any]) -> FavoriteTagComboInfo:
    return FavoriteTagComboInfo(
        id=row["id"],
        name=row["name"],
        tags=json.loads(row["tags_json"]),
        added_at=row["added_at"],
    )


# Compatibility aliases for the existing private names used by the router.
_normalize_tag_name = normalize_tag_name
_normalize_combo_tags = normalize_combo_tags
_combo_key = combo_key
_combo_name = combo_name
_combo_from_row = combo_from_row
