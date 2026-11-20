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
        self.assertEqual(views.tour_ko("LCK/2025 Season/Rounds 3-5"), "정규 3~5라운드")
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

    def test_intl(self):
        # 국제전: LCK 팀은 LCK 키(로고·내 팀과 같음), 그 밖의 팀은 이름 키. 대회는 리그 이름(First Stand·MSI·월즈·EWC)으로 찾음
        from unittest import mock
        self.assertEqual(schedule.team_id(schedule.INTL, "Hanwha Life Esports"), "hle")
        self.assertEqual(schedule.team_id(schedule.INTL, "Bilibili Gaming"), "bilibili-gaming")
        self.assertNotIn(schedule.INTL, schedule.leagues())               # 메뉴엔 없음
        self.assertIn(schedule.INTL, schedule.fetched())
        seen = []

        def cargo(gap, tables, fields, where, **kw):
            seen.append((tables, where))
            if tables == "Tournaments":
                return [{"OverviewPage": "2027 Mid-Season Invitational", "Name": "MSI 2027", "DateStart": "2027-06-27",
                         "Date": "2027-07-12", "IsPlayoffs": "0"}] if "2027" in where else []
            if tables == "MatchSchedule":
                return [{"Team1": "Bilibili Gaming", "Team2": "T1", "DT": "2027-06-27 09:00:00", "MatchId": "msi_1",
                         "OverviewPage": "2027 Mid-Season Invitational", "Winner": ""}]
            return []
        old = dict(schedule.DATA)
        try:
            with mock.patch.object(schedule, "cargo", cargo), mock.patch.object(schedule, "current_season", lambda: 2027), \
                    mock.patch.object(schedule.teamlogos, "team_rows", lambda names, gap: {"Bilibili Gaming": {"Short": "BLG", "Image": ""}}), \
                    mock.patch.object(schedule.teamlogos, "ensure", lambda imgs: 0), mock.patch.object(schedule, "_path", lambda lg: os.devnull):
                self.assertTrue(schedule.refresh(schedule.INTL))
            d = schedule.get(schedule.INTL)
            self.assertTrue(any('League IN' in w and 'Region="International"' in w for t, w in seen if t == "Tournaments"))
            self.assertFalse([t for t, w in seen if t == "Standings"])     # 국제전은 순위표를 안 받음
            self.assertEqual((d["matches"][0]["k1"], d["matches"][0]["k2"]), ("bilibili-gaming", "t1"))
            self.assertEqual(d["teams"]["t1"]["image"], "")                  # LCK 팀 로고는 따로 안 받음
            self.assertEqual(d["teams"]["bilibili-gaming"]["short"], "BLG")
        finally:
            schedule.DATA = old

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

    def test_lck_schedule_and_results(self):
        import re
        now = datetime.now(timezone.utc)
        old = [_m("A", "B", _f(now - timedelta(days=60)), "1", "2", "0", page="LCK/2026 Season/Rounds 3-4")]
        schedule.DATA = {"lck": {"season": 2026, "current": False, "at": now.isoformat(), "standings": {}, "matches": old,
                                 "tours": [{"page": "LCK/2026 Season/Rounds 3-4", "name": "LCK 2026 Rounds 3-4",
                                            "start": "2026-07-29", "end": "2026-08-23", "playoff": False}]}}
        cs = views.current_season(datetime.now(views.KST).date())
        # 시즌 고르기 표시: 스토브리그 기간엔 방금 끝난 시즌('2026 시즌', 안에 스토브리그 메뉴), 시즌 중엔 그 시즌('2027 시즌')
        shown = str(cs - 1) if views.stove_phase(datetime.now(views.KST).date()) else str(cs)
        pick = lambda page: re.search(r'aria-label="시즌 고르기"><b>(\d+)', page).group(1)   # noqa: E731
        # 규칙 1: 시즌 고르기 = 본문 제목 = 데이터. 규칙 3: 앞으로 경기가 없으면 안내 카드 하나
        plan = views.render_schedule("lck")
        self.assertEqual(pick(plan), shown)
        self.assertIn(f"{shown} LCK 대회 일정", plan)
        self.assertNotIn(f"{cs if shown != str(cs) else cs - 1} LCK 대회 일정", plan)
        self.assertEqual(plan.count('class="card sblock'), 1)                    # 빈 카드 여러 장 대신 하나
        if shown == "2026":
            self.assertIn("2026 시즌 경기가 모두 종료됐어요.", plan)
            self.assertIn('class="btn st-go" href="/lck/results">결과·순위 보기 →', plan)
            self.assertIn('href="/lck/results" data-sec="schedule"', plan)   # 규칙 2: 끝난 시즌이면 '시즌' 메뉴가 결과·순위로
        self.assertNotIn("'결과'에서", plan)                                     # 규칙 4: 용어 '결과·순위'로 통일
        self.assertNotIn('class="mt ', plan)
        res = views.render_schedule("lck", None, "results")
        self.assertEqual(pick(res), shown)
        self.assertIn(f"{shown} 시즌 결과", res)
        if shown == "2026":
            self.assertIn('class="mt done"', res)
        # 개막 전 다음 시즌(경기 0건): '아직 안 올라옴' + 지난 시즌 결과·순위
        nxt = views.render_schedule("lck", 2027)
        self.assertIn("2027 LCK 일정이 아직 리그피디아에 올라오지 않았어요. 올라오면 바로 보여요.", nxt)
        self.assertIn("2026 시즌 결과·순위 보기 →", nxt)
        self.assertEqual(nxt.count('class="card'), 1 + nxt.count('class="card tours'))   # 대회 일정이 없으면 카드 1장
        one = views.render_schedule("lck", 2026, "results", "Rounds 3-4")   # 대회 일정에서 한 대회를 눌러 들어옴
        self.assertIn("2026 시즌 결과 · 정규 3·4라운드", one)
        self.assertIn("전체 대회 보기", one)
        self.assertIn('class="mt done"', one)
        self.assertNotIn("· 엉뚱", views.render_schedule("lck", 2026, "results", "엉뚱"))   # 없는 대회 이름은 그냥 전체
        past = views.render_schedule("lck", 2026, "results")          # 2026을 고름
        self.assertEqual(pick(past), "2026")
        self.assertIn('class="mt done"', past)
        plan26 = views.render_schedule("lck", 2026)                   # 2026 일정: 그 시즌 대회 일정
        self.assertIn("정규 3·4라운드", plan26)
        self.assertEqual(pick(views.render_roster("lck")), shown)   # 다른 탭과 같은 시즌 표시

    def test_tours_card(self):
        # 대회 일정 타임라인: 상태 배지(종료·진행 중·D-N), 큰 무대 강조, 끝난 대회의 결승 우승팀
        from datetime import date
        today = date(2026, 8, 27)
        d = {"tours": [{"page": "LCK/2026 Season/Cup", "start": "2026-01-14", "end": "2026-03-01", "playoff": False},
                       {"page": "LCK/2026 Season/Season Play-In", "start": "2026-08-26", "end": "2026-08-28", "playoff": True},
                       {"page": "LCK/2026 Season/Season Playoffs", "start": "2026-08-29", "end": "2026-09-13", "playoff": True}],
             "matches": [{**_m("Gen.G", "BNK FEARX", "2026-03-01 08:00:00", "1", "3", "0", page="LCK/2026 Season/Cup", tab="Finals"),
                          "k1": "geng", "k2": "bfx"}]}
        html = views.tours_card(d, "2026", "LCK", today)
        self.assertRegex(html, r'<li class="done">.*?LCK 컵.*?class="twin".*?GEN 우승.*?01\.14 ~ 03\.01.*?종료')
        self.assertIn('<li class="now"><div class="trow"><i class="tdot"', html)  # 플레이-인은 큰 무대 아님, 끝난 경기 없으면 링크 없음
        self.assertRegex(html, r'<li class="up major">.*?플레이오프.*?D-2<')
        self.assertEqual(html.count("우승"), 1)                                # 결승이 없는(아직 안 끝난) 대회엔 우승팀 없음
        # 끝난 경기가 있는 대회는 눌러서 결과·순위의 그 대회로
        linked = views.tours_card(d, "2026", "LCK", today, "lck")
        self.assertRegex(linked, r'<a class="trow" href="/lck/results\?(season=2026&amp;)?stage=Cup"')
        self.assertEqual(linked.count('class="trow" href'), 1)

    def test_render_empty_and_full(self):
        schedule.DATA = {}
        self.assertIn("일정·결과", views.render_schedule("lck"))
        self.assertIn("일정·결과", views.render_schedule("lpl"))
        now = datetime.now(timezone.utc)
        pg = "LPL/2027 Season/Split 1"
        ms = [_m("A", "B", _f(now + timedelta(days=1)), page=pg), _m("C", "D", _f(now - timedelta(days=1)), "1", "2", "0", page=pg)]
        ms[1]["k1"], ms[1]["k2"] = "c-team", "d-team"
        schedule.DATA = {"lpl": {"season": 2027, "current": True, "at": now.isoformat(), "standings": {}, "matches": ms,
                                 "teams": {"c-team": {"name": "C Team", "short": "CT"}, "d-team": {"name": "D Team", "short": "DT"}}}}
        plan = views.render_schedule("lpl")                           # 일정: 다가오는 경기
        self.assertIn("다가오는 경기", plan)
        self.assertIn('class="mt up"', plan)
        self.assertNotIn('class="mt done"', plan)
        res = views.render_schedule("lpl", None, "results")           # 결과: 끝난 경기
        self.assertIn("<b>CT</b>", res)
        self.assertIn('data-t="c-team"', res)
        self.assertIn('class="mt done"', res)
        self.assertNotIn('class="mt up"', res)


if __name__ == "__main__":
    unittest.main()
