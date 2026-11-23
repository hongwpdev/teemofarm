"""사람별 상태 스냅숏: 모든 화면 · 독버섯 판 · 데이터 점검이 같은 시점의 계산을 읽는지."""
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker import farm, integrity, rumor, state  # noqa: E402
from tracker.core import db, init_db  # noqa: E402
from tracker.web import views  # noqa: E402

FA_COLS = "page,nick,real,team_from,role,status,team_to,team_to_name,until,date,memo"


def put(fa=(), roster=()):
    with db() as c:
        c.execute("DELETE FROM fa")
        c.execute("DELETE FROM roster")
        c.executemany(f"INSERT INTO fa({FA_COLS}) VALUES(?,?,?,?,?,?,?,?,?,?,?)", fa)
        c.executemany("INSERT INTO roster(league,team,role,page,nick,real,until,joined) VALUES('lck',?,?,?,?,?,?,?)", roster)


class SnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        farm.init()

    def setUp(self):
        state.reset()

    def tearDown(self):
        put()
        state.reset()

    def test_same_key_reuses_one_calculation(self):
        put([("SnapA", "SnapA", "", "kt", "Top", "fa", "", "", "", "2026-11-18", "")])
        with mock.patch.object(rumor, "_both", wraps=rumor._both) as rm:
            a = state.get()
            b = state.get()
            views.render_fa("lck")
            views.render_summary("lck")
            views.roster_rows()
            views.fa_rows()
            views.people()
            views.render_roster("lck")
            integrity.check()
        self.assertIs(a, b)
        self.assertEqual(rm.call_count, 2)          # FA 선수 한 번 + 계약 중 선수 한 번: 화면 여러 개와 점검이 같이 씀

    def test_data_change_rebuilds_everything_together(self):
        put([("SnapB", "SnapB", "", "kt", "Top", "fa", "", "", "", "2026-11-18", "")])
        a = state.get()
        self.assertIn("SnapB", [r["page"] for r in views.fa_rows()])
        put([("SnapB", "SnapB", "", "kt", "Top", "move", "t1", "", "", "2026-11-19", "")],
            [("t1", "Top", "SnapB", "SnapB", "", "", 0)])
        b = state.get()
        self.assertNotEqual(a["key"], b["key"])
        # 바로 다음 요청부터 FA 표 · 로스터 · 팀별이 모두 새 데이터(한쪽만 옛것인 순간이 없음)
        self.assertEqual([r["status"] for r in views.fa_rows() if r["page"] == "SnapB"], ["move"])
        self.assertIn("SnapB", [r["page"] for r in views.roster_rows()])
        self.assertIs(state.get(), b)

    def test_old_snapshot_expires(self):
        put()
        a = state.get()
        with mock.patch.object(state.time, "time", return_value=a["at"] + state.MAX_AGE + 1):
            b = state.get()
        self.assertIsNot(a, b)                      # 기사 기간(2주) 경계를 넘는 것도 반영되게

    def test_farm_and_integrity_read_the_snapshot(self):
        put()
        fake = {**state.get(), "rumors": {}, "leaving": {}, "off": {}}
        with mock.patch.object(state, "get", return_value=fake) as g:
            farm.sync(force=True)
            integrity.check()
        self.assertGreaterEqual(g.call_count, 2)


class PrecedenceTest(unittest.TestCase):
    """무작위 대량 시험(tools/fuzz_data.py)에서 찾은 화면 모순."""
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        state.reset()

    def tearDown(self):
        put()
        state.reset()

    def test_roster_ahead_of_fa_list(self):
        # 도란형: 로스터엔 DK, FA 목록은 T1 미정 → 모든 화면이 DK 이적 확정(이적 시장 '미정' · 팀별 'DK 영입'으로 엇갈리던 문제)
        put([("PrecA", "PrecA", "", "t1", "Top", "fa", "", "", "", "2026-11-17", "")],
            [("dk", "Top", "PrecA", "PrecA", "", "2027-11-30", 1)])
        snap = state.get()
        self.assertEqual([(r["status"], r["team_to"]) for r in snap["fa"] if r["page"] == "PrecA"], [("move", "dk")])
        self.assertEqual([r["status"] for r in snap["fa_raw"] if r["page"] == "PrecA"], ["fa"])   # 운영 알림용 원래 목록
        html = views.render_fa("lck")
        self.assertIn('data-s="move"', html.split('class="fa-row" data-page="PrecA"')[1].split("</li>")[0])
        sm = views.render_summary("lck")
        t1 = sm[sm.index('id="m-t1"'):].split("</article>")[0]
        self.assertNotIn('<div class="sl open">', t1)

    def test_counts_same_everywhere(self):
        # 소식 화면·오른쪽 요약 숫자(fa_counts)가 이적 시장 버튼 숫자와 같음(예전엔 DB 그대로 세서 달랐음)
        put([("PrecB", "PrecB", "", "t1", "Top", "fa", "", "", "", "2026-11-17", ""),
             ("PrecC", "PrecC", "", "kt", "Mid", "stay", "kt", "", "", "2026-11-17", "")],
            [("dk", "Top", "PrecB", "PrecB", "", "2027-11-30", 1)])
        import re
        html = views.render_fa("lck")
        btn = {k: int(v) for k, v in re.findall(r'>(확정|잔류|미정) <b>(\d+)</b></button>', html)}
        cnt = views.fa_counts()
        self.assertEqual(btn, {"확정": cnt.get("move", 0), "잔류": cnt.get("stay", 0), "미정": cnt.get("fa", 0)})
        self.assertEqual(cnt.get("move"), 1)


