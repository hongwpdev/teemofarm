"""메뉴 순서·HOT 표시: 위 메뉴는 늘 소식 · 이적 · 경기 · 팀(시기마다 순서가 바뀌지 않음). HOT은 스토브리그 기간엔 '이적', 시즌 중엔 '경기'."""
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
        self.assertEqual(labels, ["소식", "이적", "경기", "팀"])          # 늘 같은 순서·같은 이름
        self.assertEqual(hot, ["이적"])

    def test_season(self):
        labels, hot = menu(date(2027, 4, 15))
        self.assertEqual(labels, ["소식", "이적", "경기", "팀"])          # 시즌 중에도 순서는 그대로, HOT만 '경기'로
        self.assertEqual(hot, ["경기"])

    def test_no_same_year_twice(self):
        # 스토브리그 기간(2026년 11월): 지금은 '2026 시즌'(안에 스토브리그 메뉴). 같은 해가 '기록'으로 또 보이면 안 됨
        page = views.shell("lck", "news", "", "", (), date(2026, 11, 20))
        items = re.findall(r'<details class="lgsel ssel">.*?</details>', page, re.S)[0]
        labels = re.findall(r'>(\d{4} [^<]+)<small>', items)
        smalls = re.findall(r'>(\d{4}) 시즌<small>([^<]+)</small>', items)
        self.assertEqual(smalls[:2], [("2027", "예정"), ("2026", "지금")])
        years = [l.split()[0] for l in labels]
        self.assertEqual(len(years), len(set(years)), labels)

    def test_preview_menu(self):
        # '2027 시즌 · 예정': 경기·스토브리그가 아직 없으니 개막 준비 · 시즌 · 팀만, HOT 없음, 시즌 유지
        page = views.shell("lck", "news", "", "", (), date(2026, 11, 20), season=2027)
        labels, hot = menu(date(2026, 11, 20), season=2027)
        self.assertEqual(labels, ["개막 준비", "경기", "팀"])
        self.assertEqual(hot, [])
        self.assertIn('aria-label="시즌 고르기"><b>2027 시즌</b>', page)
        self.assertIn("아직 개막 전", page)

    def test_season_has_no_preview(self):
        # 시즌 중(4월)엔 '예정' 줄이 없음
        page = views.shell("lck", "news", "", "", (), date(2027, 4, 15))
        self.assertNotIn("<small>예정</small>", page)

    def test_archive_has_no_hot(self):
        _, hot = menu(date(2026, 11, 20), season=2026)
        self.assertEqual(hot, [])


if __name__ == "__main__":
    unittest.main()
