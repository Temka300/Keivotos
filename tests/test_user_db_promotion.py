from __future__ import annotations

import shutil
import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import config  # noqa: E402


class UserDatabasePromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-user-promotion"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.legacy = self.temp / "modules" / "danbooru" / "user.sqlite"
        self.destination = self.temp / "user.sqlite"
        self.legacy.parent.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def _make_legacy(self) -> None:
        connection = sqlite3.connect(self.legacy)
        connection.execute("CREATE TABLE favorites (id INTEGER PRIMARY KEY, note TEXT)")
        connection.execute("INSERT INTO favorites (note) VALUES ('precious')")
        connection.commit()
        connection.close()

    def test_promotes_and_preserves_legacy(self) -> None:
        self._make_legacy()
        result = config.promote_user_database(self.legacy, self.destination)
        self.assertTrue(result["promoted"])
        # New suite-level file holds the real data...
        moved = sqlite3.connect(self.destination)
        note = moved.execute("SELECT note FROM favorites").fetchone()[0]
        moved.close()
        self.assertEqual(note, "precious")
        # ...and the legacy source is left untouched (never deleted).
        self.assertTrue(self.legacy.exists())

    def test_idempotent_when_destination_exists(self) -> None:
        self._make_legacy()
        self.destination.write_bytes(b"already here")
        result = config.promote_user_database(self.legacy, self.destination)
        self.assertFalse(result["promoted"])
        self.assertEqual(result["reason"], "already-suite-level")
        self.assertEqual(self.destination.read_bytes(), b"already here")

    def test_no_legacy_is_a_noop(self) -> None:
        result = config.promote_user_database(self.legacy, self.destination)
        self.assertFalse(result["promoted"])
        self.assertEqual(result["reason"], "no-legacy")
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
