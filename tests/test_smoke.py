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
         "/lck?team=t1", "/lck?q=faker", "/lck?hot=0&src=news", "/worlds", "/worlds/schedule", "/worlds/results", "/worlds/teams",
         "/worlds/fa", "/fst/schedule", "/msi/results", "/ewc/teams", "/msi"]
APIS = ["/api/farm", "/api/farm?ids=rm:x:t1:m", "/api/items", "/api/people", "/api/schedule", "/api/schedule?league=lpl", "/api/status", "/api/chat", "/healthz"]


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

    def test_fa_official_news_is_confirmed(self):
        # 리그피디아엔 아직 미정인데 오피셜 기사가 나온 사람: '잔류 발표'·'잔류?'가 아니라 그냥 잔류(이적이면 이적 확정)로,
        # 위 숫자 칸·팀별 화면도 같게. 기사 추측(유력)은 '유력' 칸(미정 중)에 따로
        from unittest import mock
        from tracker.core import db
        from tracker.web import views
        rows = [("BonX", "BonX", "김기범", "ns", "Coach", "fa"), ("MovX", "MovX", "", "t1", "Mid", "fa"),
                ("GusX", "GusX", "", "kt", "Bot", "fa"), ("NoX", "NoX", "", "dk", "Top", "fa")]
        with db() as c:
            for r in rows:
                c.execute("INSERT OR REPLACE INTO fa(page,nick,real,team_from,role,status,team_to,team_to_name,until,date,memo) "
                          "VALUES(?,?,?,?,?,?,'','','','2026-11-18','')", r)
        rm = lambda team, stay, off: {"team": team, "stay": stay, "official": off, "title": "t", "url": "https://e.com", "outlet": "인벤",
                                      "published": "2026-11-18T01:00:00+00:00"}
        fake = {"BonX": rm("ns", True, True), "MovX": rm("hle", False, True), "GusX": rm("geng", False, False)}
        try:
            with mock.patch.object(views, "rumors", return_value=fake):
                html = views.render_fa("lck")
                row = lambda pg: html.split(f'class="fa-row" data-page="{pg}"')[1].split("</li>")[0]
                self.assertIn('data-s="stay"', row("BonX"))
                self.assertIn('<span class="st2 s-stay">잔류</span>', row("BonX"))
                self.assertNotIn("잔류?", row("BonX"))
                self.assertNotIn("발표", html.split('id="falist"')[1])
                self.assertIn('data-s="move"', row("MovX"))
                self.assertIn('data-s="fa" data-rm=1', row("GusX"))
                self.assertIn('<span class="st2 s-rm">유력</span>', row("GusX"))
                self.assertIn('data-s="fa" data-p', row("NoX"))
                self.assertRegex(html, r'data-s="rm"><b>1</b>유력')
        finally:
            with db() as c:
                c.execute("DELETE FROM fa WHERE page IN ('BonX','MovX','GusX','NoX')")

    def test_roster_card_official_news_fills_slot(self):
        # 리그피디아엔 빈자리지만 오피셜 기사로 잔류가 확정된 감독(bon0): 빗금·'잔류 발표'가 아니라 채운 칸 + '잔류'
        from unittest import mock
        from tracker.web import views
        rm = {"team": "ns", "stay": True, "official": True, "title": "[오피셜] 농심, 본 감독 재계약", "url": "u", "outlet": "인벤",
              "published": "2026-11-18T01:00:00+00:00"}
        guess = {**rm, "official": False, "stay": False, "team": "ns", "title": "농심행 유력"}
        x = {"page": "Bon0", "nick": "bon0", "real": "", "role": "Head Coach", "until": "", "joined": 0, "rm": rm, "pos": "감독"}
        cx = {"page": "CoX", "nick": "CoX", "real": "", "role": "Coach", "until": "", "joined": 0, "rm": rm, "pos": "코치"}
        g = {"page": "Gx", "nick": "Gx", "real": "", "role": "Top", "until": "", "joined": 0, "rm": guess, "pos": "탑"}
        with mock.patch.object(views, "rumor_slots", return_value={"ns": {"Head Coach": [x], "Top": [g]}}), \
             mock.patch.object(views, "roster_leaving", return_value={}):
            card = views.roster_card("ns", [])
        coach = card.split('data-page="Bon0"')[0].rsplit("<li", 1)[1]
        self.assertNotIn("vac", coach)
        self.assertIn('class="in stay"', card)
        self.assertNotIn("발표", card)
        self.assertIn('<li class="vac rmv"><span class="pk">탑</span>', card)        # 기사 추측은 그대로 빈자리 + 유력
        self.assertIn(">0/5<", card)
        # 코치는 감독 칸을 채우지 않음(칸은 빈자리 그대로, 이름은 아래 줄에 '잔류')
        with mock.patch.object(views, "rumor_slots", return_value={"ns": {"Head Coach": [cx]}}), \
             mock.patch.object(views, "roster_leaving", return_value={}):
            card = views.roster_card("ns", [])
        cell = card.split('data-page="CoX"')[0].rsplit("<li", 1)[1]
        self.assertIn("vac", cell)
        self.assertIn('class="in s stay"', card)

    def test_roster_complete_mark(self):
        # 주전 5명 + 감독이 다 있으면 'n/5' 대신 '로스터 완성 ✓', 한 자리라도 비면 그대로 n/5
        from tracker.web import views
        def row(role, nick):
            return {"team": "dns", "role": role, "page": nick, "nick": nick, "real": "", "until": "", "joined": 0}
        full = [row(r, n) for r, n in zip(views.ROSTER_SLOTS, ("DuDu", "Cuzz", "Ucal", "deokdam", "Bluffing", "Ggoong"))]
        self.assertTrue(views.roster_complete("dns", full))
        self.assertIn("로스터 완성", views.roster_card("dns", full))
        no_coach = full[:-1]
        self.assertFalse(views.roster_complete("dns", no_coach))
        card = views.roster_card("dns", no_coach)
        self.assertNotIn("로스터 완성", card)
        self.assertIn(">5/5<", card)
        self.assertNotIn("로스터 완성", views.roster_card("dns", full, rm=False))       # 지난 시즌 기록에는 안 붙임

    def test_predict_is_off(self):
        # 행선지 맞히기는 잠시 쉼: 메뉴에 없고, 예전 주소는 팀별로, 투표 API는 404. 켜면 다시 보임
        from unittest import mock
        from tracker.config import FEATURES
        from tracker.web import views
        self.assertFalse(FEATURES["predict"])
        code, body = self.get("/lck/summary")
        self.assertNotIn("행선지 맞히기", body)
        self.assertNotIn('href="/lck/predict"', body)
        code, body = self.get("/lck/predict")
        self.assertEqual(code, 200)
        self.assertIn('class="sgrid"', body)                                  # 팀별 화면으로 옮겨 감
        self.assertEqual(self.get("/api/votes")[0], 404)
        with mock.patch.dict(FEATURES, {"predict": True}):
            self.assertIn("행선지 맞히기", views.stove_toggle("lck", "summary"))
            self.assertEqual(self.get("/api/votes")[0], 200)

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

    def test_community_chatter_hidden(self):
        # LCK와 상관없는 커뮤니티 수다는 소식에 안 나옴(이적·팀·선수 이야기는 남음)
        from datetime import datetime, timezone
        from tracker.core import save
        now = datetime.now(timezone.utc).isoformat()
        save([{"id": "news:talk2", "team": "lck", "source": "news", "title": "[잡담] 롤 패치 너무 별로 아이템 다 너프", "url": "https://example.com/t2",
               "outlet": "인벤", "published": now},
              {"id": "news:talk3", "team": "lck", "source": "news", "title": "슼피셜)롤 GENG 서폿 클라우드 합류", "url": "https://example.com/t3",
               "outlet": "에펨코리아", "published": now}])
        body = self.get("/lck?team=all")[1]
        self.assertNotIn("패치 너무 별로", body)
        self.assertRegex(body, r'<span class="kb k-talk">커뮤니티</span>슼피셜\)롤 GENG')

    def test_summary_labels_and_no_double_row(self):
        # 스토브리그 팀별: 명사 라벨(영입·이탈·재계약·이적설·미정), 이적설에 잡힌 선수는 같은 카드 '미정'에 또 안 나옴
        from unittest import mock
        from tracker.web import views
        sm = {k: {"in": [], "out": [], "stay": [], "open": [], "updated": ""} for k in views.team_keys()}
        sm["hle"] = {"in": [{"page": "Zeka", "nick": "Zeka", "role": "Mid", "date": "", "from": ""}],
                     "out": [{"page": "Doran", "nick": "Doran", "role": "Top", "date": "", "to": "t1"}],
                     "stay": [], "open": [{"page": "Kiin", "nick": "Kiin", "role": "Top", "date": ""},
                                          {"page": "Delight", "nick": "Delight", "role": "Support", "date": ""}], "updated": ""}
        rm = {"team": "hle", "stay": False, "outlet": "OSEN", "title": "기인 HLE 유력"}
        with mock.patch.object(views.stv, "team_summary", return_value=sm), \
             mock.patch.object(views, "rumor_slots", return_value={"hle": {"top": [{"page": "Kiin", "nick": "Kiin", "role": "Top", "rm": rm, "pos": "탑"}]}}):
            html = views.render_summary("lck")
        card = html[html.index('id="m-hle"'):].split("</article>")[0]
        labels = __import__("re").findall(r"<em>(.*?)</em>", card)
        self.assertEqual(labels, ["영입", "이탈", "이적설", "미정"])
        self.assertEqual(card.count(">Kiin<"), 1)                       # 이적설에만
        self.assertIn(">Delight<", card)
        for old in ("들어옴", "나감", "<em>소문</em>"):
            self.assertNotIn(old, html)

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
