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
- ``routers/tools.py`` still mixes Danbooru operations with suite backup,
  recovery and cache endpoints. Its separation is the next slice; it is not
  enforced as suite core yet. Other Danbooru routers now live in the module.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"

# Recursively-enforced base/suite directories.
CORE_DIRS = ("files_base", "services")

# Individually-enforced base/suite files (verified free of ``modules.*`` today).
CORE_FILES = (
    "config.py",
    "database.py",
    "schema.py",
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
)


def _imported_names(path: Path) -> set[str]:
    """Absolute module names imported by ``path`` (``import x`` / ``from x import``)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import (never crosses to ``modules.*`` here).
            if node.module and node.level == 0:
                names.add(node.module)
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
