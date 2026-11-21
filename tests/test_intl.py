"""국제전 메뉴(FST·MSI·EWC·WORLDS): 리그피디아에서 받아 둔 2026 실제 자료(tests/fixtures)로
대회마다 다른 형식(그룹 → 녹아웃 · 플레이-인 → 더블 엘리미네이션 · 그룹 → 녹아웃(3·4위전) · 플레이-인 → 스위스 → 녹아웃)이
코드에 대회별 단계를 적어 두지 않고도 맞게 나뉘는지, 화면이 잘 나오는지 점검."""
import json
import os
import tempfile
import unittest
from datetime import date

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker import schedule  # noqa: E402
from tracker.core import init_db  # noqa: E402
from tracker.web import intl  # noqa: E402

FX = os.path.join(os.path.dirname(__file__), "fixtures", "intl_2026.json")
DAY = date(2026, 11, 20)


class IntlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        with open(FX, encoding="utf-8") as f:
            cls.d = json.load(f)
        cls.old = dict(schedule.DATA)
        schedule.DATA = {**schedule.DATA, schedule.INTL: cls.d}

    @classmethod
    def tearDownClass(cls):
        schedule.DATA = cls.old

    def test_event_pages(self):
        self.assertEqual(schedule.intl_event("2026 Season World Championship/Main Event"), ("worlds", "2026"))
        self.assertEqual(schedule.intl_event("Esports World Cup 2026"), ("ewc", "2026"))
        self.assertEqual(schedule.intl_event("2026 Mid-Season Invitational/Classic Showmatch"), (None, ""))
        self.assertEqual(schedule.intl_event("LCK/2026 Season/Cup"), (None, ""))
        for ev in intl.EVENTS:
            self.assertEqual(intl.years(ev, self.d), ["2026"], ev)
        self.assertEqual(intl.year_of("msi", "1999", self.d), "2026")

    def test_stages_follow_each_format(self):
        keys = {ev: [s["key"] for s in intl.stages(self.d, ev, "2026", DAY)] for ev in intl.EVENTS}
        self.assertEqual(keys, {"fst": ["group", "ko"], "msi": ["playin", "bracket"], "ewc": ["group", "ko"],
                                "worlds": ["playin", "swiss", "ko"]})
        self.assertTrue(all(s["status"] == "done" for ev in intl.EVENTS for s in intl.stages(self.d, ev, "2026", DAY)))
        msi = intl.stages(self.d, "msi", "2026", date(2026, 7, 2))
        self.assertEqual(msi[0]["status"], "done")

    def test_champions_and_finish(self):
        champ = {ev: intl.champion(intl.matches(self.d, ev, "2026"))[0] for ev in intl.EVENTS}
        self.assertEqual(champ, {"fst": "bilibili-gaming", "msi": "hle", "ewc": "dk", "worlds": "bilibili-gaming"})
        w = intl.finish(self.d, "worlds", "2026", DAY)
        self.assertEqual((w["bilibili-gaming"], w["geng"], w["t1"], w["dk"], w["hle"], w["cloud9"]),
                         ("우승", "준우승", "4강", "8강", "스위스 탈락", "플레이-인 탈락"))
        e = intl.finish(self.d, "ewc", "2026", DAY)
        self.assertEqual((e["dk"], e["karmine-corp"], e["geng"], e["t1"], e["hle"], e["sentinels"]),
                         ("우승", "준우승", "3위", "4위", "8강", "그룹 스테이지 탈락"))
        m = intl.finish(self.d, "msi", "2026", DAY)
        self.assertEqual((m["hle"], m["bilibili-gaming"], m["team-liquid"]), ("우승", "준우승", "플레이-인 탈락"))
        self.assertNotIn("t1", [k for k, v in m.items() if v == "플레이-인 탈락"])    # 플레이-인 통과

    def test_swiss_and_groups(self):
        ss = intl.stages(self.d, "worlds", "2026", DAY)
        rec = intl._records(ss[1]["ms"])
        self.assertEqual((rec["dk"][:2], rec["geng"][:2], rec["anyone-s-legend"][:2]), ([3, 0], [3, 0], [0, 3]))
        fst = intl.stages(self.d, "fst", "2026", DAY)
        pools = intl._pools(fst[0]["ms"])
        self.assertEqual(len(pools), 2)                                     # 서로 맞붙은 팀끼리 A·B조
        self.assertEqual(sorted(len(p) for p in pools), [4, 4])
        self.assertEqual(len(intl._pools(intl.stages(self.d, "ewc", "2026", DAY)[0]["ms"])), 4)

    def test_pages(self):
        from tracker.web import views
        for ev in intl.EVENTS:
            with self.subTest(ev):
                sch = intl.render(ev, "schedule")
                self.assertIn(f'2026 {intl.EVENTS[ev]["full"]} 대회 일정', sch)
                self.assertIn("경기가 모두 종료됐어요", sch)
                menu = sch.split('<nav class="top_tab"')[1].split("</nav>")[0]
                self.assertNotIn("스토브리그", menu)
                self.assertIn("대회 일정", menu)
                res = intl.render(ev, "results")
                self.assertIn("우승</small>", res)
                self.assertIn('sch-champ', res)
                self.assertIn(">Faker<", intl.render(ev, "teams") if ev != "fst" else ">Faker<")
        self.assertIn("A조", intl.render("fst", "results"))
        self.assertIn("브래킷 4라운드", intl.render("msi", "results"))
        self.assertIn("3·4위전", intl.render("ewc", "results"))
        self.assertIn("8강 · Bo5", intl.render("worlds", "results"))
        menu = views.render_summary("lck")
        self.assertIn('<li class="lab">국제전</li>', menu)
        for ev in intl.EVENTS:
            self.assertIn(f'href="/{ev}/schedule"', menu)

    def _at_moment(self, ev, cut, listed):
        """대회 중 한 시점: cut번째 경기 30분 전. listed=False면 그 뒤 경기는 아직 리그피디아에 없음."""
        import copy
        from datetime import datetime, timedelta, timezone
        fmt = "%Y-%m-%d %H:%M:%S"
        ms = intl.matches(self.d, ev, "2026")
        d = copy.deepcopy(self.d)
        t0 = datetime.strptime(ms[cut]["at"], fmt)
        shift = datetime.now(timezone.utc).replace(tzinfo=None) - (t0 - timedelta(minutes=30))
        later = {m["id"] for m in ms[cut:]}
        d["matches"] = [m for m in d["matches"] if listed or m["id"] not in later]
        for m in d["matches"]:
            m["at"] = (datetime.strptime(m["at"], fmt) + shift).strftime(fmt)
            if m["id"] in later:
                m.update(win="", s1="", s2="")
        for t in d["tours"]:
            for k in ("start", "end"):
                t[k] = (datetime.strptime(t[k], "%Y-%m-%d") + shift).strftime("%Y-%m-%d")
        return d, ms

    def test_every_moment_of_each_event(self):
        # 경기 하나 끝날 때마다(다음 경기가 이미 올라온 경우 · 아직 안 올라온 경우 모두) 네 화면이 깨지지 않고,
        # 대회 중에 '모두 종료'·우승·탈락을 미리 말하지 않는지
        from tracker.config import KST
        from datetime import datetime
        for ev in intl.EVENTS:
            for listed in (True, False):
                n = len(intl.matches(self.d, ev, "2026"))
                for cut in range(n):
                    d, ms = self._at_moment(ev, cut, listed)
                    schedule.DATA = {**schedule.DATA, schedule.INTL: d}
                    with self.subTest(ev=ev, cut=cut, listed=listed):
                        for sec in ("", "schedule", "results", "teams"):
                            html = intl.render(ev, sec)
                        sch = intl.render(ev, "schedule")
                        self.assertNotIn("경기가 모두 종료됐어요", sch)
                        self.assertNotIn("sch-champ", intl.render(ev, "results"))
                        today = datetime.now(KST).date()
                        fin = intl.finish(d, ev, "2026", today)
                        self.assertFalse([k for k, v in fin.items() if v in ("우승", "준우승")])
                        ss = intl.stages(d, ev, "2026", today)
                        last = ss[-1] if ss else None
                        if last and last["key"] in ("group", "playin"):       # 아직 진행 중인 마지막 단계에서 '탈락' 판정은 이름
                            teams = {k for m in last["ms"] for k in (m["k1"], m["k2"])}
                            self.assertFalse([k for k, v in fin.items() if "탈락" in v and k in teams])
        schedule.DATA = {**schedule.DATA, schedule.INTL: self.d}

    def test_next_year_page_only(self):
        # 다음 해 대회 문서만 먼저 올라오면: 일정은 새 해(D-day), 결과·진출팀은 결과가 있는 가장 최근 해
        import copy
        d = copy.deepcopy(self.d)
        d["tours"].append({"page": "2027 First Stand", "name": "First Stand 2027", "start": "2027-03-15", "end": "2027-03-21", "playoff": False})
        schedule.DATA = {**schedule.DATA, schedule.INTL: d}
        try:
            self.assertIn("2027 퍼스트 스탠드 대회 일정", intl.render("fst", "schedule"))
            self.assertIn("2026 퍼스트 스탠드 결과", intl.render("fst", "results"))
            self.assertIn("2026 퍼스트 스탠드 진출팀", intl.render("fst", "teams"))
            self.assertIn("2027 퍼스트 스탠드에 끝난 경기가 없어요", intl.render("fst", "results", "2027"))
        finally:
            schedule.DATA = {**schedule.DATA, schedule.INTL: self.d}

    def test_no_data_message(self):
        schedule.DATA = {**schedule.DATA, schedule.INTL: {}}
        try:
            for ev in intl.EVENTS:
                self.assertIn("대회 일정이 아직 공개되지 않았어요", intl.render(ev, "schedule"))
                self.assertIn("대회 일정이 아직 공개되지 않았어요", intl.render(ev, "teams"))
        finally:
            schedule.DATA = {**schedule.DATA, schedule.INTL: self.d}
