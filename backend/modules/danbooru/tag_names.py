"""Tag-name vocabulary and normalization.

Extracted verbatim from ``core.py``. Dependency-free, which is what lets the
search, tag-wiki, and artist domains stop reaching back into ``core`` for it.

``normalize_search_tag`` and ``normalize_user_tag`` currently have identical
bodies. They are kept as two functions on purpose: one normalizes a term typed
into search, the other a tag the user attaches to a file, and those two grammars
are free to diverge. Collapsing them would couple the search syntax to the
user-tag rules for no gain.
"""
from __future__ import annotations

import re


TAG_CATEGORIES = {"artist", "character", "copyright", "general", "meta", "unknown"}


def normalize_search_tag(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip().strip("\"'").lower())


def normalize_user_tag(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip().strip("\"'").lower())


def normalize_user_tag_category(value: str | None) -> str:
    category = (value or "general").strip().lower()
    return category if category in TAG_CATEGORIES else "general"
