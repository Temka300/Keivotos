from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from files_base import filesystem, hashing, index  # noqa: E402


class FilesBaseIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-files-base"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.library = self.temp / "library"
        (self.library / "sub").mkdir(parents=True)
        # A deliberately mixed, non-image set: the base is type-agnostic.
        (self.library / "a.png").write_bytes(b"png-bytes")
        (self.library / "data.xlsx").write_bytes(b"xlsx-bytes")
        (self.library / "Report.DOCX").write_bytes(b"docx-bytes")
        (self.library / "sub" / "w.webp").write_bytes(b"webp-bytes")
        (self.library / "sub" / "1.gif").write_bytes(b"gif-bytes")
        self.db_path = self.temp / "base" / "files.sqlite"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_scan_indexes_every_type_and_records_cheap_facts(self) -> None:
        with index.open_index(self.db_path) as connection:
            summary = index.scan_source(connection, "src-1", self.library)
            self.assertEqual(summary["files"], 5)
            self.assertEqual(summary["directories"], 1)

            top = index.list_directory(connection, "src-1", "")
            # Directory first, then files sorted case-insensitively by name.
            self.assertEqual(top[0].name, "sub")
            self.assertTrue(top[0].is_dir)
            names = [entry.name for entry in top if not entry.is_dir]
            self.assertEqual(names, ["a.png", "data.xlsx", "Report.DOCX"])

            by_name = {entry.name: entry for entry in top}
            # Extension is lowercased and dot-stripped; sizes are recorded.
            self.assertEqual(by_name["Report.DOCX"].ext, "docx")
            self.assertEqual(by_name["a.png"].size, len(b"png-bytes"))
            self.assertIsNone(by_name["a.png"].content_hash)  # hashing is lazy

    def test_browse_into_subdirectory(self) -> None:
        with index.open_index(self.db_path) as connection:
            index.scan_source(connection, "src-1", self.library)
            children = index.list_directory(connection, "src-1", "sub")
            self.assertEqual(
                sorted(entry.name for entry in children), ["1.gif", "w.webp"]
            )

    def test_name_search_is_case_insensitive_substring(self) -> None:
        with index.open_index(self.db_path) as connection:
            index.scan_source(connection, "src-1", self.library)
            hits = index.search_by_name(connection, "report")
            self.assertEqual([entry.name for entry in hits], ["Report.DOCX"])

    def test_scan_availability_does_not_depend_on_clock_progress(self) -> None:
        for next_time in ("2026-09-15T12:00:00+00:00", "2026-09-15T11:00:00+00:00"):
            with self.subTest(next_time=next_time):
                missing = self.library / "a.png"
                missing.write_bytes(b"png-bytes")
                with index.open_index(self.db_path) as connection:
                    with patch.object(index, "_now", return_value="2026-09-15T12:00:00+00:00"):
                        index.scan_source(connection, "src-1", self.library)
                    before = connection.execute("SELECT id, indexed_at, seen_at FROM files_index WHERE path = ?", (str(missing),)).fetchone()
                    missing.unlink()
                    with patch.object(index, "_now", return_value=next_time):
                        summary = index.scan_source(connection, "src-1", self.library)
                    self.assertEqual(summary["unavailable"], 1)
                    after = connection.execute("SELECT id, indexed_at, seen_at, available FROM files_index WHERE path = ?", (str(missing),)).fetchone()
                    self.assertEqual(tuple(after)[:3], tuple(before))
                    self.assertEqual(after["available"], 0)
                    self.assertEqual(len(index.list_directory(connection, "src-1", "")), 3)
                    missing.write_bytes(b"png-bytes")
                    with patch.object(index, "_now", return_value=next_time):
                        self.assertEqual(index.scan_source(connection, "src-1", self.library)["unavailable"], 0)
                    restored = connection.execute("SELECT id, available FROM files_index WHERE path = ?", (str(missing),)).fetchone()
                    self.assertEqual(restored["id"], before["id"])
                    self.assertEqual(restored["available"], 1)

    def test_missing_file_is_marked_unavailable_not_deleted(self) -> None:
        with index.open_index(self.db_path) as connection:
            index.scan_source(connection, "src-1", self.library)
            (self.library / "a.png").unlink()
            summary = index.scan_source(connection, "src-1", self.library)
            self.assertEqual(summary["unavailable"], 1)

            # Default listing hides it, but the row survives (missing != deleted).
            visible = [e.name for e in index.list_directory(connection, "src-1", "")]
            self.assertNotIn("a.png", visible)
            all_rows = index.list_directory(
                connection, "src-1", "", include_unavailable=True
            )
            gone = next(e for e in all_rows if e.name == "a.png")
            self.assertFalse(gone.available)

    def test_rescan_is_idempotent(self) -> None:
        with index.open_index(self.db_path) as connection:
            index.scan_source(connection, "src-1", self.library)
            index.scan_source(connection, "src-1", self.library)
            rows = connection.execute("SELECT COUNT(*) FROM files_index").fetchone()[0]
            self.assertEqual(rows, 6)  # 5 files + 1 directory, no duplicates

    def test_registered_child_root_keeps_stable_ownership_on_parent_rescan(self) -> None:
        child = self.library / "sub"
        with index.open_index(self.db_path) as connection:
            # Characterize the upgrade path: the parent may already own every
            # descendant before the child is registered.
            index.scan_source(connection, "src-parent", self.library)
            index.scan_source(connection, "src-child", child)
            index.scan_source(
                connection,
                "src-parent",
                self.library,
                excluded_roots=[child],
            )

            self.assertEqual(
                [entry.name for entry in index.list_directory(connection, "src-parent", "")],
                ["sub", "a.png", "data.xlsx", "Report.DOCX"],
            )
            self.assertEqual(
                sorted(entry.name for entry in index.list_directory(connection, "src-child", "")),
                ["1.gif", "w.webp"],
            )
            self.assertEqual(
                index.list_directory(connection, "src-parent", "sub"),
                [],
            )
            owners = connection.execute(
                "SELECT DISTINCT source_id FROM files_index WHERE path LIKE ?",
                (f"{child}%",),
            ).fetchall()
            self.assertEqual(
                {row["source_id"] for row in owners},
                {"src-parent", "src-child"},
            )  # the child directory belongs to the parent; its contents do not


class FilesBaseHashingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-files-hashing"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.a = self.temp / "source-a"
        self.b = self.temp / "source-b"
        self.a.mkdir(parents=True)
        self.b.mkdir(parents=True)
        # Same bytes in two sources (a true duplicate)...
        (self.a / "original.png").write_bytes(b"same-bytes")
        (self.b / "copy.png").write_bytes(b"same-bytes")
        # ...same size but different bytes (a hash candidate, not a duplicate)...
        (self.a / "decoy.txt").write_bytes(b"aame-bytes")
        # ...and a unique size that must never be hashed.
        (self.a / "unique.txt").write_bytes(b"completely different length")
        self.db_path = self.temp / "files.sqlite"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def _scan_both(self, connection) -> None:
        index.scan_source(connection, "src-a", self.a)
        index.scan_source(connection, "src-b", self.b)

    def test_only_size_colliding_files_are_hashed(self) -> None:
        with index.open_index(self.db_path) as connection:
            self._scan_both(connection)
            summary = hashing.compute_missing_hashes(connection)
            # original + copy + decoy collide on size; unique.txt is skipped.
            self.assertEqual(summary["hashed"], 3)
            self.assertEqual(summary["remaining"], 0)
            unhashed = connection.execute(
                "SELECT name FROM files_index WHERE is_dir = 0 AND content_hash IS NULL"
            ).fetchall()
            self.assertEqual([row["name"] for row in unhashed], ["unique.txt"])

    def test_duplicates_are_grouped_across_sources(self) -> None:
        with index.open_index(self.db_path) as connection:
            self._scan_both(connection)
            hashing.compute_missing_hashes(connection)
            groups = hashing.find_duplicates(connection)
            self.assertEqual(len(groups), 1)
            names = sorted(entry.name for entry in groups[0])
            self.assertEqual(names, ["copy.png", "original.png"])
            sources = {entry.source_id for entry in groups[0]}
            self.assertEqual(sources, {"src-a", "src-b"})  # dedup sees across sources

    def test_hashing_is_incremental_and_idempotent(self) -> None:
        with index.open_index(self.db_path) as connection:
            self._scan_both(connection)
            first = hashing.compute_missing_hashes(connection, limit=2)
            self.assertEqual(first["hashed"], 2)
            self.assertEqual(first["remaining"], 1)
            second = hashing.compute_missing_hashes(connection)
            self.assertEqual(second["hashed"], 1)
            third = hashing.compute_missing_hashes(connection)
            self.assertEqual(third["hashed"], 0)  # nothing left to do


class FolderPickerFilesystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-fs-picker"
        shutil.rmtree(self.temp, ignore_errors=True)
        (self.temp / "photos").mkdir(parents=True)
        (self.temp / "music").mkdir()
        (self.temp / ".hidden").mkdir()
        (self.temp / "note.txt").write_bytes(b"x")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_lists_only_visible_subdirectories(self) -> None:
        listing = filesystem.list_directories(str(self.temp))
        names = [entry["name"] for entry in listing["entries"]]
        self.assertEqual(names, ["music", "photos"])  # no files, no dotfolders
        self.assertFalse(listing["is_root"])
        self.assertEqual(listing["parent"], str(self.temp.parent))

    def test_empty_path_returns_root_or_drives(self) -> None:
        listing = filesystem.list_directories("")
        self.assertTrue(listing["is_root"])
        self.assertIsNone(listing["parent"])
        self.assertTrue(len(listing["entries"]) >= 1)

    def test_native_picker_reuses_the_windows_helper(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch

        completed = SimpleNamespace(returncode=0, stdout="D:\\Pictures\n", stderr="")
        with patch.object(filesystem.subprocess, "run", return_value=completed) as run:
            chosen = filesystem.native_pick_folder(ROOT)
        self.assertEqual(chosen, "D:\\Pictures")
        self.assertIn("windows_folder_picker.py", run.call_args.args[0][1])


if __name__ == "__main__":
    unittest.main()
