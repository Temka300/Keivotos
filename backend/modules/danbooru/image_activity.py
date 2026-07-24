"""Per-image user activity: view counts, Heart Spam, and user-added tags.

Moved verbatim from ``core.py``. All of this is irreplaceable user data in
``user.sqlite``, matched to files by durable identity rather than row id, so it
survives a full rebuild of the disposable index. No ``core`` import.
"""
from __future__ import annotations

from typing import Any

from services.query_helpers import user_file_lookup_params, user_file_lookup_sql
from services.tag_names import normalize_user_tag_category


def user_image_tags_for_file(conn, file_row: dict[str, Any]) -> dict[str, list[str]]:
    rows = conn.execute(
        f"""SELECT tag_category, tag_name
            FROM user_image_tags
            WHERE {user_file_lookup_sql()}
            ORDER BY tag_category, tag_name""",
        user_file_lookup_params(file_row),
    ).fetchall()
    tags: dict[str, list[str]] = {}
    for row in rows:
        category = normalize_user_tag_category(row["tag_category"])
        tags.setdefault(category, []).append(row["tag_name"])
    return tags


def image_view_for_file(conn, file_row: dict[str, Any]) -> dict[str, Any] | None:
    return conn.execute(
        f"""SELECT file_id, file_path, local_md5, view_count, heart_spam_count, first_viewed_at, last_viewed_at
            FROM image_views
            WHERE {user_file_lookup_sql()}
            ORDER BY last_viewed_at DESC
            LIMIT 1""",
        user_file_lookup_params(file_row),
    ).fetchone()


def earliest_timestamp(*values: str | None) -> str | None:
    timestamps = [value for value in values if value]
    return min(timestamps) if timestamps else None


def latest_timestamp(*values: str | None) -> str | None:
    timestamps = [value for value in values if value]
    return max(timestamps) if timestamps else None


def record_image_view(conn, file_row: dict[str, Any]) -> dict[str, Any]:
    existing = conn.execute(
        f"""SELECT rowid as rowid, file_id, view_count, heart_spam_count, first_viewed_at
            FROM image_views
            WHERE {user_file_lookup_sql()}
            ORDER BY last_viewed_at DESC
            LIMIT 1""",
        user_file_lookup_params(file_row),
    ).fetchone()

    if existing:
        previous_count = int(existing["view_count"] or 0)
        previous_heart_spam_count = int(existing["heart_spam_count"] or 0)
        first_viewed_at = existing["first_viewed_at"]
        if existing["file_id"] != file_row["file_id"]:
            conflict = conn.execute(
                "SELECT rowid as rowid, view_count, heart_spam_count, first_viewed_at FROM image_views WHERE file_id=?",
                (file_row["file_id"],),
            ).fetchone()
            if conflict and conflict["rowid"] != existing["rowid"]:
                previous_count += int(conflict["view_count"] or 0)
                previous_heart_spam_count += int(conflict["heart_spam_count"] or 0)
                first_viewed_at = earliest_timestamp(first_viewed_at, conflict["first_viewed_at"])
                conn.execute("DELETE FROM image_views WHERE rowid=?", (conflict["rowid"],))

        conn.execute(
            """UPDATE image_views
               SET file_id=?,
                   file_path=?,
                   local_md5=COALESCE(?, local_md5),
                   view_count=?,
                   heart_spam_count=?,
                   first_viewed_at=COALESCE(?, first_viewed_at, datetime('now')),
                   last_viewed_at=datetime('now')
               WHERE rowid=?""",
            (
                file_row["file_id"],
                file_row["path"],
                file_row.get("local_md5"),
                previous_count + 1,
                previous_heart_spam_count,
                first_viewed_at,
                existing["rowid"],
            ),
        )
    else:
        conn.execute(
            """INSERT INTO image_views
               (file_id, file_path, local_md5, view_count, heart_spam_count, first_viewed_at, last_viewed_at)
               VALUES (?, ?, ?, 1, 0, datetime('now'), datetime('now'))
               ON CONFLICT(file_id) DO UPDATE SET
                   file_path=excluded.file_path,
                   local_md5=COALESCE(excluded.local_md5, image_views.local_md5),
                   view_count=COALESCE(image_views.view_count, 0) + 1,
                   heart_spam_count=COALESCE(image_views.heart_spam_count, 0),
                   first_viewed_at=COALESCE(image_views.first_viewed_at, datetime('now')),
                   last_viewed_at=datetime('now')""",
            (file_row["file_id"], file_row["path"], file_row.get("local_md5")),
        )
    conn.commit()
    return image_view_for_file(conn, file_row) or {
        "view_count": 0,
        "heart_spam_count": 0,
        "first_viewed_at": None,
        "last_viewed_at": None,
    }


def record_heart_spam(conn, file_row: dict[str, Any]) -> dict[str, Any]:
    existing = conn.execute(
        f"""SELECT rowid as rowid, file_id, view_count, heart_spam_count, first_viewed_at, last_viewed_at
            FROM image_views
            WHERE {user_file_lookup_sql()}
            ORDER BY last_viewed_at DESC
            LIMIT 1""",
        user_file_lookup_params(file_row),
    ).fetchone()

    if existing:
        view_count = int(existing["view_count"] or 0)
        heart_spam_count = int(existing["heart_spam_count"] or 0)
        first_viewed_at = existing["first_viewed_at"]
        last_viewed_at = existing["last_viewed_at"]
        if existing["file_id"] != file_row["file_id"]:
            conflict = conn.execute(
                """SELECT rowid as rowid, view_count, heart_spam_count, first_viewed_at, last_viewed_at
                   FROM image_views WHERE file_id=?""",
                (file_row["file_id"],),
            ).fetchone()
            if conflict and conflict["rowid"] != existing["rowid"]:
                view_count += int(conflict["view_count"] or 0)
                heart_spam_count += int(conflict["heart_spam_count"] or 0)
                first_viewed_at = earliest_timestamp(first_viewed_at, conflict["first_viewed_at"])
                last_viewed_at = latest_timestamp(last_viewed_at, conflict["last_viewed_at"])
                conn.execute("DELETE FROM image_views WHERE rowid=?", (conflict["rowid"],))

        conn.execute(
            """UPDATE image_views
               SET file_id=?,
                   file_path=?,
                   local_md5=COALESCE(?, local_md5),
                   view_count=?,
                   heart_spam_count=?,
                   first_viewed_at=?,
                   last_viewed_at=?
               WHERE rowid=?""",
            (
                file_row["file_id"],
                file_row["path"],
                file_row.get("local_md5"),
                view_count,
                heart_spam_count + 1,
                first_viewed_at,
                last_viewed_at,
                existing["rowid"],
            ),
        )
    else:
        conn.execute(
            """INSERT INTO image_views
               (file_id, file_path, local_md5, view_count, heart_spam_count, first_viewed_at, last_viewed_at)
               VALUES (?, ?, ?, 0, 1, NULL, NULL)
               ON CONFLICT(file_id) DO UPDATE SET
                   file_path=excluded.file_path,
                   local_md5=COALESCE(excluded.local_md5, image_views.local_md5),
                   heart_spam_count=COALESCE(image_views.heart_spam_count, 0) + 1""",
            (file_row["file_id"], file_row["path"], file_row.get("local_md5")),
        )
    conn.commit()
    return image_view_for_file(conn, file_row) or {
        "view_count": 0,
        "heart_spam_count": 0,
        "first_viewed_at": None,
        "last_viewed_at": None,
    }
