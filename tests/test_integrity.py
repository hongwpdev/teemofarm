"""데이터 정합성: 같은 사람이 화면마다 다르게 보이지 않게(코치/감독, 미정/확정, 두 줄·두 팀)."""
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker import integrity  # noqa: E402
from tracker.core import db, init_db  # noqa: E402
from tracker.fa import classify_fa  # noqa: E402

FA_COLS = "page,nick,real,team_from,role,status,team_to,team_to_name,until,date,memo"


def put(fa=(), roster=()):
    with db() as c:
        c.execute("DELETE FROM fa")
        c.execute("DELETE FROM roster")
        c.executemany(f"INSERT INTO fa({FA_COLS}) VALUES(?,?,?,?,?,?,?,?,?,?,?)", fa)
        c.executemany("INSERT INTO roster(league,team,role,page,nick,real,until,joined) VALUES('lck',?,?,?,?,?,?,?)", roster)


class IntegrityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def tearDown(self):
        put()                           # 다른 테스트가 같은 DB를 쓰므로 비워 둠

    def test_clean(self):
        put([("Kiin", "Kiin", "", "geng", "Top", "fa", "", "", "", "2026-11-17", "")],
            [("dk", "Head Coach", "cvMax", "cvMax", "", "", 0)])
        self.assertEqual(integrity.check(), [])

    def test_same_person_two_rows(self):
        # 리그피디아에 대소문자만 다른 문서 둘('cvMax'·'CvMax') → 감독/코치, 잔류/미정이 함께 보였던 문제
        put([("cvMax", "cvMax", "", "dk", "Head Coach", "stay", "dk", "", "", "2026-11-19", "재계약"),
             ("CvMax", "cvMax", "김대호", "dk", "Coach", "fa", "", "", "", "2026-11-16", "계약 만료")],
            [("dk", "Head Coach", "cvMax", "cvMax", "", "", 0)])
        bad = integrity.check()
        self.assertTrue(any("2줄" in b for b in bad), bad)

    def test_old_duplicate_cleaned_on_start(self):
        put([("cvMax", "cvMax", "", "dk", "Head Coach", "stay", "dk", "", "", "2026-11-19", "재계약"),
             ("CvMax", "cvMax", "김대호", "dk", "Coach", "fa", "", "", "", "2026-11-16", "계약 만료")])
        init_db()                       # 서버가 켜질 때 정리
        with db() as c:
            rows = c.execute("SELECT page, status FROM fa").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("cvMax", "stay")])

    def test_fa_and_roster_disagree(self):
        put([("Zeus", "Zeus", "", "hle", "Top", "move", "t1", "", "", "2026-11-19", "")],
            [("hle", "Top", "Zeus", "Zeus", "", "2027-11-30", 0)])
        self.assertTrue(any("이적 확정인데 로스터엔 hle" in b for b in integrity.check()))

    def test_one_person_two_teams(self):
        put([], [("hle", "Top", "Zeus", "Zeus", "", "", 0), ("t1", "Top", "Zeus2", "Zeus", "", "", 0)])
        self.assertTrue(any("2곳" in b for b in integrity.check()))

    def test_classify_merges_case_variant_pages(self):
        rc = [{"Direction": "Leave", "Player": "cvMax", "Team": "Dplus KIA", "Role": "Head Coach", "D": "2026-11-17"},
              {"Direction": "Join", "Player": "cvMax", "Team": "Dplus KIA", "Role": "Head Coach", "D": "2026-11-19"}]
        exp = [{"P": "CvMax", "Team": "Dplus KIA", "Role": "Coach", "Contract": "2026-11-16", "N": "김대호", "ID": "cvMax"}]
        rows = classify_fa(rc, exp, [{"P": "cvMax", "ID": "cvMax", "Team": "Dplus KIA", "Contract": "2027-11-30", "N": ""}], "2026-11-20")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][5], "stay")


    def test_fa_table_lags_behind_roster(self):
        # 도란: 로스터엔 DK(영입)인데 리그피디아 FA 목록은 아직 T1 미정 → 알림 대상
        put([("DoranI", "DoranI", "", "t1", "Top", "fa", "", "", "", "2026-11-17", "")],
            [("dk", "Top", "DoranI", "DoranI", "", "", 1)])
        self.assertTrue(any("FA 목록은 미정인데 로스터엔 dk" in p for p in integrity.check()))

    def test_fa_rumor_for_signed_player(self):
        from datetime import datetime, timezone
        from tracker.core import save
        put([("Doran", "Doran", "", "t1", "Top", "fa", "", "", "", "2026-11-17", "")],
            [("dk", "Top", "Doran", "Doran", "", "", 1)])
        save([{"id": "news:dj1", "team": "lck", "source": "news", "title": "[단독] '도란' 최현준, 한화생명 합류 유력",
               "url": "https://example.com/dj", "outlet": "OSEN", "published": datetime.now(timezone.utc).isoformat()}])
        try:
            # 로스터 > FA 목록: 스냅숏에서 DK 이적 확정이라 'FA 유력(한화생명)'이 아예 안 생김(모든 화면 같은 말), 운영 알림만 남음
            from tracker import state
            state.reset()
            snap = state.get()
            self.assertEqual([(r["status"], r["team_to"]) for r in snap["fa"] if r["page"] == "Doran"], [("move", "dk")])
            self.assertNotIn("Doran", snap["rumors"])
            probs = integrity.check()
            self.assertFalse(any("FA 'hle 유력'" in p for p in probs))
            self.assertTrue(any("FA 목록은 미정인데 로스터엔 dk" in p for p in probs))
        finally:
            with db() as c:
                c.execute("DELETE FROM items WHERE id='news:dj1'")


