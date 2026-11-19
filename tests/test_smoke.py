"""배포 전 점검: 서버를 이 프로세스 안에서 띄워(수집·인터넷 없이) 주요 화면·API가 200으로 열리는지 확인.
실행: python -m unittest discover -s tests"""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker import chat, maint, matchinfo, player_extra, share  # noqa: E402
from tracker.core import init_db  # noqa: E402
from tracker.web import server  # noqa: E402

PAGES = ["/lck", "/lck/roster", "/lck/fa", "/lck/schedule", "/lck/results", "/lck/stove", "/lck/teams", "/lpl/results", "/lck/builder", "/lck/game", "/lpl", "/lpl/schedule", "/lec/schedule", "/cblol/roster",
         "/lck?team=t1", "/lck?q=faker", "/lck?hot=0&src=news"]
APIS = ["/api/items", "/api/people", "/api/schedule", "/api/schedule?league=lpl", "/api/status", "/api/chat", "/healthz"]


class SmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        for m in (chat, player_extra, maint, share, matchinfo):
            m.init()
        server.load_static()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=10) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def test_pages(self):
        for p in PAGES:
            with self.subTest(p):
                code, body = self.get(p)
                self.assertEqual(code, 200)
                self.assertIn("</html>", body)
                self.assertNotIn("{{ORIGIN}}", body)

    def test_apis(self):
        for p in APIS:
            with self.subTest(p):
                code, body = self.get(p)
                self.assertEqual(code, 200)
                if p != "/healthz":
                    json.loads(body)

    def test_static_files(self):
        for name in server.STATIC:
            with self.subTest(name):
                self.assertEqual(self.get(f"/static/{name}")[0], 200)

    def test_diag(self):
        code, body = self.get("/api/diag")
        self.assertEqual(code, 200)
        d = json.loads(body)
        for k in ("uptime_min", "leaguepedia_last_hour", "recent_warnings", "schedule", "logos", "collectors"):
            self.assertIn(k, d)

    def test_match_api_only_known_matches(self):
        self.assertEqual(self.get("/api/match?league=lck&id=nope")[0], 404)
        self.assertEqual(self.get("/api/match?league=zzz&id=x")[0], 404)

    def test_news_default_view_is_all(self):
        import re
        body = self.get("/lck")[1]
        on = re.search(r'<nav class="view_tab"[^>]*>(.*?)</nav>', body, re.S).group(1)
        self.assertRegex(on, r'class="on" href="/lck"[^>]*>전체<')               # 기본: 전체, 주소에 hot 없음
        self.assertIn('href="/lck?hot=1"', on)                                   # 오피셜은 hot=1
        self.assertRegex(self.get("/lck?hot=1")[1], r'class="on" href="/lck\?hot=1"[^>]*>오피셜<')

    def test_root_redirects_and_404(self):
        self.assertEqual(self.get("/")[0], 200)          # /lck 로 넘어감
        self.assertEqual(self.get("/nope/nope/nope")[0], 404)
        self.assertEqual(self.get("/tlogo/unknown-team")[0], 404)
        self.assertEqual(self.get("/tlogo/..%2F..%2Fetc%2Fpasswd")[0], 404)


if __name__ == "__main__":
    unittest.main()
