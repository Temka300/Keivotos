from __future__ import annotations

from fastapi import APIRouter
from core import *  # shared query, database, and media helpers
from tag_history import removed_tags_for_file

router = APIRouter()


@router.get("/api/images", response_model=PaginatedImages)
def list_images(
    q: str = "",
    sort: str = "date",
    order: str = "desc",
    folder: str | None = None,
    rating: str | None = None,
    blacklist: str = "",
    duplicates_only: bool = False,
    duplicate_scope: str = "all",
    offset: int = Query(0, ge=0),
    limit: int = Query(60, ge=1, le=1000),
    favorites_only: bool = False,
    collection_id: int | None = None,
):
    search, exact_post_id, root_id = combined_image_search(q, folder, rating)

    inc, exc, filt = parse_search_terms(search.strip())
    if root_id:
        filt["root_id"] = root_id
    if blacklist and not exact_post_id:
        for tag in blacklist.split(","):
            tag = normalize_search_tag(tag)
            if tag:
                exc.append((None, tag))
    where_sql, params = build_where(inc, exc, filt)

    sort_col = {
        "score": "COALESCE(p.score, -999999)",
        "date": "COALESCE(p.created_at, '')",
        "downloaded": "COALESCE(f.downloaded_at, '')",
        "name": "f.name",
        "id": "p.id",
        "size": "COALESCE(f.size, 0)",
        "tags": "(SELECT COUNT(*) FROM post_tags pt_count WHERE pt_count.post_id = p.id)",
        "views": f"COALESCE((SELECT MAX(iv_sort.view_count) FROM userdb.image_views iv_sort WHERE {user_file_match('iv_sort')}), 0)",
        "hearts": f"COALESCE((SELECT MAX(iv_sort.heart_spam_count) FROM userdb.image_views iv_sort WHERE {user_file_match('iv_sort')}), 0)",
        "heart_spam": f"COALESCE((SELECT MAX(iv_sort.heart_spam_count) FROM userdb.image_views iv_sort WHERE {user_file_match('iv_sort')}), 0)",
        "random": "RANDOM()",
    }.get(sort, "COALESCE(p.score, -999999)")
    order_dir = "ASC" if order.lower() == "asc" else "DESC"

    favorite_join = ""
    collection_join = ""
    join_params: list[Any] = []
    attach_user_db = favorites_only or collection_id is not None or sort in ("views", "hearts", "heart_spam") or search_requires_user_db(inc, exc, filt)
    if favorites_only:
        where_sql = add_where_clause(
            where_sql,
            f"EXISTS (SELECT 1 FROM userdb.favorites fav WHERE {user_file_match('fav')})",
        )
    if collection_id is not None:
        collection_join = f"JOIN userdb.collection_items ci_filter ON ci_filter.collection_id = ? AND {user_file_match('ci_filter')}"
        join_params.append(collection_id)

    with get_data_db() as conn:
        if attach_user_db:
            conn.execute("ATTACH DATABASE ? AS userdb", (str(USER_DB_PATH),))

        conn.create_function("duplicate_key", 1, duplicate_filename_key)
        if duplicates_only:
            where_sql = add_where_clause(where_sql, duplicate_filter_sql(duplicate_scope))

        count_sql = f"SELECT COUNT(*) as cnt FROM posts p JOIN files f ON f.id=p.file_id {favorite_join} {collection_join} {where_sql}"
        total = conn.execute(count_sql, [*join_params, *params]).fetchone()["cnt"]
        if collection_id is not None and sort == "date":
            sort_col = "ci_filter.added_at"
        elif favorites_only and sort == "date":
            sort_col = f"(SELECT MAX(fav_sort.added_at) FROM userdb.favorites fav_sort WHERE {user_file_match('fav_sort')})"
        pin_order = ""
        if favorites_only:
            favorite_pin = f"(SELECT MAX(fav_pin.pinned_at) FROM userdb.favorites fav_pin WHERE {user_file_match('fav_pin')})"
            pin_order = f"CASE WHEN {favorite_pin} IS NULL THEN 1 ELSE 0 END, {favorite_pin} DESC, "
        elif collection_id is not None:
            pin_order = "CASE WHEN ci_filter.pinned_at IS NULL THEN 1 ELSE 0 END, ci_filter.pinned_at DESC, "
        if sort == "random":
            order_sql = f"{pin_order}RANDOM()"
        else:
            order_sql = (
                f"{pin_order}{duplicate_group_expr('f')} ASC, {sort_col} {order_dir}, f.folder ASC, f.name ASC"
                if duplicates_only
                else f"{pin_order}{sort_col} {order_dir}, f.name ASC"
            )
        favorite_select = "NULL as favorite_added_at, NULL as favorite_pinned_at"
        collection_added_select = (
            "ci_filter.added_at as collection_added_at, ci_filter.pinned_at as collection_pinned_at"
            if collection_id is not None
            else "NULL as collection_added_at, NULL as collection_pinned_at"
        )

        query = f"""
            SELECT p.id, f.id as file_id, f.path, f.local_md5, f.downloaded_at,
                   f.name as filename, f.folder, f.ext,
                   p.created_at, p.width, p.height, p.score, p.rating, p.danbooru_post_id,
                   {favorite_select},
                   {collection_added_select}
            FROM posts p
            JOIN files f ON f.id = p.file_id
            {favorite_join}
            {collection_join}
            {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, [*join_params, *params, limit, offset]).fetchall()

    fav_meta_by_file = favorite_meta_by_file(row["file_id"] for row in rows)
    fav_file_ids = set(fav_meta_by_file)
    images = []
    for row in rows:
        images.append(image_summary_from_row(row, fav_file_ids, fav_meta_by_file))
    return PaginatedImages(images=images, total=total, offset=offset, limit=limit)


@router.get("/api/timelapse/frames", response_model=TimelapseFrames)
def timelapse_frames(
    q: str = "",
    folder: str | None = None,
    rating: str | None = None,
    blacklist: str = "",
    duplicates_only: bool = False,
    duplicate_scope: str = "all",
    frame_count: int = Query(240, ge=12, le=1000),
    favorites_only: bool = False,
    collection_id: int | None = None,
):
    search, exact_post_id, root_id = combined_image_search(q, folder, rating)

    inc, exc, filt = parse_search_terms(search.strip())
    if root_id:
        filt["root_id"] = root_id
    if blacklist and not exact_post_id:
        for tag in blacklist.split(","):
            tag = normalize_search_tag(tag)
            if tag:
                exc.append((None, tag))
    where_sql, params = build_where(inc, exc, filt)
    where_sql = add_where_clause(where_sql, "p.created_at IS NOT NULL AND p.created_at <> ''")

    favorite_join = ""
    collection_join = ""
    join_params: list[Any] = []
    attach_user_db = favorites_only or collection_id is not None or search_requires_user_db(inc, exc, filt)
    if favorites_only:
        where_sql = add_where_clause(
            where_sql,
            f"EXISTS (SELECT 1 FROM userdb.favorites fav WHERE {user_file_match('fav')})",
        )
    if collection_id is not None:
        collection_join = f"JOIN userdb.collection_items ci_filter ON ci_filter.collection_id = ? AND {user_file_match('ci_filter')}"
        join_params.append(collection_id)

    with get_data_db() as conn:
        if attach_user_db:
            conn.execute("ATTACH DATABASE ? AS userdb", (str(USER_DB_PATH),))

        conn.create_function("duplicate_key", 1, duplicate_filename_key)
        if duplicates_only:
            where_sql = add_where_clause(where_sql, duplicate_filter_sql(duplicate_scope))

        collection_added_select = (
            "ci_filter.added_at as collection_added_at, ci_filter.pinned_at as collection_pinned_at"
            if collection_id is not None
            else "NULL as collection_added_at, NULL as collection_pinned_at"
        )
        summary = conn.execute(
            f"""
            SELECT COUNT(*) as total,
                   MIN(p.created_at) as start_date,
                   MAX(p.created_at) as end_date
            FROM posts p
            JOIN files f ON f.id = p.file_id
            {favorite_join}
            {collection_join}
            {where_sql}
            """,
            [*join_params, *params],
        ).fetchone()

        total = int(summary["total"] or 0)
        if total == 0:
            return TimelapseFrames(images=[], total=0, sampled=0)

        if total <= frame_count:
            sample_indexes = list(range(1, total + 1))
        else:
            sample_indexes = sorted(
                {1 + round(index * (total - 1) / (frame_count - 1)) for index in range(frame_count)}
            )
        sample_placeholders = ",".join("?" for _ in sample_indexes)
        rows = conn.execute(
            f"""
            WITH ranked AS (
                SELECT p.id, f.id as file_id, f.path, f.local_md5, f.downloaded_at,
                       f.name as filename, f.folder, f.ext,
                       p.created_at, p.width, p.height, p.score, p.rating, p.danbooru_post_id,
                       NULL as favorite_added_at, NULL as favorite_pinned_at,
                       {collection_added_select},
                       ROW_NUMBER() OVER (
                           ORDER BY date(p.created_at) ASC, p.created_at ASC, f.name ASC
                       ) as sample_index
                FROM posts p
                JOIN files f ON f.id = p.file_id
                {favorite_join}
                {collection_join}
                {where_sql}
            )
            SELECT * FROM ranked
            WHERE sample_index IN ({sample_placeholders})
            ORDER BY sample_index
            """,
            [*join_params, *params, *sample_indexes],
        ).fetchall()

    fav_meta_by_file = favorite_meta_by_file(row["file_id"] for row in rows)
    fav_file_ids = set(fav_meta_by_file)
    images = [image_summary_from_row(row, fav_file_ids, fav_meta_by_file) for row in rows]
    return TimelapseFrames(
        images=images,
        total=total,
        sampled=len(images),
        start_date=summary["start_date"],
        end_date=summary["end_date"],
    )


@router.get("/api/images/random")
def random_image(
    q: str = "",
    folder: str | None = None,
    rating: str | None = None,
    blacklist: str = "",
    duplicates_only: bool = False,
    duplicate_scope: str = "all",
    favorites_only: bool = False,
    collection_id: int | None = None,
    collections_only: bool = False,
):
    search, exact_post_id, root_id = combined_image_search(q, folder, rating)

    inc, exc, filt = parse_search_terms(search.strip())
    if root_id:
        filt["root_id"] = root_id
    if blacklist and not exact_post_id:
        for tag in blacklist.split(","):
            tag = normalize_search_tag(tag)
            if tag:
                exc.append((None, tag))
    where_sql, params = build_where(inc, exc, filt)

    favorite_join = ""
    collection_join = ""
    join_params: list[Any] = []
    attach_user_db = favorites_only or collection_id is not None or collections_only or search_requires_user_db(inc, exc, filt)

    if favorites_only:
        where_sql = add_where_clause(
            where_sql,
            f"EXISTS (SELECT 1 FROM userdb.favorites fav WHERE {user_file_match('fav')})",
        )
    if collection_id is not None:
        collection_join = f"JOIN userdb.collection_items ci_filter ON ci_filter.collection_id = ? AND {user_file_match('ci_filter')}"
        join_params.append(collection_id)

    with get_data_db() as conn:
        if attach_user_db:
            conn.execute("ATTACH DATABASE ? AS userdb", (str(USER_DB_PATH),))

        conn.create_function("duplicate_key", 1, duplicate_filename_key)
        if duplicates_only:
            where_sql = add_where_clause(where_sql, duplicate_filter_sql(duplicate_scope))
        if collections_only:
            where_sql = add_where_clause(
                where_sql,
                f"EXISTS (SELECT 1 FROM userdb.collection_items ci_any WHERE {user_file_match('ci_any')})",
            )

        row = conn.execute(
            f"""
            SELECT p.id
            FROM posts p
            JOIN files f ON f.id = p.file_id
            {favorite_join}
            {collection_join}
            {where_sql}
            ORDER BY RANDOM()
            LIMIT 1
            """,
            [*join_params, *params],
        ).fetchone()

    if not row:
        raise HTTPException(404, "No matching image")
    return {"id": row["id"]}


def batch_error_detail(exc: Exception) -> str | dict:
    if isinstance(exc, HTTPException):
        return exc.detail
    return str(exc)


@router.put("/api/images/batch/folder")
def move_images_batch(data: ImageBatchMove):
    moved_post_ids: list[int] = []
    errors: dict[str, str | dict] = {}
    for post_id in dict.fromkeys(data.post_ids):
        try:
            move_image_folder(post_id, ImageMoveFolder(folder=data.folder))
            moved_post_ids.append(post_id)
        except Exception as exc:  # noqa: BLE001 - return per-image failures to the bulk UI.
            errors[str(post_id)] = batch_error_detail(exc)
    return {"status": "completed", "moved_post_ids": moved_post_ids, "errors": errors}


@router.get("/api/images/{post_id}", response_model=ImageDetail)
def get_image(post_id: int, record_view: bool = True):
    with get_data_db() as conn:
        row = conn.execute(
            """SELECT p.id, f.id as file_id, f.name as filename, f.folder, f.ext,
                      f.path, f.size, f.local_md5, f.downloaded_at,
                      p.width, p.height, p.score, p.rating, p.danbooru_post_id,
                      p.post_url, p.source_url, p.created_at, p.updated_at,
                      p.parent_id, p.has_children, p.child_ids_json, p.raw_json
               FROM posts p JOIN files f ON f.id=p.file_id
               WHERE p.id=?""",
            (post_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Image not found")

        tag_rows = conn.execute(
            """SELECT t.name, t.category FROM post_tags pt
               JOIN tags t ON t.id=pt.tag_id WHERE pt.post_id=?
               ORDER BY t.category, t.name""",
            (post_id,),
        ).fetchall()
        relations = build_image_relations(conn, row)

    tags: dict[str, list[str]] = {}
    for tr in tag_rows:
        tags.setdefault(tr["category"], []).append(tr["name"])

    is_fav = False
    favorite_added_at: str | None = None
    favorite_pinned_at: str | None = None
    collections: list[CollectionInfo] = []
    user_tags: dict[str, list[str]] = {}
    view_row: dict[str, Any] | None = None
    removed_tags: list[str] = []
    with get_user_db() as uconn:
        fav_row = uconn.execute(
            f"SELECT added_at, pinned_at FROM favorites WHERE {user_file_lookup_sql()} ORDER BY added_at DESC LIMIT 1",
            user_file_lookup_params(row),
        ).fetchone()
        is_fav = fav_row is not None
        favorite_added_at = fav_row["added_at"] if fav_row else None
        favorite_pinned_at = fav_row["pinned_at"] if fav_row else None

        col_rows = uconn.execute(
            """SELECT c.id, c.name, c.description, c.created_at, c.pinned_at,
                      ci.added_at as item_added_at, ci.pinned_at as item_pinned_at
               FROM collections c
               JOIN collection_items ci ON ci.collection_id=c.id
               WHERE {lookup}""".format(lookup=user_file_lookup_sql("ci")),
            user_file_lookup_params(row),
        ).fetchall()
        collections = [CollectionInfo(**cr, image_count=0) for cr in col_rows]
        user_tags = user_image_tags_for_file(uconn, row)
        removed_tags = removed_tags_for_file(uconn, row)
        view_row = record_image_view(uconn, row) if record_view else image_view_for_file(uconn, row)

    return ImageDetail(
        **row,
        thumbnail_token=row["local_md5"] or thumbnail_cache_token(row["path"]),
        tags=tags,
        removed_tags=removed_tags,
        user_tags=user_tags,
        is_favorite=is_fav,
        favorite_added_at=favorite_added_at,
        favorite_pinned_at=favorite_pinned_at,
        view_count=int(view_row["view_count"] or 0) if view_row else 0,
        heart_spam_count=int(view_row["heart_spam_count"] or 0) if view_row else 0,
        first_viewed_at=view_row["first_viewed_at"] if view_row else None,
        last_viewed_at=view_row["last_viewed_at"] if view_row else None,
        collections=collections,
        relations=relations,
    )


@router.post("/api/images/{post_id}/heart-spam")
def heart_spam_image(post_id: int):
    file_row = get_post_file_identity(post_id)
    with get_user_db() as conn:
        view_row = record_heart_spam(conn, file_row)
    return {"heart_spam_count": int(view_row["heart_spam_count"] or 0) if view_row else 0}


@router.post("/api/images/{post_id}/relations/refresh", response_model=ImageDetail)
def refresh_image_relations(post_id: int):
    with get_data_db() as conn:
        row = conn.execute(
            "SELECT danbooru_post_id FROM posts WHERE id=?",
            (post_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Image not found")
        danbooru_post_id = int_or_none(row.get("danbooru_post_id"))
        if danbooru_post_id is None:
            raise HTTPException(400, "Image has no Danbooru post id")
        refresh_relation_cache(conn, danbooru_post_id)
        conn.commit()
    return get_image(post_id, record_view=False)


@router.post("/api/images/{post_id}/user-tags")
def add_user_image_tag(post_id: int, data: UserImageTagCreate):
    file_row = get_post_file_identity(post_id)
    tag_name = normalize_user_tag(data.name)
    tag_category = normalize_user_tag_category(data.category)
    if not tag_name:
        raise HTTPException(400, "Tag name is required")

    with get_user_db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO user_image_tags
               (file_id, file_path, local_md5, tag_category, tag_name)
               VALUES (?, ?, ?, ?, ?)""",
            (file_row["file_id"], file_row["path"], file_row["local_md5"], tag_category, tag_name),
        )
        conn.commit()
        return {"tags": user_image_tags_for_file(conn, file_row)}


