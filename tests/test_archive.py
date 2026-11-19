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
                  "to": "Hanwha Life Esports", "tkey": "hle"}]}


class ArchiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_all_sections_render(self):
        with mock.patch.object(archive, "get", lambda y: REC):
            for sec in ("", "roster", "fa", "schedule"):
                with self.subTest(sec=sec):
                    page = views.render_archive("lck", sec, 2026)
                    self.assertIn("</html>", page)
            self.assertIn("Old Team", views.render_archive("lck", "schedule", 2026))   # LCK 밖 팀 이름도 표시
            self.assertIn("👑", views.render_archive("lck", "", 2026))


if __name__ == "__main__":
    unittest.main()