class RumorBucketTest(unittest.TestCase):
    """'유력인데 왜 미정이야': 이적 시장 네 칸(확정·잔류·유력·미정)은 서로 겹치지 않고, 팀별·요약 숫자도 같음."""
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        state.reset()

    def tearDown(self):
        put()
        with db() as c:
            c.execute("DELETE FROM items WHERE id LIKE 'bk%'")
        state.reset()

    def test_buckets(self):
        import re
        from datetime import datetime, timezone
        put([("BkA", "Zeus", "", "hle", "Top", "fa", "", "", "", "2026-11-17", ""),
             ("BkB", "Clear", "", "bfx", "Top", "fa", "", "", "", "2026-11-17", ""),
             ("BkC", "Kingen", "", "ns", "Top", "stay", "ns", "", "", "2026-11-17", "")])
        now = datetime.now(timezone.utc).isoformat()
        with db() as c:
            c.execute("INSERT INTO items(id,team,source,title,url,outlet,published,first_seen,league) VALUES(?,?,?,?,?,?,?,?,'lck')",
                      ("bk1", "", "news", "한화생명 떠난 '제우스', 친정 T1 복귀 유력", "https://e.com/bk1", "위키트리", now, now))
        state.reset()
        html = views.render_fa("lck")
        btn = {k: int(v) for k, v in re.findall(r'>(전체|확정|잔류|미정|유력) <b>(\d+)</b></button>', html)}
        self.assertEqual(btn, {"전체": 3, "확정": 0, "잔류": 1, "미정": 1, "유력": 1})
        self.assertEqual(views.fa_counts(), {"stay": 1, "fa": 1, "rm": 1})
        sm = views.render_summary("lck")
        self.assertIn("<span><b>1</b>유력</span><span><b>1</b>미정</span>", sm)
        hle = sm[sm.index('id="m-hle"'):].split("</article>")[0]
        self.assertNotIn('<div class="sl open">', hle)                    # 제우스는 HLE 카드에서 '미정'이 아니라
        self.assertIn("→ T1", hle)                                         # '유력 → T1'
        self.assertIn('<em>유력</em>', hle)
        t1 = sm[sm.index('id="m-t1"'):].split("</article>")[0]
        self.assertIn(">Zeus<", t1)


class FillRosterLagTest(unittest.TestCase):
    def test_moved_player_not_on_two_teams(self):
        # 이적 확정(FA 목록)인데 리그피디아 로스터엔 옛 팀에 남아 있으면(계약 끝남) 옛 팀 줄을 빼고 새 팀에만
        from tracker.fa import fill_from_fa
        fa = [("LagA", "LagA", "", "kt", "Top", "move", "dk", "", "", "2026-11-18", "")]
        rows = fill_from_fa([("lck", "kt", "Top", "LagA", "LagA", "", "", 0)], fa, {"kt", "dk"})
        self.assertEqual([(r[1], r[3]) for r in rows], [("dk", "LagA")])
        # 옛 팀 계약이 남아 있으면 로스터가 우선(그대로 두고 새 팀에 넣지 않음)
        rows = fill_from_fa([("lck", "kt", "Top", "LagA", "LagA", "", "2027-11-30", 0)], fa, {"kt", "dk"})
        self.assertEqual([(r[1], r[3]) for r in rows], [("kt", "LagA")])


if __name__ == "__main__":
    unittest.main()
