"""Controller dashboard and remote Google sign-in API checks; no Docker daemon needed."""
import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server


class DashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.TOKEN = "dashboard-test-token"
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def get(self, path, token=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            with urlopen(Request(self.base + path, headers=headers), timeout=5) as response:
                return response.status, response.headers, response.read()
        except HTTPError as response:
            with response:
                return response.code, response.headers, response.read()

    def test_dashboard_files_are_available_without_token_but_api_is_not(self):
        for path, content_type in (("/", "text/html"), ("/dashboard.js", "text/javascript"),
                                   ("/dashboard.css", "text/css")):
            status, headers, body = self.get(path)
            self.assertEqual(status, 200)
            self.assertIn(content_type, headers["Content-Type"])
            self.assertTrue(body)
            self.assertEqual(headers["Cache-Control"], "no-store")
        for path in ("/jamies", "/logins"):
            status, _, _ = self.get(path)
            self.assertEqual(status, 401)

    def test_login_screen_uses_advertised_server_address(self):
        fake = {"Config": {"Labels": {"jamie.login": "second"}},
                "NetworkSettings": {"Ports": {"6080/tcp": [{"HostPort": "49153"}]}}}

        def docker(*args):
            if args[0] == "ps":
                self.assertIn("label=jamie.login", args)
                return "login-container"
            self.assertEqual(args, ("inspect", "login-container"))
            return json.dumps([fake])

        with patch.object(server, "docker", side_effect=docker), patch.object(server, "HOST", "100.101.102.103"):
            status, _, body = self.get("/logins", server.TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), [{"account": "second", "screen":
                                             "http://100.101.102.103:49153/vnc.html"}])


if __name__ == "__main__":
    unittest.main()
