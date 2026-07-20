"""Record manual Danbooru refresh removals in rebuild-proof user storage."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import database
from config import DATA_ROOT, SIDECAR_DIR
from database import get_data_db, get_user_db
from storage_layout import load_library_roots, sidecar_candidates


def _payload_tags(payload: dict[str, Any]) -> set[str]:
    tags = payload.get("tags") or {}
    if not isinstance(tags, dict):
        return set()
    all_tags = tags.get("all")
    if isinstance(all_tags, list):
        return {str(tag) for tag in all_tags if tag}
    return {
        str(tag)
        for values in tags.values()
        if isinstance(values, list)
        for tag in values
        if tag
    }


def _current_sidecar_path(media_path: Path) -> Path | None:
    for candidate in sidecar_candidates(
        media_path,
        ".danbooru.json",
        DATA_ROOT,
        SIDECAR_DIR,
        load_library_roots(database.USER_DB_PATH),
    ):
        if candidate.exists():
            return candidate
    return None


def _identity_for(media_path: Path, local_md5: str | None) -> dict[str, Any]:
    with get_data_db() as conn:
        row = conn.execute(
            """SELECT id as file_id, path, local_md5
               FROM files
               WHERE path=? OR (? IS NOT NULL AND local_md5=?)
               ORDER BY CASE WHEN path=? THEN 0 ELSE 1 END
               LIMIT 1""",
            (str(media_path), local_md5, local_md5, str(media_path)),
        ).fetchone()
    if row:
        return row
    return {"file_id": None, "path": str(media_path), "local_md5": local_md5}


def _identity_where(identity: dict[str, Any]) -> tuple[str, list[Any]]:
    return (
        "(file_path=? OR (? IS NOT NULL AND local_md5=?) OR (? IS NOT NULL AND file_id=?))",
        [
            identity.get("path"),
            identity.get("local_md5"),
            identity.get("local_md5"),
            identity.get("file_id"),
            identity.get("file_id"),
        ],
    )


def record_removed_tags_from_archive(archive_dir: Path) -> str:
    """Compare archived pre-refresh sidecars with current sidecars."""
    recorded = 0
    cleared = 0
    skipped = 0
    checked_at = datetime.now(timezone.utc).isoformat()

    with get_user_db() as uconn:
        for archived_path in archive_dir.rglob("*.danbooru.json") if archive_dir.exists() else []:
            try:
                old_payload = json.loads(archived_path.read_text(encoding="utf-8"))
                local_file = old_payload.get("local_file") or {}
                media_path = Path(local_file["path"])
                current_path = _current_sidecar_path(media_path)
                if current_path is None:
                    skipped += 1
                    continue
                new_payload = json.loads(current_path.read_text(encoding="utf-8"))
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                skipped += 1
                continue

            local_md5 = local_file.get("md5") or (new_payload.get("local_file") or {}).get("md5")
            identity = _identity_for(media_path, str(local_md5) if local_md5 else None)
            where_sql, params = _identity_where(identity)
            removed = sorted(_payload_tags(old_payload) - _payload_tags(new_payload))
            existing = uconn.execute(
                f"SELECT id FROM tag_removals WHERE {where_sql} ORDER BY checked_at DESC LIMIT 1",
                params,
            ).fetchone()

            if not removed:
                if existing:
                    uconn.execute("DELETE FROM tag_removals WHERE id=?", (existing["id"],))
                    cleared += 1
                continue

            values = (
                identity.get("file_id"),
                identity.get("path"),
                identity.get("local_md5"),
                json.dumps(removed, ensure_ascii=False),
                checked_at,
            )
            if existing:
                uconn.execute(
                    """UPDATE tag_removals
                       SET file_id=?, file_path=?, local_md5=?, removed_tags_json=?, checked_at=?
                       WHERE id=?""",
                    (*values, existing["id"]),
                )
            else:
                uconn.execute(
                    """INSERT INTO tag_removals
                       (file_id, file_path, local_md5, removed_tags_json, checked_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    values,
                )
            recorded += 1
        uconn.commit()

    return f"Tag history: {recorded} image(s) with removed upstream tags, {cleared} cleared, {skipped} skipped"


def removed_tags_for_file(conn, file_row: dict[str, Any]) -> list[str]:
    identity = {
        "file_id": file_row.get("file_id"),
        "path": file_row.get("path"),
        "local_md5": file_row.get("local_md5"),
    }
    where_sql, params = _identity_where(identity)
    row = conn.execute(
        f"SELECT removed_tags_json FROM tag_removals WHERE {where_sql} ORDER BY checked_at DESC LIMIT 1",
        params,
    ).fetchone()
    if not row:
        return []
    try:
        values = json.loads(row["removed_tags_json"])
    except (TypeError, json.JSONDecodeError):
        return []
    return sorted({str(value) for value in values if value}) if isinstance(values, list) else []
