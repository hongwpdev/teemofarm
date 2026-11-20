"""뉴스 검색어·LoL 기사 거르기(인터넷 없이)."""
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker.config import DEFAULT_TEAMS  # noqa: E402
from tracker.core import init_db  # noqa: E402
from tracker.filters import is_lol_news  # noqa: E402
from tracker.news import NAME_CTX, _clean_title  # noqa: E402


class NewsQueryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_one_query_per_team(self):
        for k, t in DEFAULT_TEAMS.items():
            if k == "lck":
                continue
            self.assertEqual(len(t["news"]), 1, k)
            q = t["news"][0]
            self.assertTrue(q.startswith("(") and q.count("(") == q.count(")"), q)
        self.assertTrue(NAME_CTX.startswith("(") and NAME_CTX.endswith(")"))

    def test_no_fixed_year(self):
        import re
        qs = [q for t in DEFAULT_TEAMS.values() for q in t["news"]]
        self.assertFalse([q for q in qs if re.search(r"20\d\d", q)])            # 해가 바뀌어도 손댈 필요 없게
        self.assertTrue(any("{season}" in q for q in qs))

    def test_tour_queries_follow_schedule(self):
        from datetime import date
        from tracker import schedule
        from tracker.news import tour_queries
        schedule.DATA = {"lck": {"tours": [{"name": "LCK Cup 2027", "start": "2027-01-14", "end": "2027-02-22", "playoff": False},
                                           {"name": "LCK 2027 Playoffs", "start": "2027-09-01", "end": "2027-09-20", "playoff": True}]},
                         "intl": {"tours": [{"name": "MSI 2027", "start": "2027-06-27", "end": "2027-07-12"},
                                            {"name": "Worlds 2027 Main Event", "start": "2027-10-20", "end": "2027-11-10"}]}}
        try:
            self.assertEqual(tour_queries(date(2026, 11, 20)), [])                       # 스토브리그: 없음
            self.assertIn("LCK컵", tour_queries(date(2027, 1, 12))[0][1])                # 개막 이틀 전부터
            self.assertIn("MSI", tour_queries(date(2027, 7, 13))[0][1])                  # 끝난 다음 날까지
            self.assertEqual(tour_queries(date(2027, 7, 20)), [])
            self.assertIn("플레이오프", tour_queries(date(2027, 9, 5))[0][1])
            self.assertIn("롤드컵", tour_queries(date(2027, 10, 30))[0][1])
        finally:
            schedule.DATA = {}

    def test_clean_title(self):
        self.assertEqual(_clean_title("  [오피셜]  농심,  '킹겐' 재계약 - OSEN ", "OSEN"), "[오피셜] 농심, '킹겐' 재계약")
        self.assertEqual(_clean_title("제목 - 인벤", ""), "제목 - 인벤")

    def test_other_sports_stay_out(self):
        for t in ("KT 위즈, 내부 FA 영입 완료", "한진그룹 회장, 신년사 발표", "KT 소닉붐, 연장 접전 끝 승리",
                  "한화생명, 이글스 홈런왕과 광고 계약"):
            self.assertFalse(is_lol_news(t), t)

    def test_lol_even_with_other_sport_word(self):
        for t in ("'페이커' 이상혁, 야구장 시구…T1 LCK 우승 기념", "케스파컵 결승 오늘 개막", "T1, 감코진 개편 발표",
                  "리그 오브 레전드 e스포츠, 축구장 대관 이벤트"):
            self.assertTrue(is_lol_news(t), t)


