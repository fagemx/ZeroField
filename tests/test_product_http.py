"""Real HTTP + PostgreSQL acceptance for authentication and file handoff."""
from http.client import HTTPConnection
import io
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import test_execution as execution_fixture
from test_file_handoff import workbook_bytes
from project_docs import repository as repo, http
from server import OpenBenchHandler


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for HTTP tests")
class ProductHTTPTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        execution_fixture.PostgreSQLExecutionTests.setUp(self)
        self.conn.commit()
        self.member_token = "test-member-token-" + self.actor
        self.env = patch.dict(os.environ, {"OPENBENCH_AUTH_MODE": "token", "OPENBENCH_TOKENS": json.dumps({self.member_token: self.actor})})
        self.env.start()
        self.factory = patch.object(http, "_CONN_FACTORY", lambda: psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"]))
        self.factory.start()
        class Handler(OpenBenchHandler):
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.factory.stop()
        self.env.stop()
        execution_fixture.PostgreSQLExecutionTests.tearDown(self)

    def request(self, path, *, method="GET", data=None, raw=None, headers=None, authenticated=True):
        sent = {"X-Requested-With": "projects"}
        if authenticated:
            sent["Authorization"] = "Bearer " + self.member_token
        if data is not None:
            raw = json.dumps(data).encode()
            sent["Content-Type"] = "application/json"
        sent.update(headers or {})
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            connection.request(method, path, body=raw, headers=sent)
            response = connection.getresponse()
            payload, response_headers = response.read(), dict(response.getheaders())
            if "application/json" in response_headers.get("Content-Type", ""):
                payload = json.loads(payload)
            return response.status, payload, response_headers
        finally:
            connection.close()

    def test_token_cookie_viewer_and_member_enforcement(self):
        path = f"/projects/api/{self.slug}"
        self.assertEqual(self.request(path, authenticated=False)[0], 401)
        self.assertEqual(self.request(path, authenticated=False, headers={"X-OpenBench-Actor": self.actor, "Cookie": "openbench_actor=" + self.actor})[0], 401)
        self.assertEqual(self.request("/__who")[0], 404)
        self.assertEqual(self.request(path)[0], 200)
        code, _, headers = self.request("/login", method="POST", raw=("token=" + self.member_token).encode(), authenticated=False, headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(code, 303)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertEqual(self.request(path, authenticated=False, headers={"Cookie": headers["Set-Cookie"].split(";")[0]})[0], 200)
        self.assertEqual(self.request("/projects/api/members")[0], 200)
        repo.upsert_member(self.conn, self.actor, "Read only test", "viewer")
        self.conn.commit()
        self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(self.request("/projects/api/members")[0], 403)
        self.assertEqual(self.request(f"{path}/tabs/shots/table-edit", method="POST", data={})[0], 403)
        self.assertEqual(self.request("/projects/api/limbs/register", method="POST", data={})[0], 403)
        repo.upsert_member(self.conn, self.actor, "Read only test", "viewer", status="inactive")
        self.conn.commit()
        self.assertEqual(self.request(path)[0], 403)

    def test_office_import_patch_export_and_stale_reimport(self):
        import openpyxl
        base = f"/projects/api/{self.slug}"
        raw = workbook_bytes()
        upload = {"X-File-Name": "shots.xlsx", "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
        code, payload, _ = self.request(base + "/tabs/import", method="POST", raw=raw, headers=upload)
        self.assertEqual(code, 200, payload)
        tab = payload["tab"]
        self.assertNotIn("source_blob", tab)
        export = base + f"/tabs/{tab['key']}/export?format=xlsx"
        self.assertEqual(self.request(export)[1], raw)
        row = tab["doc"]["content"][0]["content"][1]
        edit = {"base_revision": tab["revision"], "row_edits": [{"row_id": row["attrs"]["bid"], "cells": {"1": "4800"}}]}
        code, edited, _ = self.request(base + f"/tabs/{tab['key']}/table-edit", method="POST", data=edit)
        self.assertEqual(code, 200, edited)
        output = self.request(export)[1]
        book = openpyxl.load_workbook(io.BytesIO(output))
        self.assertEqual(book["Shots"]["B2"].value, 4800)
        self.assertEqual(book["Shots"]["C2"].value, "=B2*2")
        self.assertTrue(book["Shots"]["B2"].font.bold)
        reimport = base + f"/tabs/import?tab_key={tab['key']}&base_revision={tab['revision']}"
        self.assertEqual(self.request(reimport, method="POST", raw=raw, headers=upload)[0], 409)
        reimport = base + f"/tabs/import?tab_key={tab['key']}&base_revision={edited['revision']}&confirm_replace=true"
        code, updated, _ = self.request(reimport, method="POST", raw=raw, headers=upload)
        self.assertEqual(code, 200, updated)
        self.assertTrue(updated["changes"])
        self.assertEqual(updated["tab"]["doc"]["content"][0]["content"][1]["attrs"]["bid"], row["attrs"]["bid"])

    def test_header_auth_requires_proxy_secret_and_same_origin_writes(self):
        path = f"/projects/api/{self.slug}"
        secret = "test-proxy-secret-at-least-24-characters"
        with patch.dict(os.environ, {"OPENBENCH_AUTH_MODE": "header", "OPENBENCH_HEADER_SECRET": secret}):
            headers = {"X-OpenBench-Actor": self.actor}
            self.assertEqual(self.request(path, authenticated=False, headers=headers)[0], 401)
            headers["X-OpenBench-Proxy-Secret"] = secret
            self.assertEqual(self.request(path, authenticated=False, headers=headers)[0], 200)
            headers["Origin"] = "https://foreign.invalid"
            self.assertEqual(self.request(path + "/tabs/shots/table-edit", method="POST", data={}, authenticated=False, headers=headers)[0], 403)

    def test_audio_upload_metadata_and_partial_playback(self):
        import wave
        stream = io.BytesIO()
        with wave.open(stream, "wb") as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
            audio.writeframes(b"\0\0" * 8000)
        raw = stream.getvalue()
        code, uploaded, _ = self.request(f"/projects/api/{self.slug}/assets", method="POST", raw=raw, headers={"Content-Type": "audio/wav"})
        self.assertEqual(code, 200, uploaded)
        code, metadata, _ = self.request(uploaded["src"] + "/meta")
        self.assertEqual((code, metadata["content_type"], metadata["bytes"]), (200, "audio/wav", len(raw)))
        code, body, headers = self.request(uploaded["src"], headers={"Range": "bytes=0-43"})
        self.assertEqual((code, body), (206, raw[:44]))
        self.assertEqual(headers["Content-Range"], f"bytes 0-43/{len(raw)}")


if __name__ == "__main__":
    unittest.main()
