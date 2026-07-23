from __future__ import annotations

import shutil
import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from files_base import annotations  # noqa: E402


class AnnotationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-files-annotations"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)
        self.conn = sqlite3.connect(self.temp / "user.sqlite")
        self.conn.row_factory = sqlite3.Row
        annotations.ensure_annotations_schema(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_schema_is_idempotent_and_additive(self) -> None:
        # Re-running ensure over an existing schema must not raise or drop data.
        annotations.upsert_annotation(
            self.conn, subject_kind="dir", source_id="src", relative_path="folder"
        )
        annotations.ensure_annotations_schema(self.conn)
        self.assertIsNotNone(
            annotations.get_annotation(
                self.conn, source_id="src", relative_path="folder"
            )
        )

    def test_file_annotation_follows_the_content_hash_not_the_path(self) -> None:
        created = annotations.upsert_annotation(
            self.conn,
            subject_kind="file",
            content_hash="hash-A",
            source_id="src",
            relative_path="3D/iroha_ver1_0.zip",
            description="Booth model",
        )
        # Renamed + moved: same bytes, different location -> same annotation.
        found = annotations.get_annotation(
            self.conn,
            content_hash="hash-A",
            source_id="src",
            relative_path="3D/Booth/iroha v1.0.zip",
        )
        self.assertIsNotNone(found)
        self.assertEqual(found.id, created.id)
        self.assertEqual(found.description, "Booth model")

    def test_two_identical_files_share_one_annotation(self) -> None:
        first = annotations.upsert_annotation(
            self.conn,
            subject_kind="file",
            content_hash="dupe",
            source_id="src",
            relative_path="a/copy1.png",
        )
        second = annotations.upsert_annotation(
            self.conn,
            subject_kind="file",
            content_hash="dupe",
            source_id="src",
            relative_path="b/copy2.png",
        )
        self.assertEqual(first.id, second.id)  # one row, not two
        rows = self.conn.execute("SELECT COUNT(*) FROM files_annotations").fetchone()[0]
        self.assertEqual(rows, 1)
        # The location hint tracks the most recent write.
        self.assertEqual(second.relative_path, "b/copy2.png")

    def test_folder_annotation_is_keyed_by_path(self) -> None:
        annotations.upsert_annotation(
            self.conn,
            subject_kind="dir",
            source_id="src",
            relative_path="Kdrama subtitle",
            description="mixed subs",
        )
        self.assertIsNotNone(
            annotations.get_annotation(
                self.conn, source_id="src", relative_path="Kdrama subtitle"
            )
        )
        self.assertIsNone(
            annotations.get_annotation(
                self.conn, source_id="src", relative_path="Other folder"
            )
        )

    def test_unannotated_subject_resolves_to_none(self) -> None:
        # A file the user has not annotated (so never hashed) and an untouched
        # folder both resolve to nothing rather than an empty row.
        annotations.upsert_annotation(
            self.conn, subject_kind="dir", source_id="src", relative_path="annotated"
        )
        self.assertIsNone(
            annotations.get_annotation(
                self.conn, content_hash="never-hashed", source_id="src", relative_path="clip.mp4"
            )
        )
        self.assertIsNone(
            annotations.get_annotation(
                self.conn, source_id="src", relative_path="unannotated folder"
            )
        )

    def test_file_requires_hash_and_folder_forbids_hash(self) -> None:
        with self.assertRaises(ValueError):
            annotations.upsert_annotation(
                self.conn, subject_kind="file", source_id="src", relative_path="f"
            )
        with self.assertRaises(ValueError):
            annotations.upsert_annotation(
                self.conn,
                subject_kind="dir",
                content_hash="nope",
                source_id="src",
                relative_path="d",
            )

    def test_description_none_creates_empty_note_and_preserves_text(self) -> None:
        created = annotations.upsert_annotation(
            self.conn,
            subject_kind="dir",
            source_id="src",
            relative_path="d",
            description="keep me",
        )
        # A later touch (e.g. before adding a link) must not wipe the text.
        touched = annotations.upsert_annotation(
            self.conn, subject_kind="dir", source_id="src", relative_path="d"
        )
        self.assertEqual(touched.id, created.id)
        self.assertEqual(touched.description, "keep me")

    def test_links_replace_is_ordered_and_idempotent(self) -> None:
        note = annotations.upsert_annotation(
            self.conn,
            subject_kind="file",
            content_hash="h",
            source_id="src",
            relative_path="model.zip",
        )
        annotations.set_links(
            self.conn,
            note.id,
            [
                {"url": "https://booth.pm/en/items/4309253", "label": "Booth", "kind": "source"},
                {"url": "", "label": "blank is skipped", "kind": "other"},
                {"url": "https://forum.example/thread", "label": "Found here", "kind": "discussion"},
            ],
        )
        links = annotations.list_links(self.conn, note.id)
        self.assertEqual([l.kind for l in links], ["source", "discussion"])
        self.assertEqual([l.position for l in links], [0, 1])
        # Replacing shrinks the list rather than appending.
        annotations.set_links(self.conn, note.id, [{"url": "https://only.example"}])
        remaining = annotations.list_links(self.conn, note.id)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].kind, "source")  # default kind

    def test_attachment_rows_add_list_remove_with_shared_hash_refcount(self) -> None:
        one = annotations.upsert_annotation(
            self.conn, subject_kind="file", content_hash="a", source_id="s", relative_path="one"
        )
        two = annotations.upsert_annotation(
            self.conn, subject_kind="file", content_hash="b", source_id="s", relative_path="two"
        )
        # The same screenshot attached to two different notes stores one hash.
        annotations.add_attachment(
            self.conn, one.id, content_hash="shot", file_name="a.png",
            media_type="image/png", size=10,
        )
        second = annotations.add_attachment(
            self.conn, two.id, content_hash="shot", file_name="b.png",
            media_type="image/png", size=10,
        )
        self.assertEqual(annotations.attachment_hash_refcount(self.conn, "shot"), 2)
        self.assertEqual(len(annotations.list_attachments(self.conn, one.id)), 1)

        self.assertTrue(annotations.remove_attachment(self.conn, two.id, second.id))
        self.assertEqual(annotations.attachment_hash_refcount(self.conn, "shot"), 1)
        # Removing an attachment from the wrong annotation does nothing.
        self.assertFalse(annotations.remove_attachment(self.conn, two.id, second.id))

    def test_delete_is_explicit_and_cascades_children(self) -> None:
        note = annotations.upsert_annotation(
            self.conn, subject_kind="file", content_hash="h", source_id="s", relative_path="f"
        )
        annotations.set_links(self.conn, note.id, [{"url": "https://x.example"}])
        annotations.add_attachment(
            self.conn, note.id, content_hash="c", file_name="s.png",
            media_type="image/png", size=1,
        )
        self.assertTrue(annotations.delete_annotation(self.conn, note.id))
        self.assertIsNone(
            annotations.get_annotation(self.conn, content_hash="h", source_id="s", relative_path="f")
        )
        self.assertEqual(annotations.list_links(self.conn, note.id), [])
        self.assertEqual(annotations.list_attachments(self.conn, note.id), [])
        self.assertFalse(annotations.delete_annotation(self.conn, note.id))

    def test_annotated_keys_reports_hashes_and_folders(self) -> None:
        annotations.upsert_annotation(
            self.conn, subject_kind="file", content_hash="h1", source_id="s", relative_path="f1"
        )
        annotations.upsert_annotation(
            self.conn, subject_kind="dir", source_id="s", relative_path="Piano Sheets"
        )
        hashes, folders = annotations.annotated_keys(self.conn)
        self.assertEqual(hashes, {"h1"})
        self.assertEqual(folders, {("s", "Piano Sheets")})


if __name__ == "__main__":
    unittest.main()
