"""Keep module API models and routing separate from shared suite contracts."""
import ast
import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import models
from modules.danbooru import descriptor, models as danbooru_models


class DanbooruApiOwnershipTests(unittest.TestCase):
    def test_shared_models_do_not_expose_danbooru_contracts(self):
        classes = {node.name for node in ast.parse((ROOT / "backend/models.py").read_text()).body
                   if isinstance(node, ast.ClassDef)}
        self.assertEqual(classes, {"UserSetting", "UserSettingUpdate", "BackupOptions", "BackupConfigurationUpdate",
                                   "BackupCreateRequest", "BackupRestoreRequest", "ThumbnailCacheLimitUpdate"})
        self.assertFalse(hasattr(models, "ImageSummary"))

    def test_every_model_caller_uses_the_owning_class(self):
        owners = {"models": models, "modules.danbooru.models": danbooru_models}
        checked = 0
        for path in (ROOT / "backend").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom) and node.module in owners:
                    caller_name = ".".join(path.relative_to(ROOT / "backend").with_suffix("").parts)
                    caller = importlib.import_module(caller_name)
                    for name in node.names:
                        self.assertIs(getattr(caller, name.asname or name.name), getattr(owners[node.module], name.name))
                        checked += 1
        self.assertGreater(checked, 60)

    def test_descriptor_mounts_each_module_route_once(self):
        from server import app

        routes = [route for router in descriptor(Path("unused"), "test").routers() for route in router.routes]
        self.assertGreater(len(routes), 50)
        schema = app.openapi()
        seen = set()
        for route in routes:
            for method in route.methods:
                key = (route.path, method)
                self.assertNotIn(key, seen)
                seen.add(key)
                self.assertIn(method.lower(), schema["paths"][route.path_format])
        self.assertTrue(all(route.endpoint.__module__.startswith("modules.danbooru.routers.") for route in routes))
