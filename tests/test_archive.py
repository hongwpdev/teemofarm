"""지난 시즌 기록 화면(?season=): 기록 파일이 있을 때 소식·로스터·이적·일정 네 화면이 모두 열리는지.
(기록 파일이 없으면 '모으는 중' 화면만 나와서 smoke 테스트로는 못 잡음 — 실제로 순위표 쪽 오류를 놓친 적 있음)"""
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker import archive  # noqa: E402
from tracker.core import init_db  # noqa: E402
from tracker.web import views  # noqa: E402

REC = {"year": 2026, "missing": [],
       "stages": [{"name": "LCK 2026 Rounds 3-4", "page": "LCK/2026 Season/Rounds 3-4", "start": "2026-07-29",
                   "table": [{"team": "Gen.G", "key": "geng", "place": "1", "w": "19", "l": "7", "gw": "41", "gl": "19"},
                             {"team": "Old Team", "key": "", "place": "2", "w": "1", "l": "9", "gw": "3", "gl": "18"}]}],
       "champion": {"name": "LCK 2026 Season Playoffs", "winner": "Gen.G", "wkey": "geng", "loser": "Hanwha Life Esports",
                    "lkey": "hle", "score": "3:1", "date": "2026-09-13"},
       "roster": [{"team": "t1", "team_name": "T1", "role": "Mid", "page": "Faker", "nick": "Faker"}],
       "moves": [{"date": "2025-11-20", "page": "Zeus", "nick": "Zeus", "role": "Top", "from": "T1", "fkey": "t1",
                  "to": "Hanwha Life Esports", "tkey": "hle"}],
       "rosters": [{"name": "LCK Cup 2026", "page": "LCK/2026 Season/Cup", "playoff": False,
                    "roster": [{"team": "bro", "team_name": "OKSavingsBank BRION", "role": "Top", "page": "Morgan", "nick": "Morgan"}]},
                   {"name": "LCK 2026 Rounds 3-4", "page": "LCK/2026 Season/Rounds 3-4", "playoff": False,
                    "roster": [{"team": "t1", "team_name": "T1", "role": "Mid", "page": "Faker", "nick": "Faker"}]},
                   {"name": "LCK 2026 Season Playoffs", "page": "LCK/2026 Season/Season Playoffs", "playoff": True,
                    "roster": [{"team": "geng", "team_name": "Gen.G", "role": "Mid", "page": "Chovy", "nick": "Chovy"}]}]}


class ArchiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_all_sections_render(self):
        with mock.patch.object(archive, "get", lambda y: REC):
            for sec in ("", "roster", "fa", "schedule", "results"):
                with self.subTest(sec=sec):
                    page = views.render_archive("lck", sec, 2026)
                    self.assertIn("</html>", page)
            self.assertIn("Old Team", views.render_archive("lck", "results", 2026))    # LCK 밖 팀 이름도 표시
            self.assertIn('class="card champ"', views.render_archive("lck", "", 2026))   # 우승 카드

    def test_schedule_and_results_differ(self):
        # 지난 시즌 '일정'과 '결과·순위'가 똑같이 보였던 문제: 일정 = 대회 일정(기간·대회별 1위), 결과 = 우승 · 순위표
        rec = {**REC, "tours": [
            {"page": "LCK/2026 Season/Cup", "name": "LCK Cup 2026", "start": "2026-01-14", "end": "2026-02-23", "playoff": False,
             "winners": [{"team": "Hanwha Life Esports", "key": "hle"}]},
            {"page": "LCK/2026 Season/Rounds 3-4", "name": "LCK 2026 Rounds 3-4", "start": "2026-07-29", "end": "2026-09-01",
             "playoff": False, "winners": [{"team": "Gen.G", "key": "geng"}]}]}
        with mock.patch.object(archive, "get", lambda y: rec):
            sch = views.render_archive("lck", "schedule", 2026)
            res = views.render_archive("lck", "results", 2026)
        self.assertIn('class="card tours"', sch)
        self.assertIn("01.14 ~ 02.23", sch)
        self.assertIn("우승</small>", sch)                       # 컵 = 우승
        self.assertIn("1위</small>", sch)                         # 정규 라운드 = 1위
        self.assertNotIn('class="card stand"', sch)
        self.assertIn('class="card stand"', res)
        self.assertIn('class="card champ"', res)
        self.assertNotIn('class="card tours"', res)

    def test_grouped_standings(self):
        # 2025 3~5라운드처럼 레전드·라이즈로 나뉜 대회: 그룹마다 따로(1위가 둘인 한 표가 아니라)
        rec = {**REC, "stages": [{"name": "LCK 2025 Rounds 3-5", "page": "LCK/2025 Season/Rounds 3-5", "start": "",
                                  "groups": ["Legend", "Rise"], "table": [
            {"team": "Gen.G", "key": "geng", "place": "1", "w": "29", "l": "1", "gw": "59", "gl": "11", "group": "Legend"},
            {"team": "Dplus Kia", "key": "dk", "place": "1", "w": "19", "l": "11", "gw": "43", "gl": "31", "group": "Rise"},
            {"team": "Hanwha Life Esports", "key": "hle", "place": "2", "w": "20", "l": "10", "gw": "46", "gl": "24", "group": "Legend"}]}]}
        with mock.patch.object(archive, "get", lambda y: rec):
            res = views.render_archive("lck", "results", 2026)
        card = res[res.index('class="card stand"'):].split("</section>")[0]
        self.assertLess(card.index("레전드 그룹"), card.index("라이즈 그룹"))
        leg, rise = card.split("라이즈 그룹")
        self.assertIn("GEN", leg)
        self.assertIn("HLE", leg)
        self.assertNotIn(">DK<", leg)
        self.assertIn("DK", rise)

    def test_champ_banner(self):
        with mock.patch.object(archive, "get", lambda y: REC):
            page = views.render_archive("lck", "results", 2026)
        card = page[page.index('class="card champ"'):].split("</section>")[0]
        self.assertIn("🏆 CHAMPION", card)
        self.assertIn('class="ch-lg"', card)
        self.assertIn("<b>GEN</b>", card)
        self.assertIn("<em>3 : 1</em>", card)
        self.assertIn("2026.09.13", card)
        no_date = {**REC, "champion": {**REC["champion"], "date": ""}}
        with mock.patch.object(archive, "get", lambda y: no_date):
            page = views.render_archive("lck", "results", 2026)
        p = page[page.index('class="card champ"'):].split("</section>")[0].split('<p class="sc-hide">')[1]
        self.assertTrue(p.rstrip().endswith("</span></p>"), p)    # 날짜가 없으면 '· ' 꼬리 없이 상대 팀으로 끝

    def test_old_file_refetches_missing_parts(self):
        old = {**REC, "at": 0}                                      # 그룹·대회 일정 없는 예전 저장본
        self.assertTrue(archive._old_format(old))
        new = {**REC, "tours": [], "champions": [], "stages": [{**REC["stages"][0], "groups": []}]}
        self.assertFalse(archive._old_format(new))

    def test_build_reads_groups_and_tours(self):
        def fake(gap, **q):
            t = q["tables"]
            if t == "Tournaments":
                return [{"OverviewPage": "LCK/2025 Season/Rounds 3-5", "Name": "LCK 2025 Rounds 3-5", "DateStart": "2025-07-23",
                         "Date": "2025-09-07", "IsPlayoffs": "0"},
                        {"OverviewPage": "LCK/2025 Season/Season Playoffs", "Name": "LCK 2025 Season Playoffs",
                         "DateStart": "2025-09-10", "Date": "2025-09-28", "IsPlayoffs": "1"}]
            if t == "Standings":
                return [{"Team": "Gen.G", "Place": "1", "WinSeries": "29", "LossSeries": "1", "WinGames": "59", "LossGames": "11"},
                        {"Team": "Dplus Kia", "Place": "1", "WinSeries": "19", "LossSeries": "11", "WinGames": "43", "LossGames": "31"}]
            if t == "TournamentGroups":
                return [{"Team": "Gen.G", "GroupDisplay": "Legend", "GroupN": "1"},
                        {"Team": "Dplus Kia", "GroupDisplay": "Rise", "GroupN": "2"}]
            if t == "TournamentResults":
                return [{"OverviewPage": "LCK/2025 Season/Rounds 3-5", "Team": "Gen.G"},
                        {"OverviewPage": "LCK/2025 Season/Rounds 3-5", "Team": "Dplus Kia"},
                        {"OverviewPage": "LCK/2025 Season/Season Playoffs", "Team": "Gen.G"}]
            return []
        with mock.patch.object(archive, "cargo", fake), mock.patch.dict(archive._CACHE, {}, clear=True):
            archive._build(2025)
            d = archive._CACHE[2025]
        st = d["stages"][0]
        self.assertEqual(st["groups"], ["Legend", "Rise"])
        self.assertEqual({r["team"]: r["group"] for r in st["table"]}, {"Gen.G": "Legend", "Dplus Kia": "Rise"})
        self.assertEqual([len(t["winners"]) for t in d["tours"]], [2, 1])
        self.assertEqual(d["tours"][1]["end"], "2025-09-28")

    def test_roster_by_tournament(self):
        with mock.patch.object(archive, "get", lambda y: REC):
            page = views.render_archive("lck", "roster", 2026)          # 기본: 마지막 정규 대회(3·4라운드)
            self.assertIn("Faker", page)
            self.assertNotIn("Chovy", page)
            self.assertIn("정규 3·4라운드", page)
            self.assertIn('href="/lck/roster?season=2026&amp;t=0"', page)
            cup = views.render_archive("lck", "roster", 2026, "0")       # LCK 컵: 그 당시 이름 + 지금 이름
            self.assertIn("OKSavingsBank BRION", cup)
            self.assertIn("지금:", cup)
            self.assertIn("Chovy", views.render_archive("lck", "roster", 2026, "2"))
            self.assertIn("Faker", views.render_archive("lck", "roster", 2026, "99"))   # 이상한 값은 기본으로


if __name__ == "__main__":
    unittest.main()
