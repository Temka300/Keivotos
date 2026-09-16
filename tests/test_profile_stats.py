"""Protect local profile artwork/statistics and independent suite settings."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import database
from fastapi import HTTPException
from models import UserSettingUpdate
from routers import stats
from routers import user_settings as settings
from modules.danbooru import profile


class ProfileStatsTests(unittest.TestCase):
    def test_router_ownership_and_helper_identity(self):
        from fastapi import FastAPI
        from modules.danbooru import descriptor

        module_routes = [route for router in descriptor(self.home, "test").routers()
                         for route in router.routes]
        self.assertEqual(sum(route.path == "/api/stats" for route in module_routes), 1)
        self.assertFalse(any(route.path.startswith("/api/user-settings") for route in module_routes))
        shell = FastAPI()
        shell.include_router(settings.router)
        paths = shell.openapi()["paths"]
        self.assertEqual(set(paths), {"/api/user-settings/{key}"})
        self.assertEqual(set(paths["/api/user-settings/{key}"]), {"get", "put"})
        self.assertIs(stats.profile_asset, profile.profile_asset)
        self.assertIs(stats.profile_asset_token, profile.profile_asset_token)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="keivotos-profile-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.data = self.home / "modules" / "danbooru" / "danbooru.sqlite"
        self.user = self.home / "user.sqlite"
        for owner, name, value in ((database, "DATA_DB_PATH", self.data),
                                   (database, "USER_DB_PATH", self.user),
                                   (stats, "USER_DB_PATH", self.user)):
            override = patch.object(owner, name, value)
            override.start()
            self.addCleanup(override.stop)
        database.init_data_db()
        database.init_user_db()
        with database.get_data_db() as conn:
            for ident, folder, ext, width, height, score in (
                (1, "C-LOGO", "jpg", 800, 800, 10),
                (2, "c-Logo", "png", 1800, 600, 100),
                (3, "Wallpaper", "gif", 1600, 800, 20),
                (4, "c-Logo", "mp4", 800, 800, 999),
            ):
                conn.execute("INSERT INTO files(id,path,name,folder,ext,size,local_md5,downloaded_at) "
                             "VALUES(?,?,?,?,?,?,?,?)",
                             (ident, f"/fixture/{ident}.{ext}", f"{ident}.{ext}", folder,
                              ext, 100, f"hash-{ident}", f"2026-01-0{ident}"))
                conn.execute("INSERT INTO posts(id,file_id,width,height,score,rating) VALUES(?,?,?,?,?,'g')",
                             (ident, ident, width, height, score))
            conn.execute("INSERT INTO tags(id,name,category) VALUES(1,'alice','character')")
            conn.commit()
        with database.get_user_db() as conn:
            conn.execute("INSERT INTO favorites(file_id,local_md5) VALUES(101,'hash-1')")
            conn.execute("INSERT INTO collections(id,name) VALUES(1,'Collection')")
            conn.execute("INSERT INTO collection_items(collection_id,file_id,file_path) VALUES(1,102,'/fixture/2.png')")
            conn.execute("INSERT INTO image_views(file_id,local_md5,view_count,first_viewed_at,last_viewed_at) "
                         "VALUES(103,'hash-3',5,'2026-02-01','2026-03-01')")
            conn.execute("INSERT INTO favorite_tags(tag_name,tag_category) VALUES('alice','character')")
            conn.execute("INSERT INTO user_image_tags(file_id,file_path,tag_name) VALUES(1,'/fixture/1.jpg','mine')")
            conn.execute("INSERT INTO artist_follows(tag_name) VALUES('artist')")
            conn.commit()

    def test_stats_counts_dates_and_durable_identity(self):
        self.assertEqual(stats.stats().model_dump(), {
            "total_images": 4, "total_tags": 1, "total_folders": 3,
            "total_favorites": 1, "total_collections": 1, "total_image_views": 5,
            "seen_images": 1, "total_storage_bytes": 400, "total_user_tags": 1,
            "total_favorite_tags": 1, "total_followed_artists": 1, "total_collection_items": 1,
            "average_score": 282.25, "best_score": 999,
            "downloaded_from": "2026-01-01", "downloaded_to": "2026-01-04",
            "first_viewed_at": "2026-02-01", "last_viewed_at": "2026-03-01",
            "profile_avatar_file_id": 1, "profile_avatar_token": "hash-1",
            "profile_banner_file_id": 3, "profile_banner_token": "hash-3",
        })

    def test_artwork_ratio_fallback_excludes_video_and_handles_missing(self):
        with database.get_data_db() as conn:
            picked = profile.profile_asset(conn, ["c-logo"], "p.width=p.height")
            self.assertEqual(picked["file_id"], 1)
            fallback = profile.profile_asset(conn, ["c-logo"], "p.width=0")
            self.assertEqual(fallback["file_id"], 2)
            self.assertIsNone(profile.profile_asset(conn, ["absent"], "p.width=p.height"))
        self.assertIsNone(profile.profile_asset_token(None))
        with patch.object(profile, "thumbnail_cache_token", return_value="fallback") as token:
            self.assertEqual(profile.profile_asset_token({"local_md5": None, "path": "/fixture/x.jpg"}), "fallback")
        token.assert_called_once_with("/fixture/x.jpg")

    def test_settings_use_only_user_database_and_preserve_normalization(self):
        # Fail if a setting starts consulting the module's data connection.
        with patch.object(stats, "get_data_db", side_effect=AssertionError("Danbooru DB accessed")):
            self.assertEqual(settings.get_user_setting("profile_name").value, "Keivotos")
            self.assertEqual(settings.put_user_setting("profile_name", UserSettingUpdate(value="  Curator  ")).value, "Curator")
            self.assertEqual(settings.get_user_setting("profile_name").value, "Curator")
            self.assertEqual(settings.put_user_setting("profile_name", UserSettingUpdate(value="x" * 60)).value, "x" * 40)
            self.assertEqual(settings.put_user_setting("profile_name", UserSettingUpdate(value=" ")).value, "Keivotos")
            for operation in (lambda: settings.get_user_setting("unknown"),
                              lambda: settings.put_user_setting("unknown", UserSettingUpdate(value="x"))):
                with self.assertRaises(HTTPException) as caught:
                    operation()
                self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
