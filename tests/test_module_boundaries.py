"""Module-boundary enforcement — the modular monolith's first line of defence.

SUITE_MODULE_CONTRACT §2.5 locks one invariant: dependency direction is
one-way. **Modules depend on the base; the base never depends on a module**,
and no module reaches into another module. That rule is what keeps the base
from rotting into "a thing that knows every module" and is what makes each
module removable. Until now it was only a convention — nothing failed when it
was broken (ROADMAP: "module-boundary enforcement ☐ nothing currently fails
when a module leaks into the base"). This test is that tripwire.

Two rules are enforced:

1. **Base/suite core never imports ``modules.*``.** The core set below is the
   genuinely neutral ground floor; it is verified clean today.
2. **No cross-module imports.** A file under ``modules/<x>/`` may import its own
   package but never ``modules/<y>`` for another module ``y``.

The local watcher and its lifecycle hook live in Danbooru. The suite
``lifecycle.py`` is enforced as core below.

Deliberately *outside* the enforced core, for now:

- ``module_registry.py`` is the composition root — the one place allowed to
  import every module's descriptor factory. That is the registration boundary,
  not a leak.
All shared backend files and app.py are now scanned, with the historical
credentials alias explicitly exempted. Imports through that alias are forbidden
from shared code. This is an import boundary check; runtime absence is verified
separately by the Files-only browser runner.
"""
from __future__ import annotations

import ast
import importlib.util
import unittest
import tempfile
from unittest.mock import patch
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"

# Recursively-enforced base/suite directories.
CORE_DIRS = ("files_base", "services")

# Individually-enforced base/suite files (verified free of ``modules.*`` today).
CORE_FILES = (
    "config.py",
    "database.py",
    "user_schema.py",
    "database_connections.py",
    "maintenance.py",
    "routers/backups.py",
    "storage_layout.py",
    "models.py",
    "product.py",
    "security.py",
    "thumbnails.py",
    "app_factory.py",
    "module_descriptor.py",
    "suite_modules.py",
    "lifecycle.py",
    "routers/files.py",
    "routers/suite.py",
    "routers/user_settings.py",
    "routers/recovery.py",
    "routers/storage.py",
    "routers/cache.py",
)


def _imported_names(path: Path) -> set[str]:
    """Absolute module names imported by ``path`` (``import x`` / ``from x import``)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                package = '.'.join(path.relative_to(BACKEND).parent.parts)
                module = importlib.util.resolve_name('.' * node.level + module, package)
            if module:
                names.add(module)
                names.update(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call) and node.args:
            function = node.func
            dynamic = (isinstance(function, ast.Name) and function.id == '__import__') or (
                isinstance(function, ast.Attribute) and function.attr == 'import_module')
            if dynamic and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                names.add(node.args[0].value)
    return names


def _module_slug(imported: str) -> str | None:
    """``modules.danbooru.foo`` -> ``danbooru``; anything else -> ``None``."""
    parts = imported.split(".")
    if len(parts) >= 2 and parts[0] == "modules":
        return parts[1]
    return None


class ModuleBoundaryTests(unittest.TestCase):
    def _core_paths(self) -> list[Path]:
        paths: list[Path] = []
        for directory in CORE_DIRS:
            paths.extend(sorted((BACKEND / directory).rglob("*.py")))
        for name in CORE_FILES:
            candidate = BACKEND / name
            self.assertTrue(candidate.exists(), f"core file missing: {name}")
            paths.append(candidate)
        return paths

    def test_core_never_imports_a_module(self) -> None:
        offenders = [
            f"{path.relative_to(BACKEND)} -> {imported}"
            for path in self._core_paths()
            for imported in _imported_names(path)
            if _module_slug(imported) is not None
        ]
        self.assertEqual(
            offenders,
            [],
            "The base/suite core must not import any module (modules -> base only):\n"
            + "\n".join(offenders),
        )

    def test_every_shared_backend_file_avoids_modules_and_legacy_credentials(self):
        paths = [path for path in BACKEND.rglob('*.py')
                 if 'modules' not in path.relative_to(BACKEND).parts
                 and path.name not in ('module_registry.py', 'credentials.py')]
        paths.append(BACKEND.parent / 'app.py')
        offenders = [f"{path.name} -> {name}" for path in paths
                     for name in _imported_names(path)
                     if _module_slug(name) or name.split('.')[0] == 'credentials']
        self.assertEqual(offenders, [])

    def test_import_scan_covers_relative_from_and_literal_dynamic_edges(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'modules/fixture/example.py'
            path.parent.mkdir(parents=True)
            path.write_text("from ..danbooru import client\nfrom modules import danbooru\n"
                            "importlib.import_module('modules.danbooru.tools')\n"
                            "__import__('credentials')\n")
            with patch.dict(_imported_names.__globals__, {'BACKEND': root}):
                names = _imported_names(path)
            self.assertTrue({'modules.danbooru', 'modules.danbooru.client',
                             'modules.danbooru.tools', 'credentials'} <= names)

    def test_no_cross_module_imports(self) -> None:
        modules_root = BACKEND / "modules"
        offenders: list[str] = []
        for path in sorted(modules_root.rglob("*.py")):
            owner = path.relative_to(modules_root).parts[0]
            for imported in _imported_names(path):
                target = _module_slug(imported)
                if target is not None and target != owner:
                    offenders.append(f"{path.relative_to(BACKEND)} -> {imported}")
        self.assertEqual(
            offenders,
            [],
            "A module must not import another module:\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
