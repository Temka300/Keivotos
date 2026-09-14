from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from files_base import serving  # noqa: E402


class ResolveServedFileTests(unittest.TestCase):
    """The containment chain — the security core of file serving."""

    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-files-serving"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.source = self.temp / "source"
        self.outside = self.temp / "outside"
        (self.source / "sub").mkdir(parents=True)
        self.outside.mkdir(parents=True)
        (self.source / "ok.txt").write_bytes(b"hello")
        (self.source / "sub" / "clip.mp4").write_bytes(b"video")
        (self.outside / "secret.txt").write_bytes(b"secret")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_resolves_a_contained_file(self) -> None:
        resolved = serving.resolve_served_file(self.source, "sub/clip.mp4", [])
        self.assertEqual(resolved.read_bytes(), b"video")

    @unittest.skipIf(os.name == "nt", "colon filenames require a POSIX filesystem")
    def test_resolves_posix_colon_filenames(self) -> None:
        for name in ("a:notes.txt", "a:", "sub/a:notes.txt", "日本語:notes.txt"):
            with self.subTest(name=name):
                target = self.source / name
                target.write_bytes(b"colon filename")
                resolved = serving.resolve_served_file(self.source, name, [])
                self.assertEqual(resolved, target.resolve())
                self.assertEqual(resolved.read_bytes(), b"colon filename")

    @unittest.skipIf(os.name == "nt", "colon filenames require a POSIX filesystem")
    def test_colon_filenames_keep_symlink_and_forbidden_root_guards(self) -> None:
        link = self.source / "a:escape.txt"
        link.symlink_to(self.outside / "secret.txt")
        with self.assertRaises(serving.ServeDenied) as caught:
            serving.resolve_served_file(self.source, link.name, [])
        self.assertEqual(caught.exception.status_code, 403)
        target = self.source / "a:private.txt"
        target.write_bytes(b"private")
        with self.assertRaises(serving.ServeDenied) as caught:
            serving.resolve_served_file(self.source, target.name, [self.source])
        self.assertEqual(caught.exception.status_code, 403)

    @unittest.skipUnless(os.name == "nt", "Windows drive-relative path semantics")
    def test_rejects_windows_drive_relative_paths(self) -> None:
        for name in ("C:notes.txt", "C:"):
            with self.subTest(name=name), self.assertRaises(serving.ServeDenied) as caught:
                serving.resolve_served_file(self.source, name, [])
            self.assertEqual(caught.exception.status_code, 400)

    def test_rejects_dotdot_traversal(self) -> None:
        with self.assertRaises(serving.ServeDenied) as caught:
            serving.resolve_served_file(self.source, "../outside/secret.txt", [])
        self.assertEqual(caught.exception.status_code, 400)

    def test_rejects_absolute_and_drive_paths(self) -> None:
        for hostile in ("/etc/passwd", "\\\\server\\share", "C:\\Windows\\win.ini", "C:/Windows/win.ini"):
            with self.assertRaises(serving.ServeDenied) as caught:
                serving.resolve_served_file(self.source, hostile, [])
            self.assertEqual(caught.exception.status_code, 400)

    def _escape_link(self) -> str:
        """Plant a reparse point escaping the source; return the path to request.

        A file symlink is the stronger case but needs SeCreateSymbolicLinkPrivilege
        on Windows (admin or Developer Mode), which is why this used to skip on an
        ordinary host. A directory junction needs no privilege and ``Path.resolve``
        follows it just the same, so it reaches the identical containment branch.
        """
        link = self.source / "escape"
        try:
            link.symlink_to(self.outside / "secret.txt")
            return "escape"
        except (OSError, NotImplementedError):
            pass
        if os.name != "nt":
            self.skipTest("symlink creation not permitted on this host")
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(self.outside)],
            capture_output=True,
        )
        if completed.returncode != 0 or not link.exists():
            self.skipTest("neither a symlink nor a junction can be created on this host")
        return "escape/secret.txt"

    def test_rejects_symlink_escape(self) -> None:
        requested = self._escape_link()
        with self.assertRaises(serving.ServeDenied) as caught:
            serving.resolve_served_file(self.source, requested, [])
        self.assertEqual(caught.exception.status_code, 403)

    def test_denies_the_suite_data_tree(self) -> None:
        # A source that overlaps a forbidden root must still refuse to serve it.
        with self.assertRaises(serving.ServeDenied) as caught:
            serving.resolve_served_file(self.source, "ok.txt", [self.source])
        self.assertEqual(caught.exception.status_code, 403)

    def test_missing_file_is_404(self) -> None:
        with self.assertRaises(serving.ServeDenied) as caught:
            serving.resolve_served_file(self.source, "nope.txt", [])
        self.assertEqual(caught.exception.status_code, 404)

    def test_directory_target_is_404(self) -> None:
        with self.assertRaises(serving.ServeDenied) as caught:
            serving.resolve_served_file(self.source, "sub", [])
        self.assertEqual(caught.exception.status_code, 404)


