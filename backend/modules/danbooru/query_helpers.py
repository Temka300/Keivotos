from __future__ import annotations

import re
from typing import Any

RATING_VALUES = ("g", "s", "q", "e", "u")
RATING_QUERY_PATTERN = r"^(?:[gsqeu](?:,[gsqeu])*)$"


def normalize_rating_values(value: str | None) -> list[str]:
    if not value:
        return []
    raw = value.casefold().strip()
    candidates = re.split(r"[,|+\s]+", raw) if re.search(r"[,|+\s]", raw) else list(raw)
    return [rating for rating in RATING_VALUES if rating in candidates]


def user_file_match(alias: str) -> str:
    return (
        f"(({alias}.file_path IS NOT NULL AND {alias}.file_path = f.path) "
        f"OR ({alias}.file_path IS NULL AND {alias}.local_md5 IS NOT NULL "
        f"AND f.local_md5 IS NOT NULL AND {alias}.local_md5 = f.local_md5) "
        f"OR ({alias}.file_path IS NULL AND {alias}.local_md5 IS NULL AND {alias}.file_id = f.id))"
    )


def user_file_lookup_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return (
        f"(({prefix}file_path IS NOT NULL AND {prefix}file_path = ?) "
        f"OR ({prefix}file_path IS NULL AND {prefix}local_md5 IS NOT NULL AND {prefix}local_md5 = ?) "
        f"OR ({prefix}file_path IS NULL AND {prefix}local_md5 IS NULL AND {prefix}file_id = ?))"
    )


def user_file_lookup_params(file_row: dict[str, Any]) -> list[Any]:
    return [file_row.get("path"), file_row.get("local_md5"), file_row.get("file_id")]
