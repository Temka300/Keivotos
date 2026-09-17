"""Protect module setting normalization and central path compatibility."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import config
from modules.danbooru.configuration import get_automation_config


class ModuleConfigurationTests(unittest.TestCase):
    def test_descriptor_defaults_are_module_owned_and_not_shared_mutable_state(self):
        from modules.danbooru import descriptor
        from modules.danbooru import automation

        first = descriptor(Path("fixture"), "test")
        second = descriptor(Path("fixture"), "test")
        self.assertEqual(first.config_defaults, {
            "data_root": str(first.home / "library"), "metadata_dir": str(first.home),
            "gallery_dl_dir": str(first.home / "gallery-dl"), "automation_enabled": False,
            "automation_enabled_at": None, "automation_interval_minutes": 15,
        })
        first.config_defaults["automation_enabled"] = True
        self.assertFalse(second.config_defaults["automation_enabled"])
        self.assertIs(automation.get_automation_config, get_automation_config)

    def test_configuration_loads_with_only_files_registered(self):
        code = """
import json, module_registry
module_registry._DESCRIPTOR_FACTORIES = (module_registry.files_descriptor,)
import config
print(json.dumps({"module": config.DANBOORU_MODULE, "base": str(config.BASE_HOME),
                  "user": str(config.USER_DB_PATH), "backups": str(config.DEFAULT_BACKUP_DIR)}))
"""
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True,
                                    env={**os.environ, "KEIVOTOS_HOME":temp, "PYTHONPATH":str(ROOT/"backend")},
                                    capture_output=True, text=True)
            self.assertEqual(json.loads(result.stdout), {"module":None, "base":str(Path(temp)/"base"),
                                                        "user":str(Path(temp)/"user.sqlite"), "backups":str(Path(temp)/"backups")})
            self.assertFalse((Path(temp)/"modules/danbooru").exists())

    def test_watcher_settings_preserve_coercion_and_bounds(self):
        for value, expected in ((None,15), ("bad",15), (0,5), (2000,1440), ("30",30)):
            with self.subTest(value=value), patch.object(config, "_cfg", {"automation_enabled": True, "automation_enabled_at":"kept", "automation_interval_minutes":value}):
                self.assertEqual(get_automation_config(), {"enabled":True,"enabled_at":"kept","interval_minutes":expected})

    def test_relative_paths_remain_module_anchored(self):
        self.assertEqual(config._resolve_path("relative/path"), config.MODULE_HOME / "relative/path")
        absolute = (ROOT / "fixture").resolve()
        self.assertEqual(config._resolve_path(str(absolute)), absolute)

    def test_snapshot_preserves_unknown_settings_and_excludes_private_paths(self):
        settings={"data_root":"private", "metadata_dir":"private", "gallery_dl_dir":"private", "future_module_setting":{"value":1}, "automation_enabled":False}
        with patch.object(config,"_cfg",settings):
            self.assertEqual(config.runtime_config_snapshot(), {"future_module_setting":{"value":1},"automation_enabled":False})
