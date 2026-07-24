"""Archiving Twitter/X and Pixiv profile artwork for followed artists.

Moved verbatim from ``core.py``. Downloading is always explicit and
user-triggered: it resolves a profile URL already cached from the tag wiki,
fetches through gallery-dl or Pixiv's endpoint, validates the bytes are a real
image from an allowlisted host, and stores deduplicated versions under the
configured archive directory. Nothing here hotlinks remote media.

No ``core`` import.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from config import ARTIST_PROFILE_ARCHIVE_DIR, CODE_ROOT
from database import get_user_db
from models import ArtistProfileArchiveResult, ArtistProfileAsset
from modules.danbooru.client import USER_AGENT
from services.tag_names import normalize_search_tag


ARTIST_PROFILE_MAX_BYTES = 16 * 1024 * 1024
ARTIST_PROFILE_ALLOWED_IMAGE_HOSTS = {"pbs.twimg.com", "i.pximg.net"}
TWITTER_RESERVED_PATHS = {"home", "i", "intent", "search", "share", "explore", "notifications", "messages"}


def artist_profile_asset_from_row(row: dict[str, Any]) -> ArtistProfileAsset:
    return ArtistProfileAsset(
        id=int(row["id"]),
        tag_name=row["tag_name"],
        platform=row["platform"],
        asset_kind=row["asset_kind"],
        source_profile_url=row["source_profile_url"],
        source_url=row["source_url"],
        file_url=f"/api/artist-profile-asset-files/{row['id']}",
        width=int(row["width"]),
        height=int(row["height"]),
        captured_at=row["captured_at"],
    )


def list_artist_profile_assets_from_conn(conn, tag_name: str) -> list[ArtistProfileAsset]:
    rows = conn.execute(
        """SELECT *
             FROM artist_profile_assets
            WHERE tag_name=?
            ORDER BY captured_at DESC, id DESC""",
        (tag_name,),
    ).fetchall()
    return [artist_profile_asset_from_row(row) for row in rows]


def cached_artist_profile_urls(tag_name: str) -> list[dict[str, Any]]:
    with get_user_db() as conn:
        row = conn.execute(
            "SELECT artist_urls_json FROM tag_wiki_cache WHERE tag_name=?",
            (tag_name,),
        ).fetchone()
    if not row:
        return []
    try:
        values = json.loads(row.get("artist_urls_json") or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(values, list):
        return []
    return sorted(
        [item for item in values if isinstance(item, dict) and str(item.get("url") or "").strip()],
        key=lambda item: not bool(item.get("is_active", True)),
    )


def artist_profile_sources(tag_name: str) -> dict[str, tuple[str, str]]:
    sources: dict[str, tuple[str, str]] = {}
    for item in cached_artist_profile_urls(tag_name):
        url = str(item.get("url") or "").strip()
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.casefold().removeprefix("www.").removeprefix("mobile.")
        parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]

        if host in {"x.com", "twitter.com"} and parts:
            handle = parts[0].lstrip("@").strip()
            if handle and handle.casefold() not in TWITTER_RESERVED_PATHS:
                sources.setdefault("twitter", (url, handle))
            continue

        if host in {"pixiv.net", "pixivision.net"}:
            user_id = ""
            if "users" in parts:
                index = parts.index("users")
                if index + 1 < len(parts):
                    user_id = parts[index + 1]
            if not user_id and parsed.path.rstrip("/").endswith("member.php"):
                user_id = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
            if user_id.isdigit():
                sources.setdefault("pixiv", (url, user_id))
    return sources


def gallery_dl_command() -> list[str] | None:
    executable_name = "gallery-dl.exe" if sys.platform == "win32" else "gallery-dl"
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).resolve(strict=False).parent / executable_name
        return [str(bundled)] if bundled.is_file() else None

    executable = shutil.which("gallery-dl")
    if executable:
        return [executable]
    venv_scripts = "Scripts" if sys.platform == "win32" else "bin"
    candidates = (
        Path(sys.executable).resolve(strict=False).parent / executable_name,
        # Was `__file__`-relative in core.py, which silently depended on this
        # code living exactly one directory below the code root. Use the
        # authoritative resource root instead so the depth no longer matters.
        CODE_ROOT / ".venv" / venv_scripts / executable_name,
    )
    for bundled in candidates:
        if bundled.is_file():
            return [str(bundled)]
    return None


def twitter_profile_media_from_messages(messages: Any) -> dict[str, str]:
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, list) or len(message) < 2:
            continue
        metadata = message[1] if isinstance(message[1], dict) else (message[2] if len(message) > 2 and isinstance(message[2], dict) else None)
        if not isinstance(metadata, dict):
            continue
        candidates = [metadata, metadata.get("user"), metadata.get("author")]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            avatar = str(candidate.get("profile_image") or "").strip()
            banner = str(candidate.get("profile_banner") or "").strip()
            if banner and "/profile_banners/" in banner and not re.search(r"/\d+x\d+$", banner):
                banner = f"{banner.rstrip('/')}/1500x500"
            media = {"avatar": avatar, "banner": banner}
            resolved = {kind: url for kind, url in media.items() if url}
            if resolved:
                return resolved
    return {}


def gallery_dl_twitter_profile_media(handle: str) -> dict[str, str]:
    command = gallery_dl_command()
    if not command:
        raise RuntimeError("gallery-dl is required for Twitter profile media")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            [*command, "-j", f"https://x.com/{handle}/info"],
            capture_output=True,
            text=True,
            timeout=35,
            creationflags=creationflags,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Twitter profile request failed: {exc}") from exc
    if not result.stdout.strip():
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "no profile data returned"
        raise RuntimeError(f"Twitter profile request failed: {detail}")
    try:
        messages = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Twitter profile response was not valid JSON") from exc

    media = twitter_profile_media_from_messages(messages)
    if media:
        return media
    raise RuntimeError("Twitter profile media was not available")


def pixiv_profile_media(user_id: str) -> dict[str, str]:
    request = urllib.request.Request(
        f"https://www.pixiv.net/ajax/user/{user_id}?full=1&lang=en",
        headers={
            "User-Agent": f"Mozilla/5.0 {USER_AGENT}",
            "Referer": "https://www.pixiv.net/",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Pixiv profile request failed: {exc}") from exc
    body = payload.get("body") if isinstance(payload, dict) else None
    if not isinstance(body, dict) or payload.get("error"):
        raise RuntimeError("Pixiv profile media was not available")
    background = body.get("background") if isinstance(body.get("background"), dict) else {}
    media = {
        "avatar": str(body.get("imageBig") or body.get("image") or "").strip(),
        "banner": str(background.get("url") or "").strip(),
    }
    return {kind: url for kind, url in media.items() if url}


def download_artist_profile_image(url: str, platform: str) -> tuple[bytes, str, int, int]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.casefold() not in ARTIST_PROFILE_ALLOWED_IMAGE_HOSTS:
        raise RuntimeError("Profile media resolved to an unsupported image host")
    headers = {"User-Agent": f"Mozilla/5.0 {USER_AGENT}"}
    if platform == "pixiv":
        headers["Referer"] = "https://www.pixiv.net/"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            final_host = urllib.parse.urlparse(response.geturl()).netloc.casefold()
            if final_host not in ARTIST_PROFILE_ALLOWED_IMAGE_HOSTS:
                raise RuntimeError("Profile media redirected to an unsupported image host")
            data = response.read(ARTIST_PROFILE_MAX_BYTES + 1)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise RuntimeError(f"Profile image download failed: {exc}") from exc
    if not data or len(data) > ARTIST_PROFILE_MAX_BYTES:
        raise RuntimeError("Profile image was empty or too large")
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image_format = (image.format or "").upper()
            image.verify()
    except Exception as exc:
        raise RuntimeError("Downloaded profile media was not a valid image") from exc
    extension = {
        "JPEG": "jpg",
        "PNG": "png",
        "WEBP": "webp",
        "GIF": "gif",
    }.get(image_format)
    if not extension:
        raise RuntimeError(f"Unsupported profile image format: {image_format or 'unknown'}")
    return data, extension, int(width), int(height)


def archive_artist_profile_asset(
    tag_name: str,
    platform: str,
    asset_kind: str,
    source_profile_url: str,
    source_url: str,
) -> bool:
    with get_user_db() as conn:
        latest = conn.execute(
            """SELECT source_url, file_path
                 FROM artist_profile_assets
                WHERE tag_name=? AND platform=? AND asset_kind=?
                ORDER BY captured_at DESC, id DESC
                LIMIT 1""",
            (tag_name, platform, asset_kind),
        ).fetchone()
    if latest and latest["source_url"] == source_url and Path(latest["file_path"]).exists():
        return False

    data, extension, width, height = download_artist_profile_image(source_url, platform)
    content_hash = hashlib.sha256(data).hexdigest()
    with get_user_db() as conn:
        duplicate = conn.execute(
            """SELECT id FROM artist_profile_assets
                WHERE tag_name=? AND platform=? AND asset_kind=? AND content_hash=?""",
            (tag_name, platform, asset_kind, content_hash),
        ).fetchone()
        if duplicate:
            return False

    safe_tag = re.sub(r"[^a-zA-Z0-9._-]+", "_", tag_name).strip("._") or "artist"
    tag_hash = hashlib.sha256(tag_name.encode("utf-8")).hexdigest()[:8]
    target_dir = ARTIST_PROFILE_ARCHIVE_DIR / f"{safe_tag}_{tag_hash}" / platform / asset_kind
    target_dir.mkdir(parents=True, exist_ok=True)
    captured = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = target_dir / f"{captured}_{content_hash[:12]}.{extension}"
    target.write_bytes(data)

    with get_user_db() as conn:
        conn.execute(
            """INSERT INTO artist_profile_assets (
                   tag_name, platform, asset_kind, source_profile_url, source_url,
                   file_path, content_hash, width, height
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tag_name,
                platform,
                asset_kind,
                source_profile_url,
                source_url,
                str(target),
                content_hash,
                width,
                height,
            ),
        )
        conn.commit()
    return True


