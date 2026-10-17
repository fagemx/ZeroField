import unittest
from project_docs import auth

ACTOR = "11111111-1111-4111-8111-111111111111"
TOKEN = "a-test-token-with-at-least-24-characters"


class AuthTests(unittest.TestCase):
    def cfg(self):
        return auth.config({"OPENBENCH_AUTH_MODE": "token", "OPENBENCH_TOKENS": '{"' + TOKEN + '":"' + ACTOR + '"}'})

    def test_token_never_accepts_dev_identity(self):
        self.assertIsNone(auth.resolve({"X-OpenBench-Actor": ACTOR}, {"openbench_actor": ACTOR}, self.cfg(), ACTOR))
        self.assertEqual(auth.resolve({"Authorization": "Bearer " + TOKEN}, {}, self.cfg()), ACTOR)
        self.assertIsNone(auth.resolve({"Authorization": "Bearer wrong"}, {}, self.cfg()))

    def test_cookie_signature_expiry_and_revocation(self):
        cfg = self.cfg()
        cookie = auth.issue_session(ACTOR, cfg, 100)
        self.assertEqual(auth.session_actor(cookie, cfg, 200), ACTOR)
        self.assertIsNone(auth.session_actor(cookie + "a", cfg, 200))
        self.assertIsNone(auth.session_actor(cookie, cfg, 100 + auth.SESSION_SECONDS))
        self.assertIsNone(auth.session_actor(cookie, cfg, 99))
        cfg["tokens"] = {}
        self.assertIsNone(auth.session_actor(cookie, cfg, 200))

    def test_header_requires_proxy_secret(self):
        cfg = auth.config({"OPENBENCH_AUTH_MODE": "header", "OPENBENCH_HEADER_SECRET": TOKEN})
        self.assertIsNone(auth.resolve({"X-OpenBench-Actor": ACTOR}, {}, cfg))
        self.assertEqual(auth.resolve({"X-OpenBench-Actor": ACTOR, "X-OpenBench-Proxy-Secret": TOKEN}, {}, cfg), ACTOR)

    def test_bad_configuration_fails_closed(self):
        for env in ({"OPENBENCH_AUTH_MODE": "oops"}, {"OPENBENCH_AUTH_MODE": "token"}, {"OPENBENCH_AUTH_MODE": "header"}):
            with self.assertRaises(auth.AuthError):
                auth.config(env)

    def test_http_server_does_not_silently_share_an_existing_port(self):
        from server import OpenBenchHTTPServer, OpenBenchHandler
        first = OpenBenchHTTPServer(("127.0.0.1", 0), OpenBenchHandler)
        try:
            with self.assertRaises(OSError):
                duplicate = OpenBenchHTTPServer(("127.0.0.1", first.server_port), OpenBenchHandler)
                duplicate.server_close()
        finally:
            first.server_close()


if __name__ == "__main__":
    unittest.main()
