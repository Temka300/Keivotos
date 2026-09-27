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
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from modules.danbooru import client, configuration, network, pipeline
from modules.danbooru.routers import tags
from modules.danbooru.routers import tools as tool_routes
from modules.danbooru.models import DanbooruHostSettings


class DanbooruNetworkTests(unittest.TestCase):
    def test_manual_host_setting_persists_and_rejects_other_hosts(self):
        import config

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(config, "RUNTIME_CONFIG_FILE", Path(directory) / "config.json"), \
             patch.dict(config._cfg, {}, clear=True):
            self.assertEqual(configuration.get_api_host(), "danbooru")
            self.assertEqual(configuration.set_api_host("betabooru"), "betabooru")
            self.assertEqual(configuration.get_api_base_url(), "https://betabooru.donmai.us")
            self.assertEqual(config._read_json(config.RUNTIME_CONFIG_FILE)["danbooru_host"], "betabooru")
            with self.assertRaises(ValueError):
                configuration.set_api_host("other.example")
            self.assertEqual(configuration.get_api_host(), "betabooru")
            with self.assertRaises(ValidationError):
                DanbooruHostSettings(host="other.example")

    def test_selected_host_routes_wiki_and_post_lookup_without_changing_post_links(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"id": 123}'
        with patch.object(configuration, "get_api_host", return_value="betabooru"), \
             patch.object(client, "effective_credentials", return_value=("user", "key", "saved")), \
             patch.object(network.urllib.request, "urlopen", return_value=response) as open_url:
            self.assertEqual(client.danbooru_json("/wiki_pages/cat.json", {}), {"id": 123})
            wiki_request = open_url.call_args.args[0]
            self.assertEqual(wiki_request.full_url, "https://betabooru.donmai.us/wiki_pages/cat.json")
            self.assertTrue(wiki_request.get_header("Authorization").startswith("Basic "))
            self.assertEqual(pipeline.request_json("/posts.json", {"md5": "abc"}, "user", "key", 0), {"id": 123})
            post_request = open_url.call_args.args[0]
            self.assertEqual(post_request.full_url, "https://betabooru.donmai.us/posts.json?md5=abc")
            self.assertTrue(post_request.get_header("Authorization").startswith("Basic "))
        self.assertEqual(client.DANBOORU_POST_URL_PREFIX, "https://danbooru.donmai.us/posts/")
        self.assertEqual(pipeline.DANBOORU_ROOT, "https://danbooru.donmai.us")

    def test_credential_check_uses_selected_host(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"name": "user", "id": 42}'
        with patch.object(tool_routes, "get_api_base_url", return_value="https://betabooru.donmai.us"), \
             patch.object(tool_routes, "effective_credentials", return_value=("user", "key", "saved")), \
             patch.object(tool_routes.urllib.request, "urlopen", return_value=response) as open_url:
            self.assertEqual(tool_routes.check_danbooru_credentials()["user_id"], 42)
        self.assertEqual(open_url.call_args.args[0].full_url, "https://betabooru.donmai.us/profile.json")

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

    def test_filename_md5_lookup_does_not_read_media_before_the_request(self):
        name = "__amamiya_ren_akechi_goro_joker_arsene_and_crow_persona_and_2_more_drawn_by_doran_doran7280__88a41d15221a8e9536d94b7c1b6c665a.jpg"
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / name
            media.write_bytes(b"synthetic test bytes, not the user's image")
            with patch.object(pipeline, "md5_file", side_effect=AssertionError("media was opened")), \
                 patch.object(pipeline, "request_json", return_value={"id": 123}) as request:
                post, matched_by, digest = pipeline.find_post_by_md5(media, None, None, 0, 0)
        self.assertEqual(post, {"id": 123})
        self.assertEqual(matched_by, "filename_md5")
        self.assertEqual(digest, "88a41d15221a8e9536d94b7c1b6c665a")
        self.assertEqual(request.call_args.args[0], "/posts.json")
        self.assertEqual(request.call_args.args[1]["md5"], digest)

    def test_filename_md5_reset_does_not_fall_through_to_a_false_miss(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "__sample__88a41d15221a8e9536d94b7c1b6c665a.jpg"
            media.write_bytes(b"synthetic bytes")
            with patch.object(pipeline, "md5_file", side_effect=AssertionError("media was opened")), \
                 patch.object(pipeline, "request_json", side_effect=urllib.error.URLError("reset")):
                with self.assertRaises(urllib.error.URLError):
                    pipeline.find_post_by_md5(media, None, None, 0, 0)


if __name__ == "__main__":
    unittest.main()