class FillRosterTest(unittest.TestCase):
    def test_resigned_and_moved_fill_roster(self):
        from tracker.fa import fill_from_fa
        R = lambda team, role, page, until="2027-11-30", joined=0: ("lck", team, role, page, page, "", until, joined)
        F = lambda page, frm, role, st, to="", memo="": (page, page, "", frm, role, st, to, "", "", "2026-11-18", memo)
        rows = [R("dk", "Top", "Doran", "", 1), R("bfx", "Head Coach", "Rather")]
        fa = [F("ShowMaker", "dk", "Mid", "stay"), F("Smash", "dk", "Bot", "stay"),           # 재계약했는데 로스터에서 빠진 선수
              F("Doran", "t1", "Top", "move", "dk"),                                         # 이미 있음 → 그대로
              F("Raptor", "bfx", "Jungle", "move", "kt"),                                    # 이적 확정 → 새 팀에
              F("Lyn", "geng", "Coach", "move", "ns"),                                       # 코치는 칸 없음
              F("Edo", "bfx", "Head Coach", "stay", memo="보직 변경"),                       # 보직 변경은 감독 칸에 안 넣음
              F("Zeus", "hle", "Top", "fa")]                                                 # 미정은 안 넣음
        out = fill_from_fa(rows, fa, {"dk", "kt", "ns", "bfx", "hle", "t1", "geng"})
        got = sorted((r[1], r[2], r[3], r[7]) for r in out)
        self.assertEqual(got, [("bfx", "Head Coach", "Rather", 0), ("dk", "Bot", "Smash", 0), ("dk", "Mid", "ShowMaker", 0),
                               ("dk", "Top", "Doran", 1), ("kt", "Jungle", "Raptor", 1)])


class AlertTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_new_problems_only_once(self):
        from unittest import mock
        from tracker import alerts
        sent = []
        with mock.patch.object(alerts, "WEBHOOK", "https://discord.invalid/hook"), \
             mock.patch.object(alerts, "_post", side_effect=sent.append):
            alerts._meta(alerts.KEY, "[]")
            self.assertEqual(alerts.integrity_alert(["A 문제", "B 문제"]), ["A 문제", "B 문제"])
            self.assertEqual(len(sent), 1)
            self.assertIn("새 문제 2건", sent[0])
            self.assertEqual(alerts.integrity_alert(["A 문제", "B 문제"]), [])      # 같은 문제는 다시 안 보냄
            self.assertEqual(len(sent), 1)
            self.assertEqual(alerts.integrity_alert(["A 문제"]), [])               # B 해결
            self.assertEqual(alerts.integrity_alert(["A 문제", "B 문제"]), ["B 문제"])   # B가 다시 생기면 다시
            self.assertEqual(len(sent), 2)
        with mock.patch.object(alerts, "WEBHOOK", ""), mock.patch.object(alerts, "_post") as p:
            alerts.integrity_alert(["C 문제"])                                      # 웹훅이 없으면 보내지 않음(로그만)
            p.assert_not_called()


if __name__ == "__main__":
    unittest.main()
