"""독버섯 심기(tracker/farm.py): 결과 판정 · 한 사람 한 번 · 마감 · 역배."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker import farm  # noqa: E402
from tracker.core import db, init_db  # noqa: E402

COLS = "id,kind,page,nick,a,b,a_label,b_label,title,url,outlet,published,lock_at,created,tag"


def item(iid, kind="rumor", page="Zeus", a="hle", b="t1", lock=""):
    with db() as c:
        c.execute(f"INSERT OR REPLACE INTO farm_items({COLS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (iid, kind, page, page, a, b, "O", "X", "t", "u", "o", "2026-11-19T00:00:00+00:00", lock, "2026-11-19", "유력"))


def fa(page, status, frm="hle", to=""):
    with db() as c:
        c.execute("DELETE FROM fa WHERE page=?", (page,))
        c.execute("INSERT INTO fa(page,nick,real,team_from,role,status,team_to,team_to_name,until,date,memo) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (page, page, "", frm, "Top", status, to, "", "", "2026-11-19", ""))


def result(iid):
    with db() as c:
        return c.execute("SELECT result FROM farm_items WHERE id=?", (iid,)).fetchone()[0]


class FarmTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        farm.init()

    def tearDown(self):
        with db() as c:
            c.execute("DELETE FROM farm_items")
            c.execute("DELETE FROM farm_picks")
            c.execute("DELETE FROM fa")
            c.execute("DELETE FROM roster")
        farm._SENT.clear()

    def test_rumor_result(self):
        item("rm:Zeus:t1:m"); item("rm:Kiin:hle:m", page="Kiin", a="geng", b="hle"); item("rm:Bon0:ns:s", page="Bon0", a="ns", b="ns")
        fa("Zeus", "fa"); fa("Kiin", "move", "geng", "t1"); fa("Bon0", "stay", "ns")
        farm.sync(force=True)
        self.assertIsNone(result("rm:Zeus:t1:m"))           # 아직 미정이면 결과 없음
        self.assertEqual(result("rm:Kiin:hle:m"), "x")       # 다른 팀으로 갔으면 X
        self.assertEqual(result("rm:Bon0:ns:s"), "o")        # 잔류 유력 → 잔류면 O
        fa("Zeus", "move", "hle", "t1")
        farm.sync(force=True)
        self.assertEqual(result("rm:Zeus:t1:m"), "o")

    def test_mover_result(self):
        # 계약 중 선수: 로스터가 그 팀으로 바뀌면 O
        item("mv:Career:hle", page="Career", a="dk", b="hle")
        with db() as c:
            c.execute("INSERT INTO roster(league,team,role,page,nick,real,until,joined) VALUES('lck','hle','Support','Career','Career','','',1)")
        farm.sync(force=True)
        self.assertEqual(result("mv:Career:hle"), "o")

    def test_one_pick_per_person_and_closed(self):
        item("rm:Zeus:t1:m"); fa("Zeus", "fa")
        self.assertEqual(farm.plant("rm:Zeus:t1:m", "o", "abcdefgh12")[0], "")
        self.assertEqual(farm.plant("rm:Zeus:t1:m", "x", "abcdefgh12")[0], "이미 심었어요")     # 바꿀 수 없음
        self.assertNotEqual(farm.plant("rm:Zeus:t1:m", "a", "abcdefgh13")[0], "")              # O/X 판에 팀 고르기 불가
        self.assertNotEqual(farm.plant("rm:Zeus:t1:m", "o", "bad id")[0], "")                  # 잘못된 브라우저 번호
        fa("Zeus", "move", "hle", "t1"); farm.sync(force=True)
        self.assertEqual(farm.plant("rm:Zeus:t1:m", "o", "abcdefgh14")[0], "이미 결과가 났거나 마감됐어요")

    def test_called_off_closes_planting(self):
        # 더 새 기사가 그 행선지를 '무산'이라 하면 새로 못 심음(결과는 계속 리그피디아 기준)
        from tracker import rumor
        from tracker.core import save
        fa("Zeus", "fa")
        save([{"id": "news:z1", "team": "lck", "source": "news", "title": "[단독] '제우스' 최우제, T1 복귀 유력", "url": "u1",
               "outlet": "o", "published": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()}])
        rumor._CACHE.clear(); farm.sync(force=True)
        self.assertIn("rm:Zeus:t1:m", [it["id"] for it in farm.board([])["open"]])
        save([{"id": "news:z2", "team": "lck", "source": "news", "title": "T1, '제우스' 최우제 영입 무산", "url": "u2",
               "outlet": "o", "published": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}])
        rumor._CACHE.clear(); farm.sync(force=True)
        self.assertNotIn("rm:Zeus:t1:m", [it["id"] for it in farm.board([])["open"]])
        self.assertEqual(farm.plant("rm:Zeus:t1:m", "o", "abcdefgh15")[0], "이미 결과가 났거나 마감됐어요")
        self.assertIsNone(result("rm:Zeus:t1:m"))
        with db() as c:
            c.execute("DELETE FROM items WHERE id IN ('news:z1','news:z2')")
        rumor._CACHE.clear()

    def test_official_closes_planting(self):
        # 오피셜 기사(발표)가 나면 새로 못 심고 목록에서도 빠짐. 이미 심은 사람은 리그피디아 반영 때 판정
        item("rm:Kiin:hle:m", page="Kiin", a="geng", b="hle"); fa("Kiin", "fa")
        self.assertEqual(farm.plant("rm:Kiin:hle:m", "o", "earlybird01")[0], "")
        with db() as c:
            c.execute("UPDATE farm_items SET tag='발표' WHERE id='rm:Kiin:hle:m'")
        self.assertEqual(farm.plant("rm:Kiin:hle:m", "o", "latecomer01")[0], "이미 결과가 났거나 마감됐어요")
        b = farm.board(["rm:Kiin:hle:m"])
        self.assertNotIn("rm:Kiin:hle:m", [x["id"] for x in b["open"]])
        self.assertFalse(b["mine"]["rm:Kiin:hle:m"]["open"])
        fa("Kiin", "move", "geng", "hle"); farm.sync(force=True)
        self.assertEqual(result("rm:Kiin:hle:m"), "o")

    def test_match_locks_ten_minutes_before(self):
        soon = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        item("m:1", kind="match", lock=soon)
        later = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        item("m:2", kind="match", lock=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
        self.assertEqual(farm.plant("m:1", "a", "abcdefgh15")[0], "")
        self.assertEqual(farm.plant("m:2", "a", "abcdefgh15")[0], "이미 결과가 났거나 마감됐어요")
        self.assertTrue(later)

    def test_underdog_bonus(self):
        item("rm:Zeus:t1:m"); fa("Zeus", "fa")
        for i in range(9):                                     # O 9명
            farm.plant("rm:Zeus:t1:m", "o", f"voter{i:04d}x")
        err, _, bonus = farm.plant("rm:Zeus:t1:m", "x", "voterX0001")    # 9명뿐(10명 미만)이라 역배 아님
        self.assertEqual(err, "")
        self.assertFalse(bonus)
        farm.plant("rm:Zeus:t1:m", "o", "voter0009x")
        err, _, bonus = farm.plant("rm:Zeus:t1:m", "x", "voterX0002")    # 11명 중 X 1명(9%) → 역배
        self.assertTrue(bonus)
        err, _, bonus = farm.plant("rm:Zeus:t1:m", "o", "voter0010x")    # 다수 쪽은 아님
        self.assertFalse(bonus)

    def test_season_matches(self):
        # 1월 개막 대비: 일정 데이터에 다가오는 LCK 경기가 들어오면 같은 카드에 '경기' 판이 먼저 나오고,
        # 시작 10분 전 마감, 끝나면 이긴 팀으로 판정(유력 판과 같은 심기·수확 흐름)
        from tracker import schedule
        now = datetime.now(timezone.utc)
        fmt = lambda d: d.strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731
        old = schedule.DATA
        schedule.DATA = {"lck": {"matches": [
            {"id": "G1", "page": "LCK/2027 Season/Cup", "tour": "LCK 컵", "at": fmt(now + timedelta(hours=20)),
             "t1": "T1", "k1": "t1", "t2": "Gen.G", "k2": "geng", "win": ""},
            {"id": "G0", "page": "LCK/2027 Season/Cup", "tour": "LCK 컵", "at": fmt(now - timedelta(hours=3)),
             "t1": "T1", "k1": "t1", "t2": "Dplus KIA", "k2": "dk", "win": "2"}]}}
        try:
            item("rm:Zeus:t1:m"); fa("Zeus", "fa")
            farm.sync(force=True)
            b = farm.board([])
            self.assertEqual(b["open"][0]["id"], "m:G1")                    # 경기 판이 맨 앞
            self.assertEqual((b["open"][0]["a_short"], b["open"][0]["b_short"]), ("T1", "GEN"))
            self.assertTrue(b["open"][0]["lock_at"] < b["open"][0]["published"])
            self.assertEqual(farm.plant("m:G1", "a", "seasonfan01")[0], "")
            self.assertNotEqual(farm.plant("m:G1", "o", "seasonfan02")[0], "")    # 경기 판은 팀(a/b)만
            self.assertEqual(result("m:G0"), "b")                              # 끝난 경기: 이긴 쪽
            self.assertNotIn("m:G0", [x["id"] for x in b["open"]])
        finally:
            schedule.DATA = old

    def test_ratio_hidden_until_planted(self):
        # 심기 전엔 참여 인원만, 심은 브라우저에만 비율(서버가 숨김) · 심은 쪽은 my_picks로 되살릴 수 있게
        item("rm:Zeus:t1:m"); fa("Zeus", "fa")
        farm.plant("rm:Zeus:t1:m", "o", "someone001")
        b = farm.board([], "viewer0001")
        z = next(x for x in b["open"] if x["id"] == "rm:Zeus:t1:m")
        self.assertEqual((z["n"], z["tally"]), (1, {}))
        farm.plant("rm:Zeus:t1:m", "x", "viewer0001")
        b = farm.board([], "viewer0001")
        z = next(x for x in b["open"] if x["id"] == "rm:Zeus:t1:m")
        self.assertEqual(z["tally"], {"o": 1, "x": 1})
        self.assertEqual(b["my_picks"], {"rm:Zeus:t1:m": "x"})

    def test_board_shows_mine_after_result(self):
        item("rm:Zeus:t1:m"); fa("Zeus", "move", "hle", "t1")
        farm.sync(force=True)
        b = farm.board(["rm:Zeus:t1:m"])
        self.assertEqual(b["mine"]["rm:Zeus:t1:m"]["result"], "o")
        self.assertNotIn("rm:Zeus:t1:m", [x["id"] for x in b["open"]])


if __name__ == "__main__":
    unittest.main()


class FarmIntlTest(unittest.TestCase):
    """국제전: 일정에 잡힌 경기 중 LCK 팀이 나오는 것만 판으로(코드 수정 없이 대회가 바뀌어도)."""
    @classmethod
    def setUpClass(cls):
        init_db()
        farm.init()

    def tearDown(self):
        from tracker import schedule
        schedule.DATA = {}
        with db() as c:
            c.execute("DELETE FROM farm_items")

    def test_intl_matches_with_lck_team(self):
        from tracker import schedule
        at = (datetime.now(timezone.utc) + timedelta(hours=20)).strftime("%Y-%m-%d %H:%M:%S")

        def m(mid, t1, k1, t2, k2):
            return {"id": mid, "page": "2027 Mid-Season Invitational", "tour": "MSI 2027", "at": at,
                    "t1": t1, "k1": k1, "t2": t2, "k2": k2, "win": ""}
        schedule.DATA = {"intl": {"matches": [m("msi1", "Bilibili Gaming", "bilibili-gaming", "T1", "t1"),
                                              m("msi2", "G2 Esports", "g2-esports", "Team Liquid", "team-liquid")],
                                  "teams": {"bilibili-gaming": {"name": "Bilibili Gaming", "short": "BLG"}}}}
        farm.sync(force=True)
        ids = {it["id"]: it for it in farm.board([])["open"]}
        self.assertIn("m:msi1", ids)                         # LCK 팀(T1)이 나오는 국제전 경기
        self.assertNotIn("m:msi2", ids)                      # LCK 팀이 없는 경기는 판 없음
        self.assertEqual((ids["m:msi1"]["a_short"], ids["m:msi1"]["b_short"]), ("BLG", "T1"))
        # 결과가 나면 판정
        schedule.DATA["intl"]["matches"][0]["win"] = "2"
        farm.sync(force=True)
        self.assertEqual(result("m:msi1"), "b")


class FarmViewTest(unittest.TestCase):
    """소식 목록 → 판 바로가기 · 격전지 표시(화면 쪽 규칙)."""
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_jump_matches_same_story_only(self):
        from tracker.web.views import _farm_jumper
        it = {"id": "rm:Zeus:t1:m", "kind": "rumor", "nick": "Zeus", "a": "hle", "b": "t1",
              "title": "[단독] '제우스' 최우제, T1 복귀 유력"}
        jump = _farm_jumper([it, {"id": "m:1", "kind": "match", "nick": "", "a": "t1", "b": "geng", "title": "LCK"}])
        self.assertEqual(jump("[단독]  '제우스' 최우제,T1 복귀 유력", "rumor"), it["id"])         # 띄어쓰기만 다른 같은 제목
        self.assertEqual(jump("[소식통] '제우스' 최우제, T1과 3년 계약 합의", "rumor"), it["id"])   # 다른 매체의 같은 소식
        self.assertEqual(jump("한화생명, '제우스'와 재계약 임박", "rumor"), "")                    # 같은 선수라도 다른 방향
        self.assertEqual(jump("T1, '제우스' 최우제 영입 무산", "rumor"), "")
        self.assertEqual(jump("'제우스' T1 리턴하면 어떨까", "view"), "")                         # 전망·분석 기사
        self.assertEqual(jump("젠지, '쵸비'와 재계약 임박", "rumor"), "")

    def test_hot_badge_only_when_split_and_enough(self):
        from tracker.web.views import _tf_tug
        base = {"kind": "rumor", "a_short": "HLE", "b_short": "T1"}
        self.assertIn("격전지", _tf_tug({**base, "tally": {"o": 5, "x": 5}, "n": 10}, True))
        self.assertNotIn("격전지", _tf_tug({**base, "tally": {"o": 2, "x": 2}, "n": 4}, True))     # 10명 미만
        self.assertNotIn("격전지", _tf_tug({**base, "tally": {"o": 8, "x": 2}, "n": 10}, True))
        self.assertNotIn("격전지", _tf_tug({**base, "tally": {"o": 5, "x": 5}, "n": 10}, False))   # 심기 전엔 비율도 비공개
