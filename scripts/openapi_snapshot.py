"""Write the committed FastAPI contract snapshot after an intentional API change."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from server import app  # noqa: E402


def main() -> None:
    target = ROOT / "tests" / "snapshots" / "openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"OpenAPI snapshot written: {target}")


if __name__ == "__main__":
    main()
