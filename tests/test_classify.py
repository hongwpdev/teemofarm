"""리그피디아 편집 요약: 칸 이름만 있는 편집('/* Current */')은 숨기고, 설명이 붙은 건 칸 이름을 떼고 한국어로."""
import unittest

from tracker.classify import is_minor_wiki, wiki_ko


class WikiSummaryTest(unittest.TestCase):
    def test_section_only_is_hidden(self):
        for t in ("/* Current */", "/* Organization */ ", "/* Former */"):
            self.assertTrue(is_minor_wiki(t), t)

    def test_section_with_text(self):
        self.assertFalse(is_minor_wiki("/* Current */ added Faker"))
        self.assertEqual(wiki_ko("/* Current */ added Faker"), "로스터 변경: Faker 합류")
        self.assertEqual(wiki_ko("/* Former */ moved Zeus to former members"), "로스터 변경: Zeus 이탈")

    def test_reverts_and_markup(self):
        for t in ("Rejected the last 2 text changes (by [[Special:Contributions/X|X]]) and restored revision 4353174 by Lynnellet",
                  "Undo revision 123 by Foo", "Reverted edits by Foo (talk) to last revision by Bar", "rv vandalism",
                  "Disambiguating Key to Key (Kim Han-gi)"):
            self.assertTrue(is_minor_wiki(t), t)
        self.assertEqual(wiki_ko("/* Current */ added [[Faker]]"), "로스터 변경: Faker 합류")
        self.assertEqual(wiki_ko("added [[Kim Han-gi|Key]] as support"), "로스터 변경: Key 합류")

    def test_old_rules_kept(self):
        self.assertTrue(is_minor_wiki("fix typo"))
        self.assertEqual(wiki_ko("Roster change: Chovy re-signed"), "로스터 변경: Chovy 재계약")


if __name__ == "__main__":
    unittest.main()


class StoveTest(unittest.TestCase):
    """소식 '스토브리그' 보기: 이동·계약 소식만(실제 기사 제목으로)."""
    def _s(self, t):
        from tracker.classify import article_kind, is_stove
        return is_stove(t, article_kind(t), 2027)

    def test_stove(self):
        for t in ("[오피셜] 전설의 귀환 '데프트' 김혁규, 농심 합류… '표식'-'안딜'과 동행",
                  "'중꺾마' 주인공 '데프트' 김혁규가 돌아왔다… 농심 입단",
                  "한화생명 창단 첫 MSI 우승 감독 '옴므' 윤성영 떠난다",
                  "한화생명e스포츠, '모글리' 이재하를 2027시즌 감독으로",
                  "'커즈' 문우찬의 2027 LCK는 'DN 수퍼스'",
                  "BNK '디아블' 남대근, 2군 강등…약속된 팬 미팅 참석 거부",
                  "'두두' 이동주, DN 수퍼스와 2028년까지 동행 [공식]",
                  "도란 나가고 제우스 오나...데프트는 농심으로"):
            self.assertTrue(self._s(t), t)

    def test_not_stove(self):
        for t in ("‘제우스’ 최우제가 설명한 탑 ‘칼챔’ 메타 [쿠키인터뷰]",
                  "젠지, 롤드컵 결승서 중국 BLG에 역전패…韓 4년 연속 세계 정상 마침표",
                  "도벽 부활, 아이언에서 출발하는 새로운 시범 랭크 등...리그 오브 레전드 2027 시즌 1 개발자 업데이트 공개",
                  "26.23 패치 롤 서버 점검 시간",
                  "디플러스 기아 유스, LCK AS 상·하반기 연속 제패"):
            self.assertFalse(self._s(t), t)


class CommunityTest(unittest.TestCase):
    """인벤 게시판 같은 커뮤니티 글: 제목에 '오피셜'·'합류'가 있어도 오피셜·단독이 아님."""
    def test_kind(self):
        from tracker.classify import article_kind, is_stove
        for t in ("[잡담] 롤) 폭스 탑라이너 타나토스 합류", "[잡담] 쉽피셜)롤 GENG 서폿 클라우드 합류",
                  "[기타] 오피셜 HLE 기인 캐니언 영입", "[수다] 롤) 쇼메 스매쉬 씨맥 재계약했네", "[일반] 그럼 카나비는 젠지 디플 lpl",
                  "[정보] [단독] ‘기인’ ‘캐니언’ 빠진 젠지, 탑 ‘시우’ 유력", "[모집] 롤 할 사람?"):
            self.assertEqual(article_kind(t), "talk", t)
        for t, k in (("[오피셜] kt 롤스터, '랩터' 전어진 영입", "official"), ("[단독] '제우스' 최우제, T1 리턴 유력", "rumor"),
                     ("[롤드컵] BLG, 젠지 3:1로 꺾고 창단 첫 우승", "news")):
            self.assertEqual(article_kind(t), k, t)
        self.assertTrue(is_stove("[잡담] 롤) 폭스 탑라이너 타나토스 합류", "talk", 2027))   # 스토브리그 보기에는 나올 수 있음

    def test_slang_head_and_outlet(self):
        from tracker.classify import article_kind
        # 말머리 없이 '슼피셜)'·'롤)'로 시작하는 글, 매체 이름이 커뮤니티인 글도 커뮤니티
        for t in ("슼피셜)롤 GENG 서폿 클라우드 합류", "뇌피셜) 페이커 내년에도 T1", "롤) 도란 한화 재계약 오피셜 떴네", "[펌] 오피셜) 기인 영입"):
            self.assertEqual(article_kind(t), "talk", t)
        self.assertEqual(article_kind("T1, 오너와 재계약 오피셜", "news", "에펨코리아"), "talk")
        self.assertEqual(article_kind("[오피셜] T1, 오너와 재계약", "news", "인벤"), "official")     # 인벤 기사(웹진)는 그대로
        self.assertEqual(article_kind("[오피셜] T1, 오너와 재계약", "news", "OSEN"), "official")

    def test_lck_topic(self):
        from tracker.filters import lck_topic
        for t in ("[잡담] 롤) 폭스 탑라이너 타나토스 합류", "[일반] 그럼 카나비는 젠지 디플 lpl", "[수다] 페이커 오늘 방송 봄?",
                  "[잡담] 한화 바텀 내년에 어떻게 됨", "슼피셜)롤 GENG 서폿 클라우드 합류"):
            self.assertTrue(lck_topic(t), t)
        for t in ("[잡담] 롤 패치 너무 별로", "[유머] 오늘 랭크 연패함", "[모집] 칼바람 할 사람?", "[질문] 발로란트 요원 추천좀"):
            self.assertFalse(lck_topic(t), t)
