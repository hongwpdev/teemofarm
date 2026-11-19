"""스토브리그 정리 기능: 팀별 요약 · 계약 만료 · 인기 로스터 · 소식통 적중률 · 행선지 투표 · RSS."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "stove_test.db")

from tracker import feed, share, stove, vote  # noqa: E402
from tracker.core import db, init_db  # noqa: E402

KEYS = ["hle", "t1", "geng", "dk", "kt", "ns", "bfx", "drx", "dns", "bro"]


def ago(h):
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


class StoveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        share.init()
        vote.init()
        stove._PRED["at"] = 0
        with db() as c:
            fa = [("Kiin", "Kiin", "김기인", "geng", "Top", "fa", "", "", "", "2026-11-16", ""),
                  ("Cuzz", "Cuzz", "문우찬", "kt", "Jungle", "move", "dns", "", "", "2026-11-17", ""),
                  ("VicLa", "VicLa", "이대광", "bfx", "Mid", "stay", "", "", "2027-11-15", "2026-11-16", ""),
                  ("Scout", "Scout", "이예찬", "ns", "Mid", "move", "", "Team Liquid", "", "2026-11-16", "")]
            c.executemany("INSERT INTO fa(page,nick,real,team_from,role,status,team_to,team_to_name,until,date,memo,league) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?,'lck')", fa)
            ros = [("dns", "Jungle", "Cuzz", "Cuzz", "문우찬", "2027-11-15", 1),
                   ("t1", "Mid", "Faker", "Faker", "이상혁", "2029-11-19", 0),
                   ("dk", "Top", "Siwoo", "Siwoo", "전시우", "2027-11-15", 0),
                   ("bro", "Mid", "SeTab", "SeTab", "", "", 1)]
            c.executemany("INSERT INTO roster(league,team,role,page,nick,real,until,joined) VALUES('lck',?,?,?,?,?,?,?)", ros)
            news = [("n1", "geng", "[단독] 한화생명, '기인' 김기인 영입", "국민일보", ago(5)),
                    ("n2", "dns", "[소식통] '커즈' 문우찬, 2027 시즌 DN 수퍼스에 합류 예정", "Sheep Esports", ago(50)),
                    ("n3", "kt", "[단독] '커즈' 문우찬, T1 합류 유력", "가짜뉴스", ago(60)),
                    ("n4", "t1", "T1 '페이커', 젠지전 승리…합류 후 100승", "스포츠서울", ago(3)),
                    ("n5", "dk", "[소식통] '시우' 전시우, 2027 LCK 시즌 젠지 합류 예정", "Sheep Esports", ago(2)),
                    ("n6", "lck", "[오피셜] DN 수퍼스, '커즈' 문우찬 영입", "인벤", ago(40))]
            c.executemany("INSERT INTO items(id,team,source,title,url,outlet,published,first_seen,league) "
                          "VALUES(?,?,'news',?,'https://example.com/' || ?,?,?,?, 'lck')",
                          [(i, t, ti, i, o, p, p) for i, t, ti, o, p in news])
            for i, r in enumerate(("Kiin,Canyon,Zeka,Gumayusi,Delight", "Kiin,Canyon,Zeka,Gumayusi,Delight", "Zeus,Canyon,Zeka,Gumayusi,Delight")):
                c.execute("INSERT INTO shares(code,r,n,at) VALUES(?,?,?,?)", (f"code{i}", r, "", ago(1)))

    def test_summary(self):
        s = stove.team_summary(KEYS)
        self.assertEqual([p["nick"] for p in s["dns"]["in"]], ["Cuzz"])
        self.assertEqual([p["nick"] for p in s["kt"]["out"]], ["Cuzz"])
        self.assertEqual([p["nick"] for p in s["bfx"]["stay"]], ["VicLa"])
        self.assertEqual([p["nick"] for p in s["geng"]["open"]], ["Kiin"])
        self.assertEqual(s["ns"]["out"][0]["to_name"], "Team Liquid")
        self.assertIn("SeTab", [p["nick"] for p in s["bro"]["in"]])          # LCK 밖에서 온 영입

    def test_contracts_sorted(self):
        c = stove.contracts()
        self.assertEqual(c[0]["until"][:4], "2027")
        self.assertEqual(c[-1]["nick"], "SeTab")                              # 날짜 모르면 맨 뒤

    def test_popular(self):
        p = stove.popular(KEYS)
        self.assertEqual(p["n"], 3)
        self.assertEqual(p["teams"]["hle"]["Top"][0], ("Kiin", 2))

    def test_predictions(self):
        stove._PRED["at"] = 0
        pr = stove.predictions()
        res = {(p["outlet"], p["nick"]): (p["team"], p["result"]) for p in pr}
        self.assertEqual(res[("Sheep Esports", "Cuzz")], ("dns", "hit"))
        self.assertEqual(res[("가짜뉴스", "Cuzz")], ("t1", "miss"))
        self.assertEqual(res[("국민일보", "Kiin")], ("hle", "wait"))
        self.assertEqual(res[("Sheep Esports", "Siwoo")], ("geng", "wait"))
        self.assertNotIn(("스포츠서울", "Faker"), res)                       # 경기 기사는 예측 아님
        self.assertNotIn(("인벤", "Cuzz"), res)                               # 오피셜은 예측 아님
        acc = {a["outlet"]: a for a in stove.accuracy(pr)}
        self.assertEqual(acc["Sheep Esports"]["rate"], 100)
        self.assertEqual(acc["가짜뉴스"]["rate"], 0)

    def test_vote(self):
        cid = "testbrowser01"
        self.assertEqual(vote.cast("Kiin", "hle", cid, KEYS), "")
        self.assertEqual(vote.cast("Kiin", "t1", cid, KEYS), "")              # 바꾸기
        self.assertEqual(vote.tally()["Kiin"], {"t1": 1})
        self.assertEqual(vote.mine(cid), {"Kiin": "t1"})
        self.assertNotEqual(vote.cast("Cuzz", "dns", cid, KEYS), "")          # 이미 정해진 선수
        self.assertNotEqual(vote.cast("Kiin", "nope", cid, KEYS), "")         # 없는 팀
        self.assertNotEqual(vote.cast("Kiin", "hle", "bad id!", KEYS), "")    # 잘못된 번호

    def test_rss(self):
        x = feed.rss("https://teemofarm.com", "lck")
        self.assertTrue(x.startswith("<?xml"))
        self.assertIn("[소식통]", x)
        self.assertNotIn("100승", x)
        self.assertIn("DN 수퍼스", feed.rss("https://teemofarm.com", "lck", "dns"))

    def test_discord_notify(self):
        sent = []
        orig = feed._post
        feed._post = sent.append
        try:
            with db() as c:
                c.execute("DELETE FROM meta WHERE k='discord_at'")
            self.assertEqual(feed.notify_once(), 0)          # 처음엔 지금부터(지난 기사로 도배 안 함)
            feed._meta("discord_at", ago(100))
            orig_sleep = feed.time.sleep
            feed.time.sleep = lambda s: None
            try:
                n = feed.notify_once()
            finally:
                feed.time.sleep = orig_sleep
            self.assertGreaterEqual(n, 1)
            self.assertTrue(all("<https://example.com/" in m for m in sent))
            self.assertFalse(any("100승" in m for m in sent))
            self.assertEqual(feed.notify_once(), 0)          # 같은 기사는 다시 안 보냄
        finally:
            feed._post = orig


if __name__ == "__main__":
    unittest.main()
