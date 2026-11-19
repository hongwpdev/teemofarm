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

    def test_old_rules_kept(self):
        self.assertTrue(is_minor_wiki("fix typo"))
        self.assertEqual(wiki_ko("Roster change: Chovy re-signed"), "로스터 변경: Chovy 재계약")


if __name__ == "__main__":
    unittest.main()