def archive_artist_profile_media(tag_name: str) -> ArtistProfileArchiveResult:
    name = normalize_search_tag(tag_name)
    sources = artist_profile_sources(name)
    saved_count = 0
    unchanged_count = 0
    notices: list[str] = []
    errors: list[str] = []
    if not sources:
        errors.append("No cached Twitter/X or Pixiv profile URL was found")

    for platform, (profile_url, identity) in sources.items():
        try:
            media = gallery_dl_twitter_profile_media(identity) if platform == "twitter" else pixiv_profile_media(identity)
            if not media:
                errors.append(f"{platform.title()} returned no avatar or banner")
                continue
            platform_label = "Twitter/X" if platform == "twitter" else "Pixiv"
            for missing_kind in ("avatar", "banner"):
                if missing_kind not in media:
                    notices.append(f"{platform_label} does not publish a {missing_kind} for this profile.")
            for asset_kind, source_url in media.items():
                if archive_artist_profile_asset(name, platform, asset_kind, profile_url, source_url):
                    saved_count += 1
                else:
                    unchanged_count += 1
        except RuntimeError as exc:
            errors.append(f"{platform.title()}: {exc}")

    with get_user_db() as conn:
        assets = list_artist_profile_assets_from_conn(conn, name)
    return ArtistProfileArchiveResult(
        assets=assets,
        saved_count=saved_count,
        unchanged_count=unchanged_count,
        notices=notices,
        errors=errors,
    )