class LiveTitlesTest(unittest.TestCase):
    """teemofarm.com/lck 에 실제로 올라왔던 제목들 — 같은 이름의 다른 업종 기사는 빼고, 롤 기사는 남긴다."""
    JUNK = (
        '신동원 등 농심 지분 44.24% 유지, 신동익 담보계약 변경',
        '한화생명, 자본건전성 회복 본격화…K-ICS 171%로 상승',
        '[단독]농심 3세 신상열, 문유석 전 판사 딸과 화촉…재계 하객 발길',
        "'홀드왕' KT 스기모토, 일본으로 향한다…소프트뱅크와 계약 추진",
        '[줌인] 한화생명, 분기 투자손실 4620억..."보험으로 번 돈 투자로 날려"',
        '홀드왕 스기모토, kt 떠나 소프트뱅크행 : 스포츠',
        '한예지 가든 플라워 롤 화장지, 3겹, 30m, 30롤, 2팩',
        '[증권言言] 키움증권 "한화생명, 투자손익 부진에 실적 불확실성 확대"',
        'KIC 투자수장에 한화생명 출신 신민식 내정…COO 신용선 유력',
        "농심 후계자 신상열 해외 경영에 '30년 농심맨' 베테랑 투입, 오너3세 체제 더 단단해져",
        '한화생명, 3년 만에 설계사 40% 증가하며 영업 기반 확대',
        '보험사 2분기 실적은…한화생명 날고, 미래에셋 주춤 전망',
        '[단독] 농심캐피탈, 온투업법 상습 위반...과태료 1.4억 제재',
        'KT 구내통신 설치 후폭풍… 삼성물산 임대차계약도 발목',
        '한화생명, 신계약 CSM 40% 성장에 보험 수익성 개선세',
        "[단독] KT, '모두의 AI' 서비스명은 '이음큐브'?…상표 출원 - 머니투데이",
        "'윈나우' KT, 구자욱 원태인 양의지 정수빈 빼고 외부 FA 다 영입 대상...박동원, 박상원, 김호령에 투자 가치 충분",
        '강진원 강진군수, 공공비축미 매입 현장 찾아 농심 살펴 > 뉴스',
        '문 열린 FA시장… kt 6명·SSG 3명 신청',
        "[단독] KT, 새 아시아쿼터 'ML 24G' 호주 국대 좌완 루이스 소프 영입 임박…'日 최초' 韓 홀드왕 공백 메운다",
        "삼성생명 14조 독주 속 ‘반전’…보유 CSM 대비 신계약 유입률 1위는 '한화생명'",
        '농심, 中사업 새 수장에 마케팅통···글로벌 인사 재편 가속',
        'KT, 내부 FA 6명 전원 시장 나간다...최지훈, 1호 계약자로 SSG 잔류할까',
        '한화생명 3분기 ‘어닝쇼크’…대규모 적자에도 실적 정상화 기대 나올 것인가',
        '이스턴웰스, 신동익으로부터 농심 보통주 8만9000주 담보 제공받아',
        '월드비전, 한화생명과 취약 청년 자산 형성 지원',
        "신계약 CSM 40% 늘린 한화생명 … '700종신' 판매 중단에 성장세 시험대",
        "[오피셜] FA 승인 선수 22명 명단 공식발표 '6명 미신청' KT 6명→삼성·두산·SSG 3명→KIA·LG·한화 2명→NC 1명",
        '"너구리도, 꿀꽈배기도 지역과 함께해 더 맛있죠" 농심의 따뜻한 동행 [ESG클린리더스]',
        '월 8만원 넣으면 3년 뒤 1000만원…한화생명, 자립준비·가족돌봄청년 95명 ‘첫 목돈’ 지원',
        '[포토] 한화생명, 자립준비·가족돌봄청년 목돈 마련 지원',
        '‘공든 탑’ 지켜야 하는 KT, 준우승 뒤 더 복잡해진 FA 셈법',
        "미국·중국서 펄펄 난 농심, 3분기 외형 성장...원부재료 가격 부담 '과제'",
        "한화생명, 월드비전 등과 'WE CARE DREAM 저축보험' 협약",
        '“자다가도 이불킥해요” 충격의 ‘피업셋’ 준우승, KT의 2027년 구상은?...힐리어드·대니엘 잡고 내부 FA 집중',
    )

    KEEP = (
        '‘제카’ 김건우 “BLG? 한화생명 훨씬 잘해…도현이형 집으로 보내겠다” [쿠키인터뷰]',
        "[오피셜] 농심, '표식-안딜' 영입 발표...주전 5인 완성",
        "[오피셜] 한화생명 출신 '블러핑', DNS 합류",
        "[오피셜] 돌아온 '데프트', 농심에서 LCK 복귀",
        '데프트, 전역 하루 만에 농심 입단…2022 롤드컵 우승 3인방 4년 만에 한 팀',
        '농심, 표식·안딜 영입…데프트 포함 2027 주전 5인 구성',
        '농심 ‘칼릭스’ 이어 ‘킹겐’도 잡았다…2028년까지 계약, 2027시즌 로스터 재편 시작',
        "[단독] '커리어' 오형석, DK 떠나 한화생명 서포터로",
        "[오피셜] 한화생명, '카나비' 서진혁도 계약 종료",
        "[오피셜] '제우스' 최우제, 한화생명과 계약 종료, T1 리턴하나",
        "한화생명과 결별한 '제우스' 최우제… 옛 동료들 다시 만나나?",
        '[계층] Lck 한화생명, 기인 ,캐니언 영입',
        '한화생명, 카나비 떠난 자리에 젠지 FA 기인·캐니언 영입설…공식 발표는 아직',
        "[오피셜] '킹겐' 황성훈, 농심과 재계약",
        "[오피셜] 농심 '보노' 김기범 코치, 2028년까지 동행",
        '연패 끊고 반등 시동…젠지, 한화생명 꺾고 15승 대열 합류 [쿠키 현장]',
        "[오피셜] '옴므' 떠난 한화생명, '모글리' 이재하 감독 승격",
        '정글러에서 롤드컵 우승 코치로... ‘모글리’, 한화생명 새 사령탑',
        "[오피셜] 한화생명, 새 사령탑에 '모글리' 이재하 감독 선임",
        "[오피셜] '커즈' 문우찬, kt 롤스터 떠났다",
        "[오피셜] KT 떠난 '커즈', 2년 만에 다시 DNS로",
        "LCK 정글러 대이동… '커즈' 문우찬도 KT와 결별",
        'KT 지우 “5세트 제리? 집중력 잃고 실수했다…라인전부터 보완할 것” [쿠키인터뷰]',
        '‘비디디’ 곽보성의 다짐 “KT, 시즌 초 흔들려도 마지막에 웃는다” [쿠키인터뷰]',
        'T1A, KT 3-0 완파…5년 만에 LCK CL 정상',
        'SOOPTV, kt HCN 채널 입점…e스포츠·당구 중계 시청자 확대',
        "DK, '쇼메이커' 허수 재계약…'스매쉬'·김대호 감독도 잔류 [공식]",
        "2027 LCK에도 DK의 심장 '쇼메이커 허수'",
        '‘패패승승승’ 이끈 DK 쇼메이커 “팬들 생각나 짐 쌀 수 없었다…월즈 꼭 가고 싶어” [쿠키인터뷰]',
        'DK 유스, 2026 LCK AS 리그 2연속 우승',
        "[오피셜] KT 떠난 '커즈', 2년 만에 다시 DNS로",
        "DNS 정글러 모두 떠난다… '표식' 홍창현·'샤벨' 김단우와 계약 종료",
        "[오피셜] '두두' 이동주, DNS와 2028년까지 동행",
        '\'롤 3차 방정식\' 완성 양대인의 자신감… "바이퍼 덕에 위기 넘고 결승, 젠지 꺾고 대기록 쓸 것"`',
        '[LCK] ‘바이퍼’ 왔는데… 한화생명, 무기력한 3연패',
        '‘우승 후보’ 한화생명, MSI 첫 경기서 TSW 3-0 완파 [MSI]',
        "[단독] '로치' 김강희, 친정팀 T1 감독으로 복귀 가닥",
        '도란 나가고 제우스 오나...데프트는 농심으로',
        'BNK ‘디아블’ 남대근, 2군 강등…“약속된 팬 미팅 참석 거부”',
        "'창단 첫 프로 진출 쾌거' 진영고, 브리온컴퍼니와 유소년 지원 육성 MOU 체결",
    )

    @classmethod
    def setUpClass(cls):
        init_db()

    def test_other_industries_stay_out(self):
        self.assertEqual([t for t in self.JUNK if is_lol_news(t)], [])

    def test_lol_titles_stay(self):
        self.assertEqual([t for t in self.KEEP if not is_lol_news(t)], [])


if __name__ == "__main__":
    unittest.main()
