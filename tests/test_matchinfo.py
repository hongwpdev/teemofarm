"""경기 상세: 리그피디아 응답(가짜)을 화면용 모양으로 잘 바꾸는지, 저장해 두고 다시 받지 않는지."""
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker import champs, matchinfo  # noqa: E402
from tracker.core import init_db  # noqa: E402

GAME = {"GameId": "M_1", "N": "1", "Team1": "Gen.G", "Team2": "T1", "Winner": "2", "Gamelength": "31:04", "Patch": "26.16",
        "VOD": "https://youtu.be/x", "Team1Picks": "Jarvan IV,Ahri", "Team2Picks": "Nunu & Willump", "Team1Bans": "Ezreal",
        "Team2Bans": "", "Team1Kills": "5", "Team2Kills": "12", "Team1Gold": "50000", "Team2Gold": "60000",
        "Team1Towers": "2", "Team2Towers": "9", "Team1Dragons": "1", "Team2Dragons": "3", "Team1Barons": "0", "Team2Barons": "1",
        "DT": "2020-01-01 08:00:00"}
PLAYERS = [{"GameId": "M_1", "Link": n, "Team": t, "Role": r, "Champion": "Ahri", "Kills": "1", "Deaths": "2", "Assists": "3",
            "CS": "200", "Gold": "10000", "DamageToChampions": "15000", "Side": ""}
           for t in ("Gen.G", "T1") for n, r in (("S", "Support"), ("A", "Top"), ("B", "Jungle"), ("C", "Mid"), ("D", "Bot"))]


class MatchInfoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        matchinfo.init()
        champs.DATA = {"ver": "1.0", "at": 0, "map": {"jarvaniv": {"id": "JarvanIV", "ko": "자르반 4세"},
                                                      "ahri": {"id": "Ahri", "ko": "아리"}}}

    def test_fetch_shape_and_cache(self):
        calls = []

        def fake(gap, **kw):
            calls.append(kw["tables"])
            return [GAME] if kw["tables"] == "ScoreboardGames" else PLAYERS
        with mock.patch.object(matchinfo, "cargo", fake):
            d = matchinfo.get("M")
            g = d["games"][0]
            self.assertEqual(g["win"], "red")
            self.assertEqual([c["ko"] for c in g["blue"]["picks"]], ["자르반 4세", "아리"])
            self.assertTrue(g["blue"]["picks"][0]["img"].endswith("/JarvanIV.png"))
            self.assertEqual(g["red"]["picks"][0]["img"], "")           # 모르는 챔피언: 이름만
            self.assertEqual(g["red"]["bans"], [])
            self.assertEqual([p["role"] for p in g["blue"]["players"]], ["Top", "Jungle", "Mid", "Bot", "Support"])
            self.assertEqual(g["red"]["dragons"], 3)
            self.assertTrue(matchinfo._is_final(d))                      # 오래전 경기 + 선수 10명 → 다시 안 받음
            n = len(calls)
            matchinfo.get("M")
            self.assertEqual(len(calls), n)


if __name__ == "__main__":
    unittest.main()
