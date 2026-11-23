"""상황별 점검(tools/scenarios.py): 실제 이적 상황마다 사람이 정한 정답대로 모든 화면이 보이는지.
(루시드·듀로처럼 계약 중인데 다른 팀 유력 · 딜라이트↔커리어 맞바꾸기 · 오피셜 전 리그피디아 미반영 · FA 목록 늦음 · 무산 …)"""
import os
import sys
import tempfile
import unittest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from tracker.core import db, init_db  # noqa: E402
from tracker import farm  # noqa: E402
import scenarios  # noqa: E402

TABLES = ("fa", "roster", "items", "farm_items")


class ScenarioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        farm.init()
        with db() as c:                       # 다른 시험이 쓰는 데이터는 끝나고 그대로 돌려놓음
            cls.saved = {t: [dict(r) for r in c.execute(f"SELECT * FROM {t}")] for t in TABLES}

    @classmethod
    def tearDownClass(cls):
        with db() as c:
            for t, rows in cls.saved.items():
                c.execute(f"DELETE FROM {t}")
                for r in rows:
                    c.execute(f"INSERT INTO {t}({','.join(r)}) VALUES({','.join('?' * len(r))})", tuple(r.values()))
        scenarios.reset_caches()

    def test_every_scenario(self):
        fails = scenarios.run_all(verbose=False)
        self.assertEqual(fails, [], "\n" + "\n".join(fails))


if __name__ == "__main__":
    unittest.main()
