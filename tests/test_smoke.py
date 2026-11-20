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

from tracker import chat, farm, maint, matchinfo, player_extra, share, vote  # noqa: E402
from tracker.core import init_db  # noqa: E402
from tracker.web import server  # noqa: E402

PAGES = ["/lck", "/lck/roster", "/lck/fa", "/lck/summary", "/lck/predict", "/lck/contracts", "/lck/teams", "/lck/schedule", "/lck/results", "/lck/stove", "/lck/teams", "/lpl/results", "/lck/builder", "/lck/game", "/lpl", "/lpl/schedule", "/lec/schedule", "/cblol/roster",
         "/lck?team=t1", "/lck?q=faker", "/lck?hot=0&src=news"]
APIS = ["/api/farm", "/api/farm?ids=rm:x:t1:m", "/api/votes", "/api/items", "/api/people", "/api/schedule", "/api/schedule?league=lpl", "/api/status", "/api/chat", "/healthz"]


class SmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        for m in (chat, player_extra, maint, share, matchinfo, vote, farm):
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

    def test_next_season_preview(self):
        # 스토브리그 기간: '다음 시즌 · 예정' 세 화면(개막 준비·시즌·팀)이 열리고, 스토브리그 메뉴는 지금 시즌으로 넘김
        from datetime import datetime
        from tracker.archive import current_season
        from tracker.config import KST
        from tracker.web import views
        if not views.stove_phase(datetime.now(KST).date()):
            self.skipTest("스토브리그 기간에만 있는 화면")
        y = current_season()
        for p in ("/lck", "/lck/schedule", "/lck/results", "/lck/roster"):
            with self.subTest(p):
                code, body = self.get(f"{p}?season={y}")
                self.assertEqual(code, 200)
                self.assertIn(f"<b>{y} 시즌</b>", body)
                self.assertIn("아직 개막 전", body)
        code, body = self.get(f"/lck?season={y}")
        self.assertIn('class="pv5"', body)
        code, _ = self.get(f"/lck/predict?season={y}")
        self.assertIn(code, (200, 301, 302, 303))

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
        self.assertRegex(self.get("/lck?hot=2")[1], r'class="on" href="/lck\?hot=2"[^>]*>스토브리그<')   # 이동·계약 소식만
        self.assertRegex(self.get("/lck?cat=stove")[1], r'class="on" href="/lck\?hot=2"')                    # ?cat=stove 도 같은 보기

    def test_community_posts(self):
        # 인벤 게시판 글: '오피셜' 대신 '커뮤니티' 배지, 오피셜 보기·'뉴스만'에서는 빠짐
        from datetime import datetime, timezone
        from tracker.core import save
        t = "[잡담] 롤) 폭스 탑라이너 타나토스 합류"
        save([{"id": "news:talk1", "team": "lck", "source": "news", "title": t, "url": "https://example.com/t",
               "outlet": "인벤", "published": datetime.now(timezone.utc).isoformat()}])
        body = self.get("/lck?team=all")[1]
        self.assertRegex(body, r'<span class="kb k-talk">커뮤니티</span>\[잡담\] 롤\) 폭스')
        self.assertNotIn("폭스 탑라이너", self.get("/lck?team=all&hot=1")[1])
        self.assertNotIn("폭스 탑라이너", self.get("/lck?team=all&src=news")[1])

    def test_ended_season_is_not_a_record(self):
        # 스토브리그 기간: 방금 끝난 시즌(2026)은 '기록'이 아니라 지금 화면 → 시즌 고르기에 2026이 두 번 나오면 안 됨
        from datetime import datetime
        import re as _re
        from tracker.archive import current_season
        from tracker.config import KST
        from tracker.web import views
        if not views.stove_phase(datetime.now(KST).date()):
            self.skipTest("스토브리그 기간에만")
        ended = current_season() - 1
        for p in ("/lck", "/lck/fa", "/lck/roster", "/lck/schedule", "/lck/results"):
            with self.subTest(p):
                code, body = self.get(f"{p}?season={ended}")          # 예전 주소로 와도 지금 화면으로
                self.assertEqual(code, 200)
                sel = _re.search(r'<details class="lgsel ssel">.*?</details>', body, _re.S).group(0)
                years = _re.findall(r">(\d{4}) 시즌<small>", sel)
                self.assertEqual(len(years), len(set(years)), years)
                self.assertNotIn("기록을 보고 있어요", body)
        code, body = self.get(f"/lck/roster?final={ended}")            # 그 시즌 최종 로스터는 '팀' 안의 탭으로
        self.assertEqual(code, 200)
        self.assertIn(f"{ended} 시즌 로스터", body)
        self.assertNotIn("기록을 보고 있어요", body)

    def test_farm_drawn_in_first_html(self):
        # 독버섯 심기: 자바스크립트 없이도 첫 HTML에 상태바(빈 밭 7칸)와 판 목록 데이터가 있어야 함(화면 밀림 방지·검색봇)
        code, body = self.get("/lck")
        self.assertEqual(code, 200)
        self.assertIn('class="card tf-bar"', body)
        import re as _re
        field = _re.search(r'<div class="tf-field"[^>]*>(.*?)</div>', body, _re.S).group(1)
        self.assertEqual(field.count('class="tf-plot'), 7)
        self.assertIn('id="tf-data"', body)
        self.assertNotIn('class="card tf-bar"', self.get("/lck?q=faker")[1])     # 검색 결과 화면엔 없음

    def test_root_redirects_and_404(self):
        self.assertEqual(self.get("/")[0], 200)          # /lck 로 넘어감
        self.assertEqual(self.get("/nope/nope/nope")[0], 404)
        self.assertEqual(self.get("/tlogo/unknown-team")[0], 404)
        self.assertEqual(self.get("/tlogo/..%2F..%2Fetc%2Fpasswd")[0], 404)


if __name__ == "__main__":
    unittest.main()
