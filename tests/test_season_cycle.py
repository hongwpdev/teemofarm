"""해가 바뀌어도 같은 규칙으로 도는지: 2027·2028·2029년을 차례로 '그날'로 맞춰 놓고 실제 코드(화면·서버·독버섯·검색어)를 돌려 봄.
연도는 하드코딩하지 않고 YEARS만 바꾸면 됨. 시계는 모듈 안의 datetime만 바꿔 끼우고(운영 DB·실제 시계는 안 건드림), DB는 임시 파일.
실행: python -m unittest tests.test_season_cycle -v  (pytest로도 돎)"""
import os
import re
import tempfile
import threading
import unittest
import urllib.request
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from unittest import mock

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker import archive, farm, news, schedule  # noqa: E402
from tracker.config import KST  # noqa: E402
from tracker.core import db, init_db  # noqa: E402
from tracker.web import server, views  # noqa: E402

YEARS = (2027, 2028, 2029)
UTC = timezone.utc


def _m(mid, page, tour, at, k1, t1, k2, t2, win="", tab="Week 1", playoff=False):
    return {"id": mid, "page": page, "tour": tour, "playoff": playoff, "tab": tab, "at": at, "bo": "3",
            "t1": t1, "k1": k1, "t2": t2, "k2": k2, "s1": "", "s2": "", "win": win, "ff": ""}


def season_data(y: int) -> dict:
    """y년 시즌 하나를 둘러싼 일정: 지난 시즌(y-1) 결승 · y년 LCK 컵(1/15 첫 경기, 1/25 다음 경기) · y년 MSI(LCK 팀 경기 1, 아닌 경기 1)."""
    p = y - 1
    lck = {"season": y, "at": f"{y}-01-01T00:00:00+00:00", "standings": {},
           "matches": [_m(f"lck{p}fin", f"LCK/{p} Season/Season Playoffs", f"LCK {p} Season Playoffs", f"{p}-09-13 08:00:00",
                          "geng", "Gen.G", "hle", "Hanwha Life Esports", "1", "Finals", True),
                       _m(f"lck{y}cup1", f"LCK/{y} Season/Cup", f"LCK Cup {y}", f"{y}-01-15 08:00:00", "t1", "T1", "hle", "Hanwha Life Esports"),
                       _m(f"lck{y}cup2", f"LCK/{y} Season/Cup", f"LCK Cup {y}", f"{y}-01-25 08:00:00", "geng", "Gen.G", "dk", "Dplus KIA")],
           "tours": [{"page": f"LCK/{p} Season/Season Playoffs", "name": f"LCK {p} Season Playoffs", "start": f"{p}-08-29", "end": f"{p}-09-13", "playoff": True},
                     {"page": f"LCK/{y} Season/Cup", "name": f"LCK Cup {y}", "start": f"{y}-01-15", "end": f"{y}-03-01", "playoff": False}]}
    intl = {"season": y, "at": f"{y}-01-01T00:00:00+00:00",
            "matches": [_m(f"msi{y}a", f"{y} Mid-Season Invitational", f"MSI {y}", f"{y}-05-15 10:00:00", "t1", "T1", "bilibili-gaming", "Bilibili Gaming"),
                        _m(f"msi{y}b", f"{y} Mid-Season Invitational", f"MSI {y}", f"{y}-05-15 13:00:00", "g2-esports", "G2 Esports", "flyquest", "FlyQuest")],
            "tours": [{"page": f"{y} Mid-Season Invitational", "name": f"MSI {y}", "start": f"{y}-05-13", "end": f"{y}-05-30"}],
            "teams": {"bilibili-gaming": {"name": "Bilibili Gaming", "short": "BLG"}}}
    return {"lck": lck, "intl": intl}


def frozen(at: datetime):
    """그 시각에 멈춘 datetime(now만 바뀜, 나머지는 진짜 datetime 그대로)."""
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return at.astimezone(tz) if tz else at.astimezone(KST).replace(tzinfo=None)
    return Frozen


class at_time:
    """with at_time(그 시각): 화면·서버·시즌 계산·독버섯이 보는 '지금'을 그 시각으로."""
    def __init__(self, when: datetime):
        self.when, self.stack = when, ExitStack()

    def __enter__(self):
        f = frozen(self.when)
        for mod in (views, server, archive, news):
            self.stack.enter_context(mock.patch.object(mod, "datetime", f))
        self.stack.enter_context(mock.patch.object(farm, "_now", lambda: self.when.astimezone(UTC)))
        return self.when.astimezone(KST).date()

    def __exit__(self, *a):
        self.stack.close()


def title_years(html: str) -> set:
    return set(re.findall(r"(\d{4}) LCK 대회 일정", html))


def picked(html: str) -> str:
    return re.search(r'aria-label="시즌 고르기"><b>(\d{4})', html).group(1)


class SeasonCycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        farm.init()
        server.load_static()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.old = schedule.DATA

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        schedule.DATA = cls.old

    def tearDown(self):
        with db() as c:
            c.execute("DELETE FROM farm_items")

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as r:
            return r.geturl().replace(self.base, ""), r.read().decode("utf-8")

    def test_collector_season_year(self):
        # 수집기용 시즌 계산: 11월부터는 다음 해(화면 제목엔 안 씀)
        for y in YEARS:
            with self.subTest(y=y):
                self.assertEqual(archive.current_season(date(y - 1, 11, 20)), y)
                self.assertEqual(archive.current_season(date(y, 1, 3)), y)
                self.assertEqual(archive.current_season(date(y, 8, 15)), y)
                self.assertEqual(archive.current_season(date(y, 11, 15)), y + 1)

    def test_stove_league_shows_finished_season(self):
        # y-1년 11월(스토브리그): 시즌 고르기 = 제목 = 데이터 모두 y-1, '시즌' 메뉴는 결과·순위로, 빈 일정은 안내 카드 하나
        for y in YEARS:
            schedule.DATA = season_data(y)
            with self.subTest(y=y), at_time(datetime(y - 1, 11, 20, 14, 0, tzinfo=KST)) as today:
                self.assertTrue(views.stove_phase(today))
                self.assertEqual(views.view_year("lck", None, today), str(y - 1))
                self.assertEqual(views.season_entry("lck", None, today), "/results")
                plan = views.render_schedule("lck")
                self.assertEqual(picked(plan), str(y - 1))
                self.assertEqual(title_years(plan), {str(y - 1)})
                self.assertIn(f"{y - 1} 시즌 경기가 모두 종료됐어요.", plan)
                self.assertIn(f'href="/lck/schedule?season={y}">{y} 시즌 일정 보기', plan)   # 다음 시즌 경기가 올라와 있으면 길 안내
                self.assertIn('href="/lck/results" data-sec="schedule"', plan)
                res = views.render_schedule("lck", None, "results")
                self.assertIn(f"{y - 1} 시즌 결과", res)
                self.assertIn('class="mt done"', res)
                # '{y} 시즌 · 예정'을 고르면 그 해 일정(다가오는 경기)
                nxt = views.render_schedule("lck", y)
                self.assertEqual((picked(nxt), title_years(nxt)), (str(y), {str(y)}))
                self.assertIn("다가오는 경기", nxt)
                self.assertEqual(views.season_entry("lck", y, today), "/schedule")

    def test_january_before_and_after_opening(self):
        for y in YEARS:
            schedule.DATA = season_data(y)
            with self.subTest(y=y, when="개막 전"), at_time(datetime(y, 1, 10, 12, 0, tzinfo=KST)) as today:
                self.assertTrue(views.stove_phase(today))                 # 1월이라도 첫 경기 전이면 아직 스토브리그
                self.assertEqual(views.view_year("lck", None, today), str(y - 1))
            with self.subTest(y=y, when="개막 뒤"), at_time(datetime(y, 1, 20, 12, 0, tzinfo=KST)) as today:
                self.assertFalse(views.stove_phase(today))
                self.assertEqual(views.view_year("lck", None, today), str(y))
                self.assertEqual(views.season_entry("lck", None, today), "/schedule")
                plan = views.render_schedule("lck")
                self.assertEqual((picked(plan), title_years(plan)), (str(y), {str(y)}))
                self.assertIn("다가오는 경기", plan)

    def test_tournament_queries(self):
        # 대회 시작 3일 전 ~ 끝난 다음 날에만 그 대회 검색어
        for y in YEARS:
            schedule.DATA = season_data(y)
            with self.subTest(y=y):
                self.assertEqual(news.tour_queries(date(y, 1, 11)), [])
                self.assertIn("LCK컵", news.tour_queries(date(y, 1, 12))[0][1])
                self.assertIn("LCK컵", news.tour_queries(date(y, 3, 2))[0][1])
                self.assertIn("MSI", news.tour_queries(date(y, 5, 14))[0][1])
                self.assertEqual(news.tour_queries(date(y, 6, 5)), [])

    def test_international_farm_items(self):
        # 국제전: LCK 팀이 나오는 경기만, 이틀 전부터 독버섯 판
        for y in YEARS:
            schedule.DATA = season_data(y)
            with self.subTest(y=y), at_time(datetime(y, 5, 14, 9, 0, tzinfo=KST)):
                farm.sync(force=True)
                ids = {it["id"] for it in farm.board([])["open"]}
                self.assertIn(f"m:msi{y}a", ids)
                self.assertNotIn(f"m:msi{y}b", ids)
            with db() as c:
                c.execute("DELETE FROM farm_items")

    def test_server_routes(self):
        # 실제 서버로: 스토브리그 동안 '지금'(y-1)과 '{y} 시즌 · 예정'이 각자 제 해만 보여 줌
        for y in YEARS:
            schedule.DATA = season_data(y)
            with self.subTest(y=y), at_time(datetime(y - 1, 11, 20, 14, 0, tzinfo=KST)):
                url, body = self.get("/lck/schedule")
                self.assertEqual(title_years(body), {str(y - 1)})
                url, body = self.get(f"/lck/schedule?season={y}")
                self.assertEqual(title_years(body), {str(y)})
                url, body = self.get(f"/lck/results?season={y - 1}")      # 방금 끝난 시즌을 '기록'으로 열면 지금 화면으로
                self.assertEqual(url, "/lck/results")
                self.assertIn(f"{y - 1} 시즌 결과", body)


if __name__ == "__main__":
    unittest.main()
