from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from routers import folders  # noqa: E402


class FolderPickerTests(unittest.TestCase):
    def test_modern_windows_picker_is_preferred(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="D:\\Pictures\n", stderr="")
        with patch.object(folders.os, "name", "nt"), patch.object(folders.subprocess, "run", return_value=completed) as run:
            result = folders.browse_for_folder()
        self.assertEqual(result, {"path": "D:\\Pictures"})
        self.assertIn("windows_folder_picker.py", run.call_args.args[0][1])

    def test_frozen_app_routes_picker_through_its_helper_mode(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="D:\\Archive\n", stderr="")
        with (
            patch.object(folders.os, "name", "nt"),
            patch.object(folders.sys, "frozen", True, create=True),
            patch.object(folders.subprocess, "run", return_value=completed) as run,
        ):
            result = folders.browse_for_folder()
        self.assertEqual(result, {"path": "D:\\Archive"})
        self.assertEqual(run.call_args.args[0], [sys.executable, "--folder-picker"])

    def test_native_picker_failure_does_not_fall_back_to_tkinter(self) -> None:
        native = SimpleNamespace(returncode=1, stdout="", stderr="COM failed")
        with (
            patch.object(folders.os, "name", "nt"),
            patch.object(folders.subprocess, "run", return_value=native) as run,
            self.assertRaises(folders.HTTPException) as raised,
        ):
            folders.browse_for_folder()
        self.assertEqual(raised.exception.status_code, 500)
        self.assertIn("Windows folder picker failed: COM failed", raised.exception.detail)
        self.assertEqual(run.call_count, 1)

    def test_picker_helper_has_no_tkinter_fallback(self) -> None:
        source = (ROOT / "scripts" / "windows_folder_picker.py").read_text(encoding="utf-8")
        self.assertNotIn("tkinter", source)
        self.assertNotIn("--fallback", source)
