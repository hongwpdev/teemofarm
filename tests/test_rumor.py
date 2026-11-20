"""이적·FA '유력' 표시: 기사 제목에서 행선지를 읽는 규칙 점검."""
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker.core import init_db  # noqa: E402
from tracker.rumor import MOVE_MARK, _guess, read_title  # noqa: E402
from tracker.cluster import persons  # noqa: E402


def _nick(ko):
    """테스트 환경에 따라 '두두'가 'dudu'로 묶이기도 해서, 그 환경에서 쓰는 이름으로."""
    return next(iter(persons(f"'{ko}'")))


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

    def test_leave_to_other_team(self):
        # '영입' 같은 말 없이 '원소속 떠나 다른 팀 ○○로'
        t = "[단독] '커리어' 오형석, DK 떠나 한화생명 서포터로"
        self.assertEqual(read_title(t, "Career", "dk"), ("hle", False))
        g = _guess([{"page": "Career", "nick": "Career", "team_from": "dk"}],
                   [{"title": t, "url": "u", "outlet": "엑스포츠뉴스", "published": "2026-11-19T09:10:00+00:00"}],
                   marks=MOVE_MARK, allow_stay=False)
        self.assertEqual(g["Career"]["team"], "hle")
        # 떠나기만 하고 행선지 팀이 없으면 아님
        self.assertIsNone(read_title("'기인' 김기인, 젠지 떠나 FA 시장으로", "Kiin", "geng"))
        self.assertIsNone(read_title("한화생명과 결별한 '제우스' 최우제… 옛 동료들 다시 만나나?", "Zeus", "hle"))

    def test_left_team_must_be_own_team(self):
        # DNS로 간 커즈(지금 DNS 로스터): 'KT 떠난'은 KT를 떠났다는 말 → KT행으로 읽으면 안 됨
        t = "[오피셜] KT 떠난 '커즈', 2년 만에 다시 DNS로"
        self.assertIsNone(read_title(t, "Cuzz", "dns"))
        self.assertEqual(read_title(t, "Cuzz", "kt"), ("dns", False))

    def test_left_team_is_not_destination(self):
        # 이미 DNS 로스터인 블러핑: '한화생명 떠나 DN 수퍼스 합류'를 HLE행으로 읽으면 안 됨
        t = "[단독] '블러핑' 박규용, 3년간 몸담았던 한화생명 떠나 DN 수퍼스 합류... LCK 정조준"
        self.assertIsNone(read_title(t, _nick("블러핑"), "dns"))
        self.assertEqual(read_title(t, _nick("블러핑"), "hle"), ("dns", False))

    def test_partnership_ended(self):
        # '동행 마무리'는 떠난다는 말(잔류로 읽으면 안 됨)
        self.assertIsNone(read_title("[오피셜] '도란' 최현준, T1과 동행 마무리", "Doran", "t1"))

    def test_former_team(self):
        # '한화생명 출신'은 예전 팀: 이미 DNS 로스터인 블러핑을 한화생명행으로 읽으면 안 됨
        t = "[오피셜] 한화생명 출신 '블러핑', DNS 합류"
        self.assertIsNone(read_title(t, _nick("블러핑"), "dns"))
        self.assertEqual(read_title(t, _nick("블러핑"), "hle"), ("dns", False))

    def test_split_headline(self):
        # '…'로 이어진 다른 선수 소식은 섞지 않음
        t = "'커즈'·'유칼', DN 수퍼스로 복귀…빈센조도 BNK 피어엑스행"
        self.assertIsNone(read_title(t, "Cuzz", "dns"))          # 이미 DNS 선수: BFX행이 아님
        self.assertEqual(read_title(t, "Cuzz", "kt"), ("dns", False))
        self.assertIsNone(read_title("기인 후계자에서 최장수 탑으로... 이동주, DNS와 2년 재계약", "Kiin", "geng"))
        self.assertEqual(read_title("기인 후계자에서 최장수 탑으로... '두두', DNS와 2년 재계약", _nick("두두"), "dns"), ("dns", True))
        # 사람이 없는 토막(…2028년까지 재계약)은 그대로 봄
        self.assertEqual(read_title("[오피셜] ‘8위 추락’ 농심, ‘킹겐·칼릭스’ 중심으로 로스터 재편…2028년까지 재계약", "Kingen", "ns"),
                         ("ns", True))

    def test_more_wordings(self):
        self.assertEqual(read_title("[단독] ‘기인’ ‘캐니언’ 빠진 젠지, 탑 ‘시우’ 유력…정글 ‘샤벨’-‘카나비’ 두고 고심", "Siwoo", "dk"),
                         ("geng", False))
        self.assertIsNone(read_title("[단독] ‘기인’ ‘캐니언’ 빠진 젠지, 탑 ‘시우’ 유력…정글 ‘샤벨’-‘카나비’ 두고 고심", "Kiin", "geng"))
        self.assertEqual(read_title("[오피셜] 농심, '칼릭스' 선현빈과 2028년까지", "Calix", "ns"), ("ns", True))
        self.assertEqual(read_title("[오피셜] 정글러 '빈센조' 하승민, BFX 합류", _nick("빈센조"), "drx"), ("bfx", False))
        self.assertEqual(read_title("'모글리' 이재하, 코치에서 한화생명 감독으로 승격 [공식]", "Mowgli", "hle"), ("hle", True))
        self.assertEqual(read_title("‘제우스’ 최우제, 2년 만에 T1 돌아오나... 친정팀 복귀 유력", "Zeus", "hle"), ("t1", False))

    def test_english_titles(self):
        # 영어 기사(Sheep Esports): 소식 목록엔 안 보이고 유력 판단에만 씀
        self.assertEqual(read_title("Sources: Cuzz set to join DN SOOPers for LCK 2027", "Cuzz", "kt"), ("dns", False))
        self.assertEqual(read_title("Sources: Siwoo set to join Gen.G for LCK 2027 season", "Siwoo", "dk"), ("geng", False))
        self.assertEqual(read_title("VicLa extends contract with BNK FEARX for LCK 2027 season", "VicLa", "bfx"), ("bfx", True))
        self.assertEqual(read_title("DN SOOPers re-sign DuDu for the 2027 LCK season", "DuDu", "dns"), ("dns", True))
        self.assertEqual(read_title("Ucal joins DN SOOPers for the 2027 LCK season", "Ucal", "drx"), ("dns", False))
        self.assertEqual(read_title("Sources: Kiin expected to join Hanwha Life Esports for the 2027 LCK season", "Kiin", "geng"),
                         ("hle", False))
        # 'Hanwha Life'의 Life는 코치 '라이프'가 아님
        self.assertIsNone(read_title("Sources: Kiin expected to join Hanwha Life Esports for the 2027 LCK season", "Life", "dns"))
        # 이미 DNS 선수인 커즈: 'leaves KT'의 KT는 행선지가 아님
        self.assertIsNone(read_title("Cuzz leaves KT Rolster to join DN SOOPers", "Cuzz", "dns"))
        self.assertIsNone(read_title("Sources: Alphari won't continue with Movistar KOI in 2027", "Alphari", "t1"))

    def test_english_rumor_is_not_official(self):
        news = [{"title": "Sources: Cuzz set to join DN SOOPers for LCK 2027", "url": "u", "outlet": "Sheep Esports",
                 "published": "2026-11-17T00:00:00+00:00"}]
        g = _guess([{"page": "Cuzz", "nick": "Cuzz", "team_from": "kt"}], news)
        self.assertEqual(g["Cuzz"]["team"], "dns")
        self.assertFalse(g["Cuzz"]["official"])
        news[0]["title"] = "Ucal joins DN SOOPers for the 2027 LCK season"
        g = _guess([{"page": "Ucal", "nick": "Ucal", "team_from": "drx"}], news)
        self.assertTrue(g["Ucal"]["official"])

    def test_other_player(self):
        self.assertIsNone(read_title("[단독] 한화생명, '기인' 김기인 영입", "Canyon", "geng"))


if __name__ == "__main__":
    unittest.main()
