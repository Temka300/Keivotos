from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import config  # noqa: E402


class AttachmentStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-attach-store"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)
        # Isolate the config singleton: a scratch config.json and a clean key.
        self._orig_cfg = dict(config._cfg)
        self._orig_runtime = config.RUNTIME_CONFIG_FILE
        config.RUNTIME_CONFIG_FILE = self.temp / "config.json"
        config._cfg.pop("attachment_root", None)

    def tearDown(self) -> None:
        config.RUNTIME_CONFIG_FILE = self._orig_runtime
        config._cfg.clear()
        config._cfg.update(self._orig_cfg)
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_default_is_the_files_base_home(self) -> None:
        self.assertEqual(config.attachment_store_root(), config.BASE_HOME)

    def test_mode_is_managed_by_default_and_folder_when_configured(self) -> None:
        self.assertEqual(config.attachment_store_mode(), "managed")
        target = self.temp / "visible-store"
        config.set_attachment_store_root(str(target))
        self.assertEqual(config.attachment_store_mode(), "folder")
        config.set_attachment_store_root(None)
        self.assertEqual(config.attachment_store_mode(), "managed")

    def test_managed_and_visible_layouts_write_where_expected_and_resolve(self) -> None:
        from files_base import attachment_store

        root = self.temp / "store"
        root.mkdir()
        data = b"attachment-bytes"
        digest = attachment_store.md5_bytes(data)

        managed = attachment_store.write_attachment(root, digest, "png", data, visible=False)
        self.assertEqual(managed.parent, root / ".keivotos" / "attachments" / digest[:2])
        self.assertTrue(managed.is_file())
        # Managed bytes hide under the scan-excluded directory.
        from files_base.index import EXCLUDED_DIR_NAMES

        self.assertIn(".keivotos", EXCLUDED_DIR_NAMES)
        self.assertEqual(attachment_store.resolve_attachment(root, digest, "png"), managed)

        other = self.temp / "visible"
        other.mkdir()
        visible = attachment_store.write_attachment(other, digest, "png", data, visible=True)
        self.assertEqual(visible, other / "Attachments" / f"{digest}.png")
        self.assertTrue(visible.is_file())
        # A browsable folder, not the hidden one.
        self.assertNotIn(".keivotos", str(visible))
        self.assertEqual(attachment_store.resolve_attachment(other, digest, "png"), visible)

    def test_delete_removes_the_bytes_in_either_layout(self) -> None:
        from files_base import attachment_store

        root = self.temp / "store"
        root.mkdir()
        data = b"bye"
        digest = attachment_store.md5_bytes(data)
        visible = attachment_store.write_attachment(root, digest, "jpg", data, visible=True)
        self.assertTrue(visible.is_file())
        attachment_store.delete_attachment_file(root, digest, "jpg")
        self.assertFalse(visible.exists())

    def test_set_persists_then_reset_returns_to_default(self) -> None:
        target = self.temp / "attachments"
        target.mkdir()
        config.set_attachment_store_root(str(target))
        self.assertEqual(config.attachment_store_root(), target)
        # It is written to the scratch config, not left only in memory.
        self.assertIn("attachment_root", config.RUNTIME_CONFIG_FILE.read_text(encoding="utf-8"))

        config.set_attachment_store_root(None)
        self.assertEqual(config.attachment_store_root(), config.BASE_HOME)

    def test_blank_path_resets_to_default(self) -> None:
        target = self.temp / "custom"
        target.mkdir()
        config.set_attachment_store_root(str(target))
        config.set_attachment_store_root("   ")
        self.assertEqual(config.attachment_store_root(), config.BASE_HOME)

    def test_endpoints_get_set_validate_and_reset(self) -> None:
        # Called directly (this env has no httpx for a TestClient), the same way
        # the other Files tests exercise route functions.
        from fastapi import HTTPException
        from routers import files

        default_info = files.get_attachment_store()
        self.assertTrue(default_info.is_default)
        self.assertEqual(default_info.mode, "managed")

        target = self.temp / "endpoint-store"
        set_ok = files.set_attachment_store(files.AttachmentStoreRequest(path=str(target)))
        self.assertFalse(set_ok.is_default)
        self.assertEqual(set_ok.mode, "folder")
        self.assertTrue(target.is_dir())  # created on set

        # A bare drive root is refused.
        drive_root = str(Path(target.anchor)) if target.anchor else "/"
        with self.assertRaises(HTTPException) as ctx:
            files.set_attachment_store(files.AttachmentStoreRequest(path=drive_root))
        self.assertEqual(ctx.exception.status_code, 400)

        reset = files.set_attachment_store(files.AttachmentStoreRequest(path=None))
        self.assertTrue(reset.is_default)


if __name__ == "__main__":
    unittest.main()
