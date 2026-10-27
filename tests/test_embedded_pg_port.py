"""Embedded development database: a taken default port does not stop the launcher (SPEC_20 A17)."""
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

import server


class _Done:
    def __init__(self, code):
        self.returncode = code


class EmbeddedPortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / "pg"
        self.data.mkdir()
        (self.data / "PG_VERSION").write_text("16", encoding="utf-8")
        self.calls = []

    def _start(self, status_code, env, free=lambda port: True):
        def run(args, **kwargs):
            self.calls.append(args)
            return _Done(status_code if args[-1] == "status" else 0)
        with patch.dict(os.environ, {"OPENBENCH_PG_DATA": str(self.data), **env}, clear=False), \
                patch.object(server, "_find_pg_bin", return_value=Path("pgbin")), \
                patch.object(server, "_loopback_port_free", side_effect=free), \
                patch("subprocess.run", side_effect=run):
            if "OPENBENCH_PG_PORT" not in env:
                os.environ.pop("OPENBENCH_PG_PORT", None)
            uri, _cleanup = server._start_local_postgres()
        return uri

    def _start_args(self):
        return next(args for args in self.calls if args[-1] == "start")

    def test_default_port_is_used_when_free(self):
        uri = self._start(3, {})
        self.assertEqual(uri, "postgresql://postgres@127.0.0.1:55432/postgres")
        self.assertIn("-p 55432 -h 127.0.0.1", self._start_args())

    def test_taken_default_port_moves_to_the_next_free_port(self):
        uri = self._start(3, {}, free=lambda port: port >= 55435)
        self.assertEqual(uri, "postgresql://postgres@127.0.0.1:55435/postgres")
        self.assertIn("-p 55435 -h 127.0.0.1", self._start_args())

    def test_configured_port_is_kept_even_when_taken(self):
        uri = self._start(3, {"OPENBENCH_PG_PORT": "55999"}, free=lambda port: False)
        self.assertEqual(uri, "postgresql://postgres@127.0.0.1:55999/postgres")
        self.assertIn("-p 55999 -h 127.0.0.1", self._start_args())

    def test_running_cluster_is_reached_on_its_recorded_port(self):
        (self.data / "postmaster.pid").write_text("123\n" + str(self.data) + "\n1700000000\n55437\n\n127.0.0.1\n", encoding="utf-8")
        uri = self._start(0, {}, free=lambda port: False)
        self.assertEqual(uri, "postgresql://postgres@127.0.0.1:55437/postgres")
        self.assertFalse([args for args in self.calls if args[-1] == "start"])

    def test_port_probe_sees_a_listening_socket(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            port = held.getsockname()[1]
            self.assertFalse(server._loopback_port_free(port))
            self.assertNotEqual(server._free_loopback_port(port), port)


if __name__ == "__main__":
    unittest.main()
