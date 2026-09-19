"""Compatibility CLI/import path for the Danbooru-owned preservation pipeline.

Keep this filename for existing commands and packaged helper dispatch. Imported
callers receive the owner module itself, so globals and monkeypatches retain the
same identity through both historical import spellings.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from modules.danbooru import pipeline as _pipeline  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_pipeline.main())
else:
    sys.modules[__name__] = _pipeline
