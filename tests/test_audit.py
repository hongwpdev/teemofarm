"""운영 점검 주소: 못 읽은 기사 모으기(/api/rumor-audit) · 지난 기록 진행 상황(/api/history)."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker import archive, intl_hist, rumor, rumor_audit  # noqa: E402
from tracker.core import db, init_db  # noqa: E402


class RumorAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_collects_unread(self):
        now = datetime.now(timezone.utc)
        news = [{"title": t, "url": f"https://e.com/{i}", "outlet": "인벤", "published": (now - timedelta(hours=i)).isoformat()}
                for i, t in enumerate([
                    "[단독] 한화생명, '기인' 김기인 영입",               # 읽음(한화생명)
                    "'기인', 새 시즌 거취 결정 임박",                     # 이적 말은 있는데 행선지가 없음 → 확인 후보
                    "젠지 '기인', T1전 펜타킬",                           # 이적 말 없음(경기 기사) → 안 셈
                    "한화생명 '기인' 영입 무산"])]                         # 무산: 행선지가 없는 게 정답 → 안 셈
        fa = [{"page": "Kiin", "nick": "Kiin", "team_from": "geng", "status": "fa"}]
        with mock.patch.object(rumor, "_recent_news", lambda: news):
            rumor_audit.init()
            with db() as c:
                c.execute("DELETE FROM rumor_audit")
            self.assertTrue(rumor_audit.record(fa, [], force=True))
        rep = rumor_audit.report()
        self.assertEqual((rep["pairs"], rep["read"], rep["unread"]), (2, 1, 1))
        self.assertEqual(rep["read_rate"], 0.5)
        self.assertEqual([x["title"] for x in rep["unread_list"]], ["'기인', 새 시즌 거취 결정 임박"])

    def test_runs_at_most_every_five_minutes(self):
        with mock.patch.object(rumor, "_recent_news", lambda: []):
            rumor_audit._RUN["at"] = 0.0
            self.assertTrue(rumor_audit.record([], []))
            self.assertFalse(rumor_audit.record([], []))           # 방금 돌았음


class HistoryStatusTest(unittest.TestCase):
    def test_lck_status_all_years(self):
        with mock.patch.object(archive, "current_season", lambda today=None: 2027), mock.patch.dict(
                archive._CACHE, {2019: {"stages": [{}], "champions": [{}, {}], "tours": [], "missing": []}}, clear=True):
            st = archive.status()
        self.assertEqual(len(st), 15)
        row = next(x for x in st if x["year"] == 2019)
        self.assertEqual((row["ready"], row["champions"]), (True, 2))
        self.assertFalse(next(x for x in st if x["year"] == 2012)["ready"])

    def test_intl_status(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "intl_hist_index.json"), "w", encoding="utf-8") as f:
            json.dump({"at": 0, "rows": [{"OverviewPage": "Season 1 World Championship", "DateStart": "2011-06-18"},
                                         {"OverviewPage": "2016 Mid-Season Invitational", "DateStart": "2016-05-04"}]}, f)
        with open(os.path.join(d, "intl_hist_worlds_2011.json"), "w", encoding="utf-8") as f:
            json.dump({"complete": True, "matches": [{}] * 21, "rosters": {}}, f)
        with mock.patch.object(intl_hist, "_DIR", d), mock.patch.dict(intl_hist._STATE, {"index": None}), \
                mock.patch.object(intl_hist, "_live_years", lambda: set()):
            intl_hist._MEM["files"].clear()
            st = intl_hist.status()
            intl_hist._MEM["files"].clear()
        self.assertEqual([(x["ev"], x["year"], x["complete"], x["matches"]) for x in st],
                         [("msi", "2016", False, 0), ("worlds", "2011", True, 21)])


if __name__ == "__main__":
    unittest.main()
