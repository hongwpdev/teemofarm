"""지난 기록 넓히기: LCK 2012~(OGN 챔피언스 포함) · 국제전 월즈 2011~ · MSI 2015~.
리그피디아 실제 응답(tests/fixtures/history_sample.json, 2026.11 받음)을 그대로 돌려주는 가짜 cargo로 확인."""
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker import archive, intl_hist, schedule  # noqa: E402
from tracker.core import init_db  # noqa: E402
from tracker.web import intl, views  # noqa: E402

REC = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "history_sample.json"), encoding="utf-8"))


def fake_cargo(gap, retry=True, **q):
    if q.get("tables") == "Teams":
        shorts = REC["Teams||shorts"]
        return [{"Name": n, "Short": s, "OverviewPage": n, "Image": ""} for n, s in shorts.items() if f'"{n}"' in q["where"]]
    return list(REC.get(f'{q["tables"]}||{q["where"]}', []))


class LckHistoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.d = {}
        with mock.patch.object(archive, "cargo", fake_cargo), mock.patch.object(archive, "current_season", lambda today=None: 2027), \
                mock.patch.dict(archive._CACHE, {}, clear=True):
            for y in (2013, 2019):
                archive._build(y)
                cls.d[y] = archive._CACHE[y]

    def page(self, year, sec):
        with mock.patch.object(archive, "get", lambda y, first=True: self.d[year]), \
                mock.patch.object(archive, "current_season", lambda today=None: 2027):
            return views.render_archive("lck", sec, year)

    def test_years_back_to_2012(self):
        with mock.patch.object(archive, "current_season", lambda today=None: 2027):
            ys = archive.archive_years()
        self.assertEqual((ys[0], ys[-1], len(ys)), (2026, 2012, 15))
        self.assertEqual(archive.prefix(2015), "Champions")
        self.assertEqual(archive.prefix(2016), "LCK")

    def test_old_team_names(self):
        self.assertEqual(archive.team_key("SK Telecom T1"), "t1")
        self.assertEqual(archive.team_key("Samsung White"), "geng")
        self.assertEqual(archive.team_key("Kingzone DragonX"), "drx")
        self.assertEqual(archive.team_key("DWG KIA"), "dk")
        self.assertEqual(archive.team_key("Griffin (Korean Team)"), "")        # 지금 없는 팀은 그 당시 이름 그대로

    def test_champions_2013(self):
        # 2014년까지(OGN 챔피언스): 윈터·스프링·서머 대회마다 우승(대회 안의 결승)
        cs = self.d[2013]["champions"]
        self.assertEqual([(c["winner"], c["score"]) for c in cs],
                         [("NaJin Sword", "3:0"), ("MVP Ozone", "3:0"), ("SK Telecom T1 2", "3:2")])
        res = self.page(2013, "results")
        self.assertEqual(res.count("🏆 CHAMPION"), 3)
        self.assertLess(res.index("2013 챔피언스 서머 우승"), res.index("2013 챔피언스 윈터 우승"))   # 최근 대회부터
        self.assertIn("<b>SKT2</b>", res)                                    # 그 당시 약칭
        self.assertNotIn("Qualifiers", res)                                    # 예선은 순위표에서 뺌
        self.assertIn("A 그룹", res)

    def test_champions_2019(self):
        cs = self.d[2019]["champions"]
        self.assertEqual([(c["page"].split("/")[-1], c["winner"]) for c in cs],
                         [("Spring Playoffs", "SK Telecom T1"), ("Summer Playoffs", "SK Telecom T1")])
        res = self.page(2019, "results")
        self.assertIn("2019 LCK 서머 플레이오프 우승", res)
        self.assertIn("2019 LCK 스프링 플레이오프 우승", res)
        self.assertIn("<b>SKT</b>", res)
        self.assertIn("GRF", res)                                             # 지금 없는 팀: 그 당시 약칭
        self.assertNotIn("Promotion", res)
        sch = self.page(2019, "schedule")
        self.assertIn("2019 LCK 대회 일정", sch)
        self.assertRegex(sch, r"스프링 플레이오프</b><small class=\"twin win\"[^>]*>.*?SKT.*? 우승")
        self.assertRegex(sch, r"<b>스프링</b><small class=\"twin\"[^>]*>.*?GRF.*? 1위")


class IntlHistoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.dir = tempfile.mkdtemp()
        idx = {("worlds", "2011"): [{"OverviewPage": "Season 1 World Championship", "Name": "Season 1 World Championship",
                                     "DateStart": "2011-06-18", "Date": "2011-06-20", "IsPlayoffs": "0"}],
               ("msi", "2021"): [{"OverviewPage": "2021 Mid-Season Invitational", "Name": "2021 Mid-Season Invitational",
                                  "DateStart": "2021-05-06", "Date": "2021-05-23", "IsPlayoffs": "0"}]}
        with mock.patch.object(intl_hist, "cargo", fake_cargo), mock.patch.object(schedule, "cargo", fake_cargo), \
                mock.patch.object(intl_hist.teamlogos, "team_rows", lambda names, gap=None: {}), \
                mock.patch.object(intl_hist.teamlogos, "ensure", lambda imgs: 0), \
                mock.patch.object(intl_hist, "_DIR", cls.dir), mock.patch.object(intl_hist, "index", lambda gap=None: idx), \
                mock.patch.object(intl_hist, "GAP_BETWEEN", 0), mock.patch.object(intl_hist, "_live_years", lambda: set()):
            intl_hist._MEM["files"].clear()
            intl_hist._run_once()

    def render(self, ev, sec, year):
        with mock.patch.object(intl_hist, "_DIR", self.dir), mock.patch.object(schedule, "get", lambda lg: {}):
            intl_hist._MEM["merged"] = None
            return intl.render(ev, sec, year)

    def test_files_saved(self):
        self.assertTrue(os.path.exists(os.path.join(self.dir, "intl_hist_worlds_2011.json")))
        d = json.load(open(os.path.join(self.dir, "intl_hist_msi_2021.json"), encoding="utf-8"))
        self.assertEqual(len(d["matches"]), 12)
        self.assertTrue(d["complete"])
        # 그 당시 이름이 지금과 다른 LCK 팀(DWG KIA)은 그 당시 팀으로(지금 DK 로고·약칭을 쓰지 않음)
        self.assertEqual({m["k1"] for m in d["matches"] if m["t1"] == "DWG KIA"}, {"dwg-kia"})

    def test_worlds_2011(self):
        res = self.render("worlds", "results", "2011")
        self.assertIn("2011 월드 챔피언십 우승", res)
        card = res[res.index('class="card champ'):].split("</section>")[0]
        self.assertIn("Fnatic", card)
        self.assertIn("<em>2 : 1</em>", card)
        self.assertIn("녹아웃 스테이지", res)                                    # 'Round 1~3'은 2011년엔 토너먼트(스위스 아님)
        self.assertNotIn("스위스", res)
        self.assertIn("그룹 스테이지", res)
        self.assertIn("5위 결정전", res)
        with mock.patch.object(intl_hist, "_DIR", self.dir), mock.patch.object(schedule, "get", lambda lg: {}):
            intl_hist._MEM["merged"] = None
            self.assertIn("2011", intl.years("worlds"))

    def test_msi_2021_rumble(self):
        res = self.render("msi", "results", "2021")
        self.assertIn("럼블 스테이지", res)
        self.assertIn("그룹 스테이지", res)
        self.assertIn("2021 MSI 우승", res)
        card = res[res.index('class="card champ'):].split("</section>")[0]
        self.assertIn("<em>3 : 2</em>", card)

    def test_past_event_has_archive_bar(self):
        # 시즌 고르기에 '기록'으로 나오는 지난 국제전도 LCK처럼 '기록을 보고 있어요' 안내(실제 사이트 전체 점검에서 찾음)
        from datetime import date
        with mock.patch.object(intl, "years", lambda ev, d=None: ["2026", "2011"]):
            old = views.shell("worlds", "results", "t", "", (), date(2026, 11, 21), season="2011")
            new = views.shell("worlds", "results", "t", "", (), date(2026, 11, 21), season="2026")
        self.assertIn("지금 <b>2011 월드 챔피언십</b> 기록을 보고 있어요", old)
        self.assertNotIn("archive-bar", new)

    def test_kind(self):
        k = lambda tab, page: intl.kind({"tab": tab, "page": page})     # noqa: E731
        self.assertEqual(k("Day 3", "2017 Season World Championship/Main Event"), "group")
        self.assertEqual(k("Day 3", "2017 Season World Championship/Play-In"), "playin")
        self.assertEqual(k("Tiebreakers", "2017 Mid-Season Invitational/Main Event"), "group")
        self.assertEqual(k("Round 2", "Season 1 World Championship"), "ko")
        self.assertEqual(k("Round 2", "2025 Season World Championship/Main Event"), "swiss")
        self.assertEqual(k("Rumble Day 2", "2022 Mid-Season Invitational"), "rumble")
        self.assertEqual(schedule.intl_event("Season 2 World Championship"), ("worlds", "2012"))


if __name__ == "__main__":
    unittest.main()
