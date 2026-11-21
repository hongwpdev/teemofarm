"""이적·FA '유력' 표시: 기사 제목에서 행선지를 읽는 규칙 점검."""
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker.core import init_db  # noqa: E402
from tracker.rumor import MOVE_MARK, _guess, called_off_hit, read_title  # noqa: E402
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

    def test_called_off_drops_older_rumor(self):
        def n(t, h):
            return {"title": t, "url": f"u{h}", "outlet": "o", "published": f"2026-11-19T{h:02d}:00:00+00:00"}
        who = [{"page": "Zeus", "nick": "Zeus", "team_from": "hle"}]
        rumor, nix = n("[단독] '제우스' 최우제, T1 복귀 유력", 1), n("T1, '제우스' 최우제 영입 무산", 2)
        off = {}
        self.assertNotIn("Zeus", _guess(who, [nix, rumor], off=off))          # 최신순: 무산 기사가 더 새것
        self.assertEqual(off["Zeus"], {("t1", False)})
        late = n("[단독] '제우스' 최우제, T1 복귀 유력", 3)
        self.assertEqual(_guess(who, [late, nix, rumor])["Zeus"]["team"], "t1")   # 무산 뒤에 다시 유력이 나오면 다시 보임
        # 다른 팀 무산은 상관없음
        self.assertEqual(_guess(who, [n("젠지, '제우스' 영입 무산", 2), rumor])["Zeus"]["team"], "t1")
        # 재계약 불발 → 그전의 잔류 유력도 버림
        stay = n("한화생명, '제우스'와 재계약 임박", 1)
        self.assertNotIn("Zeus", _guess(who, [n("'제우스' 최우제, 한화생명과 재계약 불발", 2), stay]))
        self.assertEqual(called_off_hit("T1과 '제우스' 협상 결렬", "Zeus", "hle"), ("t1", False))

    def test_community_post_is_not_evidence(self):
        # '[기타] 오피셜 HLE 기인 캐니언 영입' 같은 커뮤니티 글은 '발표'·'유력' 근거로 쓰지 않음
        n = {"title": "[기타] 오피셜 HLE 기인 캐니언 영입", "url": "u", "outlet": "인벤", "published": "2026-11-19T09:00:00+00:00"}
        self.assertNotIn("Kiin", _guess([{"page": "Kiin", "nick": "Kiin", "team_from": "geng"}], [n]))
        news = {"title": "[단독] 한화생명, '기인' 김기인 영입", "url": "u2", "outlet": "국민일보", "published": "2026-11-19T08:00:00+00:00"}
        g = _guess([{"page": "Kiin", "nick": "Kiin", "team_from": "geng"}], [n, news])["Kiin"]
        self.assertEqual((g["team"], g["official"], g["outlet"]), ("hle", False, "국민일보"))

    def test_vacancy_is_not_the_player(self):
        # '카나비 떠난 자리에 젠지 FA 기인·캐니언 영입설': 카나비가 젠지로 가는 게 아니라, 그 자리를 기인·캐니언이 채움
        t = "한화생명, 카나비 떠난 자리에 젠지 FA 기인·캐니언 영입설…공식 발표는 아직"
        self.assertIsNone(read_title(t, "Kanavi", "hle"))
        self.assertIsNone(read_title(t, "Kanavi", "dk"))                  # (DK로 간 뒤에도 GEN행으로 읽으면 안 됨)
        self.assertEqual(read_title(t, "Kiin", "geng"), ("hle", False))
        self.assertEqual(read_title(t, "Canyon", "geng"), ("hle", False))
        self.assertIsNone(read_title("'페이커 빈자리' T1, 새 미드 영입 임박", "Faker", "t1"))
        # 쉼표 뒤의 'FA'는 데려오는 팀 쪽('한화생명, FA 기인 영입')
        self.assertEqual(read_title("한화생명, FA 기인 영입", "Kiin", "geng"), ("hle", False))

    def test_rumor_before_settled_move_is_ignored(self):
        # 이적이 확정된 날보다 앞선 기사는 지금 팀 기준 '이적 유력'으로 안 봄
        old = {"title": "[단독] '카나비' 서진혁, 젠지 합류 유력", "url": "u", "outlet": "OSEN", "published": "2026-11-17T09:00:00+00:00"}
        p = [{"page": "Kanavi", "nick": "Kanavi", "team_from": "dk"}]
        self.assertIn("Kanavi", _guess(p, [old], marks=MOVE_MARK, allow_stay=False))
        self.assertNotIn("Kanavi", _guess(p, [old], marks=MOVE_MARK, allow_stay=False, since={"Kanavi": {"date": "2026-11-18"}}))

    def test_no_rumor_back_to_team_just_left(self):
        # T1을 떠나 DK에 입단한 도란: 그 뒤 기사에 T1이 나와도 'T1 이적 유력'은 아님
        n = {"title": "[단독] '도란' 최현준, T1 합류 유력", "url": "u", "outlet": "OSEN", "published": "2026-11-21T09:00:00+00:00"}
        p = [{"page": "Doran", "nick": "Doran", "team_from": "dk"}]
        self.assertIn("Doran", _guess(p, [n], marks=MOVE_MARK, allow_stay=False))
        self.assertNotIn("Doran", _guess(p, [n], marks=MOVE_MARK, allow_stay=False, since={"Doran": {"date": "2026-11-20", "from": "t1"}}))

    def test_settled_uses_roster_when_fa_table_lags(self):
        # FA 표는 아직 '미정'(T1)인데 로스터엔 DK로 올라온 도란: T1이 떠나온 팀
        from tracker.core import db
        from tracker.rumor import _settled
        with db() as c:
            c.execute("INSERT OR REPLACE INTO fa(page,nick,real,team_from,role,status,team_to,team_to_name,until,date,memo) "
                      "VALUES('DoranT','DoranT','','t1','Top','fa','','','','','')")
        try:
            self.assertEqual(_settled({"DoranT": "dk"})["DoranT"]["from"], "t1")
            self.assertNotIn("DoranT", _settled({"DoranT": "t1"}))
        finally:
            with db() as c:
                c.execute("DELETE FROM fa WHERE page='DoranT'")

    def test_title_pattern_matrix(self):
        # 자주 나오는 제목 틀 × 팀 조합 × 선수: 잘못된 행선지(떠나온 팀·다른 선수의 행선지)를 읽지 않는지
        import itertools
        KO = {"hle": "한화생명", "t1": "T1", "geng": "젠지", "dk": "디플러스 기아", "kt": "KT", "ns": "농심",
              "bfx": "BNK 피어엑스", "drx": "DRX", "dns": "DN 수퍼스", "bro": "브리온"}
        EN = {"hle": "Hanwha Life Esports", "t1": "T1", "geng": "Gen.G", "dk": "Dplus KIA", "kt": "KT Rolster",
              "ns": "Nongshim RedForce", "bfx": "BNK FEARX", "drx": "DRX", "dns": "DN SOOPers", "bro": "BRION"}
        P = [("Zeus", "제우스"), ("Doran", "도란"), ("Kanavi", "카나비"), ("Canyon", "캐니언"), ("Kiin", "기인")]
        n = 0
        for i, (a, b, c, d) in enumerate(itertools.islice(itertools.permutations(KO, 4), 0, 5040, 97)):
            p, q = P[i % 5], P[(i + 2) % 5]
            A, B, C = KO[a], KO[b], KO[c]
            cases = [
                (f"{A}, '{p[1]}'와 계약 종료", [(p, a, None), (p, b, None)]),
                (f"{A} 떠난 '{p[1]}', {B} 합류", [(p, a, (b, False)), (p, b, None)]),
                (f"'{p[1]}', {A}와 결별…{B}행 유력", [(p, a, (b, False)), (p, b, None)]),
                (f"'{p[1]}', {A} 잔류 확정", [(p, a, (a, True)), (p, b, None)]),
                (f"[단독] {A}, '{p[1]}' 영입 무산", [(p, b, None)]),
                (f"'{p[1]}' 떠난 자리에 {B} 출신 '{q[1]}' 합류", [(p, a, None), (p, b, None)]),
                (f"{A}·{B} 관심…'{p[1]}' 행선지는?", [(p, c, None)]),
                (f"'{p[1]}'·'{q[1]}', {B} 합류", [(p, a, (b, False)), (q, c, (b, False))]),
                (f"[단독] {B}, '{p[1]}' 영입 임박…'{q[1]}'와 재계약", [(p, a, (b, False)), (q, c, (c, True))]),
                (f"{A}, '{p[1]}' 떠나보내고 '{q[1]}' 영입", [(p, a, None), (p, b, None), (q, c, (a, False))]),
                (f"'{p[1]}' 빈자리 채운다…{A}, '{q[1]}' 영입 임박", [(p, a, None), (q, b, (a, False))]),
                (f"'{p[1]}' 후계자에서 주전으로... 이동주, {A}와 2년 재계약", [(p, a, None)]),
                (f"Sources: {EN[b]} to sign {p[0]}, {q[0]} heads to {EN[c]}", [(p, a, (b, False)), (q, d, (c, False))]),
                (f"{EN[a]} parts ways with {p[0]}", [(p, a, None), (p, b, None)]),
                (f"{p[0]} re-signs with {EN[a]}", [(p, a, (a, True))]),
            ]
            for t, exp in cases:
                for who, tf, want in exp:
                    n += 1
                    self.assertEqual(read_title(t, who[0], tf), want, f"{t} / {who[0]} (원소속 {tf})")
        self.assertGreater(n, 1000)

    def test_english_title_with_two_players(self):
        # 'T1 to sign Zeus, Doran heads to DK': 도란(이미 DK)은 T1행이 아님, 제우스는 T1행
        t = "Sources: T1 to sign Zeus, Doran heads to Dplus KIA"
        self.assertIsNone(read_title(t, "Doran", "dk"))
        self.assertEqual(read_title(t, "Zeus", "hle"), ("t1", False))
        self.assertEqual(read_title("Sources: Cuzz set to join DN SOOPers", "Cuzz", "kt"), ("dns", False))

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


