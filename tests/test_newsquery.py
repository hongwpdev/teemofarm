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


if __name__ == "__main__":
    unittest.main()
