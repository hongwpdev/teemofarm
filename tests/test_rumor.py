"""이적·FA '유력' 표시: 기사 제목에서 행선지를 읽는 규칙 점검."""
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker.core import init_db  # noqa: E402
from tracker.rumor import MOVE_MARK, _guess, read_title  # noqa: E402


class RumorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_join_rumor(self):
        t = "[단독] 한화생명, ‘기인’ 김기인·'캐니언' 김건부 영입"
        self.assertEqual(read_title(t, "Kiin", "geng"), ("hle", False))
        self.assertEqual(read_title(t, "Canyon", "geng"), ("hle", False))

    def test_contract_agreement(self):
        self.assertEqual(read_title("[소식통] '제우스' 최우제, T1과 3년 계약 합의", "Zeus", "hle"), ("t1", False))

    def test_renew(self):
        self.assertEqual(read_title("젠지, '쵸비'와 재계약 임박", "Chovy", "geng"), ("geng", True))

    def test_leave_not_renew(self):
        t = "[오피셜] 젠지, '기인' 김기인·'캐니언' 김건부와 3년 동행 마침표"
        self.assertIsNone(read_title(t, "Kiin", "geng"))
        self.assertIsNone(read_title(t, "Canyon", "geng"))

    def test_negated(self):
        self.assertIsNone(read_title("'롤드컵 패배' T1 탑 도란 재계약 불발 인터뷰 실제 발언 공개", "Doran", "t1"))
        self.assertIsNone(read_title("한화생명 '제우스' 영입 무산", "Zeus", "t1"))

    def test_no_destination(self):
        for t in ("젠지 3년째 '땡큐 캐니언'...올해는 기인도 함께",
                  "LCK 스토브리그 개장 첫날 기인·캐니언 FA…하루 새 주전 10명 시장행",
                  "'기인·제우스·캐니언' FA 시장으로…LCK 스토브리그 개막"):
            for nick, frm in (("Kiin", "geng"), ("Canyon", "geng"), ("Zeus", "hle")):
                self.assertIsNone(read_title(t, nick, frm), (t, nick))

    def test_contracted_player_needs_rumor_or_official(self):
        news = [{"title": "T1 '페이커', 젠지전 승리…합류 후 100승", "url": "u1", "outlet": "a", "published": "2026-11-19T01:00:00+00:00"},
                {"title": "[소식통] '시우' 전시우, 2027 LCK 시즌 젠지 합류 예정", "url": "u2", "outlet": "b", "published": "2026-11-19T02:00:00+00:00"}]
        people = [{"page": "Faker", "nick": "Faker", "team_from": "t1"}, {"page": "Siwoo", "nick": "Siwoo", "team_from": "dk"}]
        got = _guess(people, news, marks=MOVE_MARK, allow_stay=False)
        self.assertNotIn("Faker", got)                 # 평범한 경기 기사는 이적으로 보지 않음
        self.assertEqual(got["Siwoo"]["team"], "geng")

    def test_other_player(self):
        self.assertIsNone(read_title("[단독] 한화생명, '기인' 김기인 영입", "Canyon", "geng"))


if __name__ == "__main__":
    unittest.main()
