"""Release dates are explicit and cannot leak across version changes."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("set_version", ROOT / "scripts/release/set_version.py")
set_version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(set_version)


def test_release_date_requires_an_explicit_timezone():
    for value in ("2026-11-02T10:43:17", "not a date", "2026-11-02"):
        with pytest.raises(ValueError, match="timezone|ISO 8601"):
            set_version.release_timestamp(value)
    assert set_version.release_timestamp("2026-11-02T10:43:17+09:00") == "2026-11-02T10:43:17+09:00"
    assert set_version.release_timestamp("2026-11-01T23:43:17-04:00") == "2026-11-01T23:43:17-04:00"


def test_version_change_clears_old_release_date(tmp_path, monkeypatch):
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "product.py").write_text('VERSION = "1.2.1"\nRELEASED_AT = "2026-09-20T10:00:00+09:00"\n')
    monkeypatch.setattr(set_version, "ROOT", tmp_path)

    assert set_version.recorded_release_timestamp("1.2.2", None) == ""
    assert set_version.recorded_release_timestamp("1.2.1", None) == "2026-09-20T10:00:00+09:00"
    assert set_version.recorded_release_timestamp("1.2.2", "2026-11-02T10:43:17+09:00") == "2026-11-02T10:43:17+09:00"


def test_current_frontend_and_backend_release_identity_agree():
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    try:
        from product import RELEASED_AT, VERSION
    finally:
        sys.path.pop(0)
    frontend = (ROOT / "frontend/src/lib/product.ts").read_text(encoding="utf-8")
    assert f"export const VERSION = '{VERSION}';" in frontend
    assert f"export const RELEASED_AT = '{RELEASED_AT}';" in frontend
