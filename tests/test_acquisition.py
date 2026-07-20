from __future__ import annotations

import base64
import io
import json
import shutil
import sys
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import credentials  # noqa: E402
import core  # noqa: E402
import danbooru_gallery_dl as gallery  # noqa: E402
from routers import tools as tool_routes  # noqa: E402
from routers import images_media as image_routes  # noqa: E402


class AcquisitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-acquisition"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_gallery_download_metadata_becomes_canonical_sidecar(self) -> None:
        data_root = self.temp / "data-root"
        destination = data_root / "Library"
        sidecar_dir = self.temp / "sidecars"
        destination.mkdir(parents=True)
        media = destination / "42_0123456789abcdef0123456789abcdef.jpg"
        media.write_bytes(b"test image bytes")
        raw = {
            "id": 42,
            "md5": "0123456789abcdef0123456789abcdef",
            "rating": "s",
            "tag_string": "1girl blue_archive",
            "tag_string_general": "1girl",
            "tag_string_copyright": "blue_archive",
            "tag_string_character": "",
            "tag_string_artist": "",
            "tag_string_meta": "",
            "file_ext": "jpg",
        }
        Path(str(media) + ".danbooru.json").write_text(json.dumps(raw), encoding="utf-8")
        args = gallery.build_parser().parse_args([
            "--root", str(data_root),
            "--sidecar-dir", str(sidecar_dir),
            "download", "blue_archive", "--destination", str(destination),
        ])

        normalized, failed = gallery.normalize_gallery_dl_sidecars(destination, args)

        canonical = sidecar_dir / "roots" / "portable-root" / "Library" / (media.name + ".danbooru.json")
        payload = json.loads(canonical.read_text(encoding="utf-8"))
        self.assertEqual((normalized, failed), (1, 0))
        self.assertEqual(payload["post"]["id"], 42)
        self.assertEqual(payload["post"]["rating"], "s")
        self.assertEqual(payload["tags"]["all"], ["1girl", "blue_archive"])
        self.assertEqual(payload["local_file"]["path"], str(media))

    def test_external_sidecar_resolves_real_media_for_orphan_check(self) -> None:
        data_root = self.temp / "data-root"
        sidecar_dir = self.temp / "sidecars"
        media = self.temp / "external" / "sample.jpg"
        media.parent.mkdir()
        media.write_bytes(b"external media")
        metadata = gallery.metadata_path_for(media, ".danbooru.json", data_root, sidecar_dir)
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps({"local_file": {"path": str(media)}}), encoding="utf-8")

        resolved = gallery.media_path_for_sidecar(metadata, ".danbooru.json", data_root, sidecar_dir)

        self.assertEqual(resolved, media)
        self.assertTrue(resolved.exists())

    def test_orphan_cleanup_skips_unavailable_media_root(self) -> None:
        data_root = self.temp / "data-root"
        sidecar_dir = self.temp / "sidecars"
        unavailable_root = data_root / "OfflineLibrary"
        missing_media = unavailable_root / "missing.jpg"
        metadata = sidecar_dir / "OfflineLibrary" / "missing.jpg.danbooru.json"
        metadata.parent.mkdir(parents=True)
        metadata.write_text(
            json.dumps({"local_file": {"path": str(missing_media)}}),
            encoding="utf-8",
        )

        while_offline = gallery.orphan_sidecar_files(
            [sidecar_dir], [".danbooru.json"], data_root, sidecar_dir
        )
        unavailable_root.mkdir(parents=True)
        while_online = gallery.orphan_sidecar_files(
            [sidecar_dir], [".danbooru.json"], data_root, sidecar_dir
        )

        self.assertEqual(while_offline, [])
        self.assertEqual(while_online, [metadata])

    def test_saved_api_key_is_encrypted_and_never_returned(self) -> None:
        credential_path = self.temp / "danbooru_credentials.json"

        def protect(value: str) -> str:
            return base64.b64encode(("protected:" + value).encode()).decode()

        def unprotect(value: str) -> str:
            return base64.b64decode(value).decode().removeprefix("protected:")

        with (
            patch.object(credentials, "CREDENTIALS_PATH", credential_path),
            patch.object(credentials, "_protect", protect),
            patch.object(credentials, "_unprotect", unprotect),
            patch.dict("os.environ", {"DANBOORU_USERNAME": "", "DANBOORU_API_KEY": ""}),
        ):
            status = credentials.save_credentials("local-user", "very-secret-key")
            environment = credentials.credential_environment()
            stored = credential_path.read_text(encoding="utf-8")

        self.assertEqual(status["username"], "local-user")
        self.assertTrue(status["configured"])
        self.assertNotIn("very-secret-key", status.values())
        self.assertNotIn("very-secret-key", stored)
        self.assertEqual(environment["DANBOORU_API_KEY"], "very-secret-key")

    def test_gallery_config_with_credentials_is_transient(self) -> None:
        work_dir = self.temp / "gallery-work"
        destination = self.temp / "destination"
        destination.mkdir()
        args = gallery.build_parser().parse_args([
            "--root", str(self.temp),
            "--gallery-dl-dir", str(work_dir),
            "download", "blue_archive", "--destination", str(destination), "--dry-run",
        ])
        output = io.StringIO()
        with (
            patch.dict("os.environ", {
                "DANBOORU_USERNAME": "local-user",
                "DANBOORU_API_KEY": "very-secret-key",
            }),
            redirect_stdout(output),
        ):
            result = gallery.run_download(args)

        self.assertEqual(result, 0)
        self.assertNotIn("very-secret-key", output.getvalue())
        self.assertEqual(list((work_dir / "configs").glob("*.json")), [])

    def test_twitter_profile_info_extracts_avatar_and_full_banner(self) -> None:
        messages = [[1, {
            "name": "sample_artist",
            "profile_image": "https://pbs.twimg.com/profile_images/1/avatar.jpg",
            "profile_banner": "https://pbs.twimg.com/profile_banners/1/1234567890",
        }]]

        self.assertEqual(
            core.twitter_profile_media_from_messages(messages),
            {
                "avatar": "https://pbs.twimg.com/profile_images/1/avatar.jpg",
                "banner": "https://pbs.twimg.com/profile_banners/1/1234567890/1500x500",
            },
        )

    def test_bundled_gallery_dl_is_found_next_to_venv_python(self) -> None:
        bundled = self.temp / "gallery-dl.exe"
        bundled.write_bytes(b"")
        with (
            patch.object(core.shutil, "which", return_value=None),
            patch.object(core.sys, "platform", "win32"),
            patch.object(core.sys, "executable", str(self.temp / "python.exe")),
        ):
            self.assertEqual(core.gallery_dl_command(), [str(bundled)])

    def test_frozen_gallery_dl_never_uses_an_older_path_installation(self) -> None:
        bundled = self.temp / "gallery-dl.exe"
        bundled.write_bytes(b"")
        with (
            patch.object(core.shutil, "which", return_value=str(self.temp / "old-path" / "gallery-dl.exe")),
            patch.object(core.sys, "platform", "win32"),
            patch.object(core.sys, "executable", str(self.temp / "Keivotos.exe")),
            patch.object(core.sys, "frozen", True, create=True),
        ):
            self.assertEqual(core.gallery_dl_command(), [str(bundled)])

    def test_dimension_read_hides_only_the_corrupt_exif_warning(self) -> None:
        class FakeImage:
            size = (640, 480)

            def __enter__(self):
                warnings.warn(
                    "Corrupt EXIF data.  Expecting to read 4 bytes but only got 0.",
                    UserWarning,
                )
                return self

            def __exit__(self, *_args):
                return False

        with patch.object(gallery._PILImage, "open", return_value=FakeImage()):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                dimensions = gallery.image_dimensions(self.temp / "corrupt-exif.jpg")

        self.assertEqual(dimensions, (640, 480))
        self.assertEqual(caught, [])

    def test_repo_venv_gallery_dl_is_found_when_server_python_is_global(self) -> None:
        backend_dir = self.temp / "repo" / "backend"
        bundled = self.temp / "repo" / ".venv" / "Scripts" / "gallery-dl.exe"
        backend_dir.mkdir(parents=True)
        bundled.parent.mkdir(parents=True)
        bundled.write_bytes(b"")
        with (
            patch.object(core.shutil, "which", return_value=None),
            patch.object(core.sys, "platform", "win32"),
            patch.object(core.sys, "executable", str(self.temp / "global" / "python.exe")),
            patch.object(core, "__file__", str(backend_dir / "core.py")),
        ):
            self.assertEqual(core.gallery_dl_command(), [str(bundled)])

    def test_open_location_uses_all_managed_library_roots(self) -> None:
        media = self.temp / "external-library" / "image.jpg"
        media.parent.mkdir()
        media.write_bytes(b"image")
        with (
            patch.object(image_routes, "get_post_file_identity", return_value={"path": str(media)}),
            patch.object(image_routes, "ensure_managed_path") as ensure_managed,
            patch.object(image_routes.sys, "platform", "win32"),
            patch("subprocess.Popen") as popen,
        ):
            result = image_routes.open_image_location(42)

        ensure_managed.assert_called_once_with(media.resolve(strict=False), "open")
        popen.assert_called_once_with(["explorer.exe", "/select,", str(media.resolve(strict=False))])
        self.assertEqual(result["status"], "opened")

    def test_backfill_tool_targets_existing_images_by_folder(self) -> None:
        media_folder = self.temp / "existing-images"
        media_folder.mkdir()
        request = tool_routes.BackfillToolRequest(folder=str(media_folder), limit=25)
        with patch.object(tool_routes, "_launch_tool", return_value={"status": "started"}) as launch:
            tool_routes.run_backfill_tool(request)

        command = launch.call_args.args[1][0]
        self.assertIn("backfill", command)
        self.assertIn(str(media_folder), command)
        self.assertEqual(command[command.index("--limit") + 1], "25")

    def test_settings_preserves_original_five_maintenance_tools(self) -> None:
        self.assertEqual(
            [(tool["id"], tool["name"]) for tool in tool_routes.TOOL_DEFINITIONS],
            [
                ("sync", "Sync Database"),
                ("backfill", "Backfill Metadata"),
                ("sqlite", "Rebuild Database (Recovery)"),
                ("clean-sidecars", "Clean Orphan Sidecars"),
                ("refresh-tags", "Update Danbooru Tags"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
