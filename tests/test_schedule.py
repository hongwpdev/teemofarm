"""일정·결과 도우미 테스트(인터넷 없이). 실행: python -m unittest discover -s tests"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker import schedule  # noqa: E402
from tracker.web import views  # noqa: E402


def _m(t1, t2, at, win="", s1="", s2="", page="P", tab="Week 1"):
    return {"id": "", "page": page, "tour": "LCK 2027 Cup", "playoff": False, "tab": tab, "at": at, "bo": "3",
            "t1": t1, "k1": "", "t2": t2, "k2": "", "s1": s1, "s2": s2, "win": win, "ff": ""}


def _f(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class ScheduleTest(unittest.TestCase):
    def test_tab_ko(self):
        self.assertEqual(views.tab_ko("Week 3"), "3주차")
        self.assertEqual(views.tab_ko("Playoffs Round 2"), "플레이오프 2라운드")
        self.assertEqual(views.tab_ko("Play-In Round 1"), "플레이-인 1라운드")
        self.assertEqual(views.tab_ko("Finals"), "결승")
        self.assertEqual(views.tab_ko("Something"), "Something")

    def test_tour_ko(self):
        self.assertEqual(views.tour_ko("LCK/2026 Season/Season Playoffs"), "플레이오프")
        self.assertEqual(views.tour_ko("LCK/2026 Season/Rounds 3-4"), "정규 3·4라운드")
        self.assertEqual(views.tour_ko("LCK/2026 Season/Cup"), "LCK 컵")
        self.assertEqual(views.tour_ko("CBLOL/2026 Season/Cup", "CBLOL"), "CBLOL 컵")
        self.assertEqual(views.tour_ko("LPL/2026 Season/Split 1 Playoffs", "LPL"), "스플릿 1 플레이오프")
        self.assertEqual(views.tour_ko("LEC/2026 Season/Spring Season", "LEC"), "스프링")
        self.assertEqual(views.tour_ko("LPL/2026 Season/Grand Finals", "LPL"), "그랜드 파이널")
        self.assertEqual(views.tour_ko("LCS/2026 Season/Lock-In", "LCS"), "락인")

    def test_team_id(self):
        self.assertEqual(schedule.team_id("lck", "Gen.G"), "geng")
        self.assertEqual(schedule.team_id("lpl", "Bilibili Gaming"), "bilibili-gaming")
        self.assertEqual(schedule.team_id("lpl", "TBD"), "")

    def test_state(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(views._sch_state(_m("A", "B", _f(now + timedelta(hours=2))), now), "up")
        self.assertEqual(views._sch_state(_m("A", "B", _f(now - timedelta(hours=1))), now), "live")
        self.assertEqual(views._sch_state(_m("A", "B", _f(now - timedelta(hours=9))), now), "done")
        self.assertEqual(views._sch_state(_m("A", "B", _f(now - timedelta(hours=1)), win="2"), now), "done")

    def test_groups_split_by_who_played_whom(self):
        row = lambda t, p, w: {"team": t, "key": "", "place": p, "w": w, "l": "0", "gw": "0", "gl": "0"}  # noqa: E731
        table = [row("A", "1", "9"), row("X", "1", "3"), row("B", "2", "8"), row("Y", "2", "2")]
        ms = [_m("A", "B", "2026-08-01 08:00:00"), _m("X", "Y", "2026-08-01 10:00:00")]
        g = schedule._groups(table, ms, "P")
        self.assertEqual([[r["team"] for r in x["table"]] for x in g], [["A", "B"], ["X", "Y"]])
        self.assertEqual([x["name"] for x in g], ["상위 그룹", "하위 그룹"])

    def test_groups_single(self):
        table = [{"team": t, "key": "", "place": str(i + 1), "w": "1", "l": "0", "gw": "0", "gl": "0"} for i, t in enumerate("ABC")]
        self.assertEqual(schedule._groups(table, [], "P"), [{"name": "", "table": table}])

    def test_render_empty_and_full(self):
        schedule.DATA = {}
        self.assertIn("일정·결과", views.render_schedule("lck"))
        self.assertIn("일정·결과", views.render_schedule("lpl"))
        now = datetime.now(timezone.utc)
        ms = [_m("A", "B", _f(now + timedelta(days=1))), _m("C", "D", _f(now - timedelta(days=1)), "1", "2", "0")]
        ms[1]["k1"], ms[1]["k2"] = "c-team", "d-team"
        schedule.DATA = {"lpl": {"season": 2027, "current": True, "at": now.isoformat(), "standings": {}, "matches": ms,
                                 "teams": {"c-team": {"name": "C Team", "short": "CT"}, "d-team": {"name": "D Team", "short": "DT"}}}}
        page = views.render_schedule("lpl")
        self.assertIn("<b>CT</b>", page)
        self.assertIn('data-t="c-team"', page)
        self.assertIn("다가오는 경기", page)
        self.assertIn("최근 결과", page)
        self.assertIn('class="mt up"', page)
        self.assertIn('class="mt done"', page)


if __name__ == "__main__":
    unittest.main()
