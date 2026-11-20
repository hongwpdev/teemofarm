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
