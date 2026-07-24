"""Duplicate-review grouping: which files count as the same content.

Moved verbatim from ``core.py``. A duplicate is the same *content*, keyed by the
gallery-dl filename convention; parent and sibling posts are explicitly not
duplicates. Scope narrows to the same or different folder. No ``core`` import.
"""
from __future__ import annotations

import re


COPY_SUFFIX_RE = re.compile(r"\s+\(\d+\)(?=\.[^.]+$)")


def duplicate_filename_key(filename: str | None) -> str:
    if not filename:
        return ""
    return COPY_SUFFIX_RE.sub("", filename).casefold()


def duplicate_group_expr(alias: str) -> str:
    return f"COALESCE(NULLIF({alias}.local_md5, ''), duplicate_key({alias}.name))"


def duplicate_filter_sql(scope: str) -> str:
    group_expr = duplicate_group_expr("f")
    inner_expr = duplicate_group_expr("df")
    folder_identity = "COALESCE(NULLIF(f.root_id, ''), f.folder, '')"
    inner_folder_identity = "COALESCE(NULLIF(df.root_id, ''), df.folder, '')"
    if scope == "same_folder":
        return f"""({group_expr} || char(31) || {folder_identity}) IN (
            SELECT {inner_expr} || char(31) || {inner_folder_identity}
            FROM files df
            GROUP BY {inner_expr}, {inner_folder_identity}
            HAVING COUNT(*) > 1
        )"""
    if scope == "different_folder":
        return f"""{group_expr} IN (
            SELECT {inner_expr}
            FROM files df
            GROUP BY {inner_expr}
            HAVING COUNT(DISTINCT {inner_folder_identity}) > 1
        )"""
    return f"""{group_expr} IN (
        SELECT {inner_expr}
        FROM files df
        GROUP BY {inner_expr}
        HAVING COUNT(*) > 1
    )"""