class InlineAllowlistTests(unittest.TestCase):
    def test_inert_media_renders_inline(self) -> None:
        for name, expected in [
            ("a.png", "image/png"),
            ("b.mp4", "video/mp4"),
            ("c.mp3", "audio/mpeg"),
            ("d.pdf", "application/pdf"),
            ("e.srt", "text/plain; charset=utf-8"),
        ]:
            media_type, inline = serving.inline_media_type(Path(name))
            self.assertTrue(inline, name)
            self.assertEqual(media_type, expected)

    def test_active_content_is_forced_to_download(self) -> None:
        # The XSS mitigation: html/svg/js and unknown types never render inline.
        for name in ("page.html", "vector.svg", "script.js", "model.zip", "data.xlsx"):
            media_type, inline = serving.inline_media_type(Path(name))
            self.assertFalse(inline, name)
            self.assertEqual(media_type, "application/octet-stream")

    def test_disposition_survives_non_ascii_and_blocks_injection(self) -> None:
        header = serving.content_disposition(
            "[Blue Archive] 鹿乃.pdf\r\nSet-Cookie: x", inline=False
        )
        self.assertTrue(header.startswith("attachment;"))
        self.assertNotIn("\n", header)
        self.assertIn("filename*=UTF-8''", header)


class RangeHeaderTests(unittest.TestCase):
    def test_parses_ranges_and_rejects_bad_ones(self) -> None:
        self.assertEqual(serving.parse_range_header("bytes=0-9", 100), (0, 9))
        self.assertEqual(serving.parse_range_header("bytes=90-", 100), (90, 99))
        self.assertEqual(serving.parse_range_header("bytes=-10", 100), (90, 99))
        self.assertIsNone(serving.parse_range_header(None, 100))
        self.assertIsNone(serving.parse_range_header("bytes=200-300", 100))


class ServeFileRouteTests(unittest.TestCase):
    """Exercise the router endpoint directly, like test_files_api."""

    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-files-serve-route"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.suite_home = self.temp / "suite"
        self.suite_home.mkdir(parents=True)
        self.library = self.temp / "library"
        (self.library / "sub").mkdir(parents=True)
        (self.library / "doc.pdf").write_bytes(b"%PDF-1.4 body")
        (self.library / "page.html").write_bytes(b"<script>alert(1)</script>")

        import config
        import database
        from routers import files

        self.files = files
        self._patchers = [
            patch.object(config, "SUITE_HOME", self.suite_home),
            patch.object(config, "FILES_DB_PATH", self.suite_home / "base" / "files.sqlite"),
            patch.object(database, "USER_DB_PATH", self.temp / "user.sqlite"),
        ]
        for patcher in self._patchers:
            patcher.start()
        self.source = files.register_source(
            files.SourceRegister(path=str(self.library), display_name="Lib")
        )

    def tearDown(self) -> None:
        for patcher in self._patchers:
            patcher.stop()
        shutil.rmtree(self.temp, ignore_errors=True)

    def _request(self, headers: dict[str, str] | None = None) -> SimpleNamespace:
        return SimpleNamespace(headers=headers or {})

    def test_serves_a_pdf_inline_with_guards(self) -> None:
        response = self.files.serve_file(
            self._request(), source_id=self.source.source_id, path="doc.pdf"
        )
        self.assertEqual(response.media_type, "application/pdf")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertTrue(response.headers["Content-Disposition"].startswith("inline;"))

    def test_html_is_forced_to_attachment(self) -> None:
        response = self.files.serve_file(
            self._request(), source_id=self.source.source_id, path="page.html"
        )
        self.assertEqual(response.media_type, "application/octet-stream")
        self.assertTrue(response.headers["Content-Disposition"].startswith("attachment;"))

    def test_range_request_returns_206(self) -> None:
        response = self.files.serve_file(
            self._request({"range": "bytes=0-3"}),
            source_id=self.source.source_id,
            path="doc.pdf",
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.headers["Content-Range"], "bytes 0-3/13")
        self.assertEqual(response.headers["Content-Length"], "4")

    def test_unknown_source_is_404(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as caught:
            self.files.serve_file(self._request(), source_id="src-nope", path="doc.pdf")
        self.assertEqual(caught.exception.status_code, 404)

    def test_traversal_out_of_source_is_refused(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as caught:
            self.files.serve_file(
                self._request(),
                source_id=self.source.source_id,
                path="../suite/user.sqlite",
            )
        self.assertEqual(caught.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