class FuzzFoundTest(unittest.TestCase):
    """무작위 대량 시험(tools/fuzz_data.py)에서 찾은 오류들."""
    @classmethod
    def setUpClass(cls):
        init_db()
        from tracker.core import db
        from tracker.filters import KO_NICKS
        from tracker import cluster, filters
        with db() as c:
            c.executemany("INSERT OR IGNORE INTO fa(page,nick,real,team_from,role,status,team_to,team_to_name,until,date,memo) "
                          "VALUES(?,?,'','hle','Top','fa','','','','','')", [(n, n) for n in KO_NICKS])
        filters._NAMES["at"] = cluster._PEOPLE["at"] = 0.0

    def test_cut_team_name(self):
        # 'DNS'를 잘라 'NS'(농심)로 읽어서 농심 출신 선수의 DNS 영입을 놓치던 문제
        self.assertEqual(read_title("[오피셜] DNS, '스매시' 영입", "Smash", "ns"), ("dns", False))

    def test_denial_is_not_rumor(self):
        self.assertIsNone(read_title("브리온 \"'빈' 영입설 사실무근\"", "Bin", "t1"))
        self.assertIsNone(read_title("T1 '테디' 재계약 협상 난항", "Teddy", "t1"))

    def test_dest_after_name(self):
        t = "[스토브리그 정리] '스펀지' DN 수퍼스행·'클리어' kt 롤스터행"
        self.assertEqual(read_title(t, "Sponge", "ns"), ("dns", False))
        self.assertEqual(read_title(t, "Clear", "ns"), ("kt", False))
        self.assertEqual(read_title("‘구마유시’, 디플러스 기아로 가나", "Gumayusi", "hle"), ("dk", False))
        self.assertIsNone(read_title("'구마유시' T1 행사 참석", "Gumayusi", "hle"))     # '행사'는 행선지가 아님

    def test_origin_team_is_not_destination(self):
        self.assertEqual(read_title("KT, T1 출신 사루 데려온다", "Saroo", "t1"), ("kt", False))
        self.assertEqual(read_title("한화생명e스포츠, DNS 출신 루스터 데려온다", "Rooster", "dns"), ("hle", False))
        self.assertEqual(read_title("DK, 전 DRX 감독 '사루' 선임", "Saroo", "drx"), ("dk", False))

    def test_name_inside_other_name(self):
        # '빈센조' 속 '빈'을 빈으로 보던 문제
        self.assertEqual(read_title("디플러스 기아, ‘빈센조’ 떠나보내고 '빈' 영입", "Bin", "drx"), ("dk", False))

    def test_leave_word_of_other_person(self):
        # '옴므 떠난'은 옴므 얘기, 모글리는 승격(잔류)
        self.assertEqual(read_title("[오피셜] '옴므' 떠난 한화생명, '모글리' 이재하 감독 승격", "Mowgli", "hle"), ("hle", True))
        self.assertIsNone(read_title("[오피셜] 젠지, '기인' 김기인·'캐니언' 김건부와 3년 동행 마침표", "Kiin", "geng"))

    def test_more_words(self):
        self.assertEqual(read_title("디플러스 기아, FA ‘꿍’ 품었다", "Ggoong", "t1"), ("dk", False))
        self.assertEqual(read_title("농심, ‘미닛’ 붙잡았다", "Minit", "ns"), ("ns", True))
        self.assertEqual(read_title("제우스 T1과 3년 계약 소식에 팬들 관심", "Zeus", "hle"), ("t1", False))
        self.assertEqual(read_title("DK, '쇼메이커' 허수 재계약…'스매쉬'·김대호 감독도 잔류 [공식]", "Smash", "dk"), ("dk", True))
        self.assertEqual(read_title("Diable to stay at Nongshim RedForce", "Diable", "ns"), ("ns", True))
        self.assertEqual(read_title("OKSavingsBank BRION announce Daystar as new mid laner", "Daystar", "kt"), ("bro", False))
        # 이름만 늘어놓은 뒤 동사 하나(실제 기사): 모두 같은 소식
        for n in ("ShowMaker", "Smash"):
            self.assertEqual(read_title("ShowMaker, Smash, and cvMax extend with Dplus KIA ahead of 2027", n, "dk"), ("dk", True))

    def test_real_headlines(self):
        # 실제 기사 68건(사람이 정답을 매김): 엉뚱한 팀·헛유력은 0, 놓침은 2건까지(특이한 말투 2개)
        import json
        path = os.path.join(os.path.dirname(__file__), "fixtures", "real_titles_2026.json")
        bad = {"wrong": [], "false+": [], "miss": []}
        for x in json.load(open(path, encoding="utf-8")):
            want = tuple(x["want"]) if x["want"] else None
            got = read_title(x["title"], x["nick"], x["from"])
            if got != want:
                bad["wrong" if got and want else "false+" if got else "miss"].append((x["title"], x["nick"], got))
        self.assertEqual(bad["wrong"], [])
        self.assertEqual(bad["false+"], [])
        self.assertLessEqual(len(bad["miss"]), 2, bad["miss"])


if __name__ == "__main__":
    unittest.main()
