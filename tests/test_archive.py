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
            for sec in ("", "roster", "fa", "schedule"):
                with self.subTest(sec=sec):
                    page = views.render_archive("lck", sec, 2026)
                    self.assertIn("</html>", page)
            self.assertIn("Old Team", views.render_archive("lck", "schedule", 2026))   # LCK 밖 팀 이름도 표시
            self.assertIn('class="card champ"', views.render_archive("lck", "", 2026))   # 우승 카드

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
