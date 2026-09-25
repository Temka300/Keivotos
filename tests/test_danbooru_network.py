"""Small, offline regressions for Danbooru transport and wiki failures."""
from __future__ import annotations

import contextlib
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from modules.danbooru import client, network, pipeline
from modules.danbooru.routers import tags


class DanbooruNetworkTests(unittest.TestCase):
    def test_reset_then_success_is_bounded_and_redacted(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"id": 123}'
        request = MagicMock(full_url="https://danbooru.donmai.us/wiki_pages/cat.json?api_key=private")
        messages: list[str] = []
        with patch.object(network.urllib.request, "urlopen", side_effect=[
            urllib.error.URLError(ConnectionResetError(10054, "connection reset")), response,
        ]) as open_url, patch.object(network.time, "sleep") as sleep:
            result = network.read_json(request, timeout=6, retries=1, emit=messages.append,
                                       secrets=("private",))
        self.assertEqual(result, {"id": 123})
        self.assertEqual(open_url.call_count, 2)
        self.assertEqual(open_url.call_args.kwargs["timeout"], 6)
        sleep.assert_called_once_with(2)
        self.assertIn("connection", messages[0])
        self.assertNotIn("private", "\n".join(messages))

    def test_persistent_reset_has_concise_public_error_and_keeps_status(self):
        reset = urllib.error.URLError(ConnectionResetError(10054, "connection reset"))
        with patch.object(client, "effective_credentials", return_value=(None, None, "none")), \
             patch.object(client, "read_json", side_effect=reset) as read:
            with self.assertRaises(HTTPException) as caught:
                client.danbooru_json("/wiki_pages/cat.json", {})
        self.assertEqual(read.call_args.kwargs["retries"], 2)
        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("check access", caught.exception.detail)
        self.assertNotIn("10054", caught.exception.detail)

    def test_http_failures_stay_distinct_from_connection_reset(self):
        for status in (401, 403, 429, 404, 503):
            with self.subTest(status=status):
                error = urllib.error.HTTPError("https://danbooru.donmai.us/", status,
                                               "failure", {}, None)
                with patch.object(client, "effective_credentials", return_value=(None, None, "none")), \
                     patch.object(client, "read_json", side_effect=error):
                    with self.assertRaises(HTTPException) as caught:
                        client.danbooru_json("/wiki_pages/cat.json", {})
                self.assertEqual(caught.exception.status_code, 404 if status == 404 else 502)
                self.assertNotIn("Connection to Danbooru", caught.exception.detail)

    def test_wiki_refresh_failure_returns_saved_row_without_replacing_it(self):
        row = {"tag_name": "cat", "body": "saved wiki text"}
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = row
        saved = object()
        with patch.object(tags, "get_user_db", return_value=contextlib.nullcontext(connection)), \
             patch.object(tags, "fetch_tag_wiki_values", side_effect=HTTPException(502, "connection failed")), \
             patch.object(tags, "tag_wiki_info_from_cache_row", return_value=saved) as from_cache, \
             patch.object(tags, "save_tag_wiki_cache") as save:
            result = tags.tag_wiki("cat", refresh=True)
        self.assertIs(result, saved)
        self.assertIs(from_cache.call_args.args[1], row)
        self.assertEqual(from_cache.call_args.args[2], "connection failed")
        save.assert_not_called()

if __name__ == "__main__":
    unittest.main()
