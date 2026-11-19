"""해외 팀 로고: 받은 그림 종류 판별, 저장·주소, 이상한 키 막기, 실패 후 하루 동안 다시 안 받기(인터넷 없이)."""
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

from tracker import teamlogos  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"0" * 40


class TeamLogosTest(unittest.TestCase):
    def setUp(self):
        teamlogos.INDEX = {}
        teamlogos._DIR = tempfile.mkdtemp()
        teamlogos._INDEX = os.path.join(teamlogos._DIR, "index.json")

    def test_sniff(self):
        self.assertEqual(teamlogos._sniff(PNG)[0], "png")
        self.assertEqual(teamlogos._sniff(WEBP)[0], "webp")
        self.assertIsNone(teamlogos._sniff(b"<html>"))

    def test_ensure_saves_and_skips_failed(self):
        api = json.dumps({"query": {"pages": {"1": {"title": "File:G2 logo.png", "imageinfo": [{"thumburl": "https://x/g2"}]},
                                              "2": {"title": "File:Bad.png", "imageinfo": [{"thumburl": "https://x/bad"}]}}}}).encode()
        calls = []

        def fake_get(url):
            calls.append(url)
            return api if "api.php" in url else WEBP if url.endswith("g2") else b"<html>not an image"
        def fake_api(params):
            return json.loads(fake_get("api.php"))
        with mock.patch.object(teamlogos, "http_get", fake_get), mock.patch.object(teamlogos, "api_get", fake_api), \
                mock.patch.object(teamlogos.time, "sleep", lambda s: None):
            self.assertEqual(teamlogos.ensure({"g2-esports": "G2 logo.png", "bad-team": "Bad.png"}), 1)
            self.assertTrue(teamlogos.url("g2-esports").startswith("/tlogo/g2-esports?v="))
            self.assertEqual(teamlogos.read("g2-esports"), (WEBP, "image/webp"))
            self.assertEqual(teamlogos.url("bad-team"), "")
            n = len(calls)
            self.assertEqual(teamlogos.ensure({"g2-esports": "G2 logo.png", "bad-team": "Bad.png"}), 0)   # 둘 다 다시 안 받음
            self.assertEqual(len(calls), n)

    def test_prefers_square(self):
        self.assertEqual(teamlogos._cands("G2 Esportslogo profile.png"), ["G2 Esportslogo square.png", "G2 Esportslogo profile.png"])
        self.assertEqual(teamlogos._cands("1TAP Dinologo square.png"), ["1TAP Dinologo square.png"])

    def test_career_queue(self):
        teamlogos._WANT.clear()
        teamlogos.request(["Griffin (Korean Team)", "Nowhere Team", ""])
        self.assertEqual(teamlogos._WANT, {"Griffin (Korean Team)", "Nowhere Team"})
        got = {}
        with mock.patch.object(teamlogos, "team_rows", lambda names, strict: {"Griffin (Korean Team)": {"Image": "Grifflogo.png"}}), \
                mock.patch.object(teamlogos, "ensure", lambda imgs: got.update(imgs)):
            teamlogos._batch()
        self.assertEqual(got, {"griffin-korean-team": "Grifflogo.png", "nowhere-team": ""})
        self.assertTrue(teamlogos.known("nowhere-team"))                  # 로고 없는 팀은 한동안 다시 안 찾음
        teamlogos.request(["Nowhere Team"])
        self.assertEqual(teamlogos._WANT, set())

    def test_career_queue_retries_on_error(self):
        teamlogos._WANT.clear()
        teamlogos.request(["Some Team"])

        def boom(names, strict):
            raise RuntimeError("You've exceeded your rate limit")
        with mock.patch.object(teamlogos, "team_rows", boom):
            teamlogos._batch()
        self.assertEqual(teamlogos._WANT, {"Some Team"})                  # 한도 오류: 다음 묶음에 다시
        self.assertFalse(teamlogos.known("some-team"))

    def test_download_blocked_falls_back_to_browser(self):
        api = json.dumps({"query": {"pages": {"1": {"title": "File:G2 logo.png",
                                                    "imageinfo": [{"thumburl": "https://static.wikia.nocookie.net/x/g2.png"}]}}}}).encode()

        def blocked(url):
            raise OSError("CERTIFICATE_VERIFY_FAILED")
        with mock.patch.object(teamlogos, "http_get", blocked), mock.patch.object(teamlogos, "api_get", lambda p: json.loads(api)), \
                mock.patch.object(teamlogos.time, "sleep", lambda s: None):
            teamlogos.ensure({"g2-esports": "G2 logo.png"})
        self.assertEqual(teamlogos.url("g2-esports"), "/tlogo/g2-esports?v=r")
        self.assertEqual(teamlogos.remote("g2-esports"), "https://static.wikia.nocookie.net/x/g2.png")
        self.assertIsNone(teamlogos.read("g2-esports"))
        self.assertIn("CERTIFICATE", teamlogos.LAST_ERROR["msg"])
        teamlogos.INDEX["bad"] = {"remote": "https://evil.example/x.png"}      # 리그피디아 이미지 주소가 아니면 안 넘김
        self.assertEqual(teamlogos.remote("bad"), "")

    def test_read_rejects_odd_keys(self):
        teamlogos.INDEX = {"../x": {"file": "../../etc/passwd", "type": "image/png", "v": "1"}}
        self.assertIsNone(teamlogos.read("../x"))
        self.assertIsNone(teamlogos.read("nope"))


if __name__ == "__main__":
    unittest.main()
