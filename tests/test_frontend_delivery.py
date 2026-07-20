from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from server import serve_index  # noqa: E402


class FrontendDeliveryTests(unittest.TestCase):
    def test_index_never_reuses_a_stale_asset_manifest(self) -> None:
        response = asyncio.run(serve_index())

        self.assertEqual(
            response.headers["cache-control"],
            "no-store, no-cache, must-revalidate",
        )
        self.assertEqual(response.headers["pragma"], "no-cache")
        self.assertEqual(response.headers["expires"], "0")


if __name__ == "__main__":
    unittest.main()