@router.delete("/api/images/{post_id}/user-tags/{tag_name:path}")
def remove_user_image_tag(post_id: int, tag_name: str, category: str | None = None):
    file_row = get_post_file_identity(post_id)
    normalized = normalize_user_tag(tag_name)
    if not normalized:
        raise HTTPException(400, "Tag name is required")

    with get_user_db() as conn:
        params: list[Any] = [normalized]
        category_sql = ""
        if category:
            category_sql = "AND tag_category=?"
            params.append(normalize_user_tag_category(category))
        conn.execute(
            f"""DELETE FROM user_image_tags
                WHERE tag_name=? {category_sql} AND {user_file_lookup_sql()}""",
            [*params, *user_file_lookup_params(file_row)],
        )
        conn.commit()
        return {"tags": user_image_tags_for_file(conn, file_row)}


@router.post("/api/images/{post_id}/open-location")
def open_image_location(post_id: int):
    file_row = get_post_file_identity(post_id)
    image_path = Path(file_row["path"])
    resolved_path = image_path.resolve(strict=False)
    ensure_managed_path(resolved_path, "open")

    if not resolved_path.exists():
        raise HTTPException(404, "File not found on disk")

    try:
        import subprocess

        if sys.platform == "win32":
            subprocess.Popen(["explorer.exe", "/select,", str(resolved_path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(resolved_path)])
        else:
            subprocess.Popen(["xdg-open", str(resolved_path.parent)])
    except OSError as exc:
        raise HTTPException(500, f"Failed to open image location: {exc}") from exc

    return {"status": "opened", "path": str(resolved_path)}


@router.put("/api/images/{post_id}/folder", response_model=ImageDetail)
def move_image_folder(post_id: int, data: ImageMoveFolder):
    with get_data_db() as conn:
        row = conn.execute(
            """SELECT p.id, p.raw_json, f.id as file_id, f.path, f.name, f.local_md5
               FROM posts p JOIN files f ON f.id=p.file_id
               WHERE p.id=?""",
            (post_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Image not found")

    source_path = Path(row["path"])
    if not source_path.exists():
        raise HTTPException(404, "File not found on disk")

    ensure_managed_path(source_path, "move")

    target_dir, target_folder = folder_target(data.folder)
    target_path = target_dir / source_path.name
    if source_path.resolve(strict=False) == target_path.resolve(strict=False):
        return get_image(post_id, record_view=False)

    paths_to_move: list[tuple[Path, Path]] = [(source_path, target_path)]
    for suffix in SIDECAR_SUFFIXES:
        for sidecar_path in sidecar_candidates(source_path, suffix):
            if sidecar_path.exists():
                paths_to_move.append((sidecar_path, central_sidecar_path(target_path, suffix)))
                break

    for _, destination in paths_to_move:
        if destination.exists():
            raise HTTPException(409, f"Target file already exists: {destination.name}")

    with get_data_db() as conn:
        existing = conn.execute(
            "SELECT id FROM files WHERE path=? AND id<>?",
            (str(target_path), row["file_id"]),
        ).fetchone()
        if existing:
            raise HTTPException(409, "Target file is already indexed")

    for _, destination in paths_to_move:
        destination.parent.mkdir(parents=True, exist_ok=True)
    moved_paths: list[tuple[Path, Path]] = []
    old_path_text = str(source_path)

    try:
        for source, destination in paths_to_move:
            shutil.move(str(source), str(destination))
            moved_paths.append((source, destination))

        raw_json = rewrite_json_sidecar(
            central_sidecar_path(target_path, ".danbooru.json"),
            target_path,
        ) or move_payload_text(row.get("raw_json"), target_path)

        with get_data_db() as conn:
            target_root_id, target_relative_path = identity_for_media(
                target_path,
                DATA_ROOT,
                library_roots(),
            )
            conn.execute(
                """UPDATE files
                   SET path=?, folder=?, name=?, ext=?, size=?, root_id=?, relative_path=?
                   WHERE id=?""",
                (
                    str(target_path),
                    target_folder,
                    target_path.name,
                    target_path.suffix.lower().lstrip("."),
                    target_path.stat().st_size,
                    target_root_id,
                    str(target_relative_path),
                    row["file_id"],
                ),
            )
            if raw_json is not None:
                conn.execute("UPDATE posts SET raw_json=? WHERE id=?", (raw_json, post_id))
            conn.commit()
    except Exception as exc:
        for source, destination in reversed(moved_paths):
            try:
                if destination.exists() and not source.exists():
                    shutil.move(str(destination), str(source))
            except OSError:
                pass
        raise HTTPException(500, f"Failed to move image: {exc}")

    with get_user_db() as uconn:
        uconn.execute(
            "UPDATE favorites SET file_path=?, local_md5=COALESCE(local_md5, ?) WHERE file_id=? OR file_path=?",
            (str(target_path), row["local_md5"], row["file_id"], old_path_text),
        )
        uconn.execute(
            "UPDATE collection_items SET file_path=?, local_md5=COALESCE(local_md5, ?) WHERE file_id=? OR file_path=?",
            (str(target_path), row["local_md5"], row["file_id"], old_path_text),
        )
        uconn.execute(
            "UPDATE user_image_tags SET file_path=?, local_md5=COALESCE(local_md5, ?) WHERE file_id=? OR file_path=?",
            (str(target_path), row["local_md5"], row["file_id"], old_path_text),
        )
        uconn.execute(
            "UPDATE image_views SET file_path=?, local_md5=COALESCE(local_md5, ?) WHERE file_id=? OR file_path=?",
            (str(target_path), row["local_md5"], row["file_id"], old_path_text),
        )
        uconn.execute(
            "UPDATE tag_removals SET file_path=?, local_md5=COALESCE(local_md5, ?) WHERE file_id=? OR file_path=? OR local_md5=?",
            (str(target_path), row["local_md5"], row["file_id"], old_path_text, row["local_md5"]),
        )
        uconn.commit()

    return get_image(post_id, record_view=False)


@router.get("/api/image-file/{file_id}")
def serve_image(file_id: int, request: Request):
    with get_data_db() as conn:
        row = conn.execute("SELECT path, local_md5 FROM files WHERE id=?", (file_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    p = Path(row["path"])
    if not p.exists():
        raise HTTPException(404, "File not found on disk")
    media = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".jfif": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
        ".mp4": "video/mp4", ".webm": "video/webm",
    }.get(p.suffix.lower(), "application/octet-stream")

    file_size = p.stat().st_size
    range_header = request.headers.get("range")
    byte_range = parse_range_header(range_header, file_size)
    if range_header and byte_range is None:
        return Response(
            status_code=416,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes */{file_size}",
            },
        )

    if byte_range is not None:
        start, end = byte_range
        content_length = end - start + 1
        return StreamingResponse(
            file_range_iter(p, start, end),
            status_code=206,
            media_type=media,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
                "Content-Range": f"bytes {start}-{end}/{file_size}",
            },
        )

    return FileResponse(p, media_type=media, headers={"Accept-Ranges": "bytes"})


@router.get("/api/thumbnail/{file_id}")
def serve_thumbnail(
    file_id: int,
    size: int = Query(DEFAULT_THUMB_SIZE, ge=DEFAULT_THUMB_SIZE, le=1200),
):
    with get_data_db() as conn:
        row = conn.execute("SELECT path, local_md5 FROM files WHERE id=?", (file_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    thumb = ensure_thumbnail(row["path"], size, row["local_md5"])
    if thumb and thumb.exists():
        return FileResponse(
            thumb,
            media_type="image/webp",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
    p = Path(row["path"])
    if p.exists():
        return media_placeholder(p.suffix)
    raise HTTPException(404)
