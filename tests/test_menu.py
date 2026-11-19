"""메뉴 순서·HOT 표시: 스토브리그 기간엔 '스토브리그'가, 시즌 중엔 '시즌'이 소식 다음에 오고 HOT이 붙음."""
import os
import re
import tempfile
import unittest
from datetime import date

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker.core import init_db  # noqa: E402
from tracker.web import views  # noqa: E402


def menu(today, season=None):
    page = views.shell("lck", "news", "", "", (), today, season=season)
    nav = re.search(r'<nav class="top_tab".*?</nav>', page, re.S).group(0)
    labels = re.findall(r'data-sec="\w+"[^>]*>([^<]+)', nav)
    hot = re.findall(r'>([^<]+)<span class=season>HOT</span>', nav)
    return labels, hot


class MenuTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_stove_league(self):
        labels, hot = menu(date(2026, 11, 20))
        self.assertEqual(labels[:2], ["소식", "스토브리그"])
        self.assertEqual(hot, ["스토브리그"])

    def test_season(self):
        labels, hot = menu(date(2027, 4, 15))
        self.assertEqual(labels[:2], ["소식", "시즌"])
        self.assertEqual(hot, ["시즌"])

    def test_archive_has_no_hot(self):
        _, hot = menu(date(2026, 11, 20), season=2026)
        self.assertEqual(hot, [])


if __name__ == "__main__":
    unittest.main()
