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


if __name__ == "__main__":
    unittest.main()
