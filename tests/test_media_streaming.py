"""Metadata and conditional GET never retrieve the media blob."""
from unittest import TestCase
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

from project_docs import http, repository as repo


class MediaStreamingTests(TestCase):
    def test_metadata_query_selects_only_type_and_size(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("video/mp4", 67108864)
        self.assertEqual(repo.get_asset_meta(conn, "film", "pa_" + "a" * 32), ("video/mp4", 67108864))
        sql, parameters = cursor.execute.call_args.args
        self.assertEqual(sql.split(" FROM ")[0], "SELECT content_type, byte_size")
        self.assertEqual(parameters, ("film", "pa_" + "a" * 32))
        cursor.fetchone.return_value = None
        self.assertIsNone(repo.get_asset_meta(conn, "film", "missing"))

    def request(self, suffix="", headers=None, exists=True):
        handler, conn = MagicMock(), MagicMock()
        handler.headers = headers or {}
        handler.project_docs_identity.return_value = ({"actor_id": "test", "name": "Director",
            "role": "admin", "status": "active", "directory_registered": True}, None)
        with patch.object(http, "open_connection", return_value=conn), patch.object(http, "_ensure_schema"), \
                patch.object(repo, "get_asset_meta", return_value=("video/mp4", 64000) if exists else None) as meta, \
                patch.object(repo, "get_asset", return_value=("video/mp4", b"movie")) as blob:
            http._api(handler, urlparse("/projects/api/film/assets/pa_" + "a" * 32 + suffix), "GET")
        return handler, meta, blob, conn

    def test_meta_uses_zero_blob_lookup(self):
        handler, meta, blob, conn = self.request("/meta")
        handler.send_json.assert_called_once_with(200, {"content_type": "video/mp4", "bytes": 64000})
        meta.assert_called_once()
        blob.assert_not_called()
        conn.rollback.assert_called_once()

    def test_matching_etag_checks_existence_without_blob(self):
        etag = '"pa_' + 'a' * 32 + '"'
        for header in (etag, "W/" + etag, '"other", ' + etag, "*"):
            with self.subTest(header=header):
                handler, meta, blob, conn = self.request(headers={"If-None-Match": header})
                handler.send_response.assert_called_once_with(304)
                handler.send_header.assert_any_call("ETag", etag)
                handler.send_header.assert_any_call("Cache-Control", "private, max-age=31536000, immutable")
                handler.send_skillops_bytes.assert_not_called()
                handler.wfile.write.assert_not_called()
                blob.assert_not_called()
                meta.assert_called_once()
                conn.close.assert_called_once()

    def test_missing_etag_asset_returns_404_and_mismatch_reads_normally(self):
        handler, _, blob, _ = self.request(headers={"If-None-Match": "*"}, exists=False)
        handler.send_json.assert_called_once_with(404, {"error": "Media not found."})
        blob.assert_not_called()
        handler, meta, blob, _ = self.request(headers={"If-None-Match": '"pa_' + 'a' * 32 + 'extra"'})
        meta.assert_not_called()
        blob.assert_called_once()
        handler.send_skillops_bytes.assert_called_once()
