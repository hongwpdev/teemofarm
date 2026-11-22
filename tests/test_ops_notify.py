"""반영 알림(tools/ops_notify.py): .env 읽기, 웹훅 고르기(소식 채널로는 절대 X), 실제 주소 점검·데이터 점검 요약, 알림 글."""
import importlib.util
import json
import os
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location("ops_notify", os.path.join(os.path.dirname(__file__), "..", "tools", "ops_notify.py"))
ops = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ops)

GOOD = {"/healthz": "ok", "/lck": '<nav class="top_tab">', "/lck/fa": '<ul id="falist">', "/lck/summary": '<div class="sgrid">',
        "/lck/roster": '<nav class="top_tab">', "/lck/schedule": '<nav class="top_tab">'}


def fake(pages=None, integrity=(), audit=None, purge_ok=True, webhook_code=204):
    """주소 → (코드, 본문). 부른 주소·보낸 데이터는 calls에 남김."""
    pages = dict(GOOD, **(pages or {}))
    calls = []

    def fetch(url, data=None, headers=None, timeout=20):
        calls.append((url, data, headers or {}))
        if "api.cloudflare.com" in url:
            return (200, json.dumps({"success": True})) if purge_ok else (403, json.dumps({"success": False}))
        if "discord" in url:
            return webhook_code, ""
        if url.endswith("/api/integrity"):
            return 200, json.dumps({"problems": list(integrity)})
        if url.endswith("/api/rumor-audit"):
            return 200, json.dumps(audit or {"read_rate": 0.971, "unread": 2})
        path = "/" + url.split("://", 1)[1].split("/", 1)[1].split("?")[0]
        v = pages.get(path)
        return (v if isinstance(v, tuple) else (200, v)) if v is not None else (404, "")
    return fetch, calls


CFG = {"webhook": "https://discord.com/api/webhooks/x", "cf_zone": "z", "cf_token": "t",
       "site": "https://teemofarm.com", "internal": "http://127.0.0.1:8088"}


class EnvTest(unittest.TestCase):
    def test_parse(self):
        env = ops.parse_env('# 주석\nexport A=1\nB="two words"\nC=\'x=y\'\nD=plain # 끝 주석\n\nbad line\nE=a=b\n')
        self.assertEqual(env, {"A": "1", "B": "two words", "C": "x=y", "D": "plain", "E": "a=b"})

    def test_webhook_never_news_channel(self):
        # 소식 채널(DISCORD_WEBHOOK)은 독자가 보는 곳: 운영 알림이 거기로 가면 안 됨
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, ".env")
            with open(p, "w", encoding="utf-8") as f:
                f.write("DISCORD_WEBHOOK=https://news\n")
            self.assertEqual(ops.settings(p, {})["webhook"], "")
            with open(p, "a", encoding="utf-8") as f:
                f.write("DISCORD_WEBHOOK_URL=https://url\n")
            self.assertEqual(ops.settings(p, {})["webhook"], "https://url")
            with open(p, "a", encoding="utf-8") as f:
                f.write("DISCORD_OPS_WEBHOOK=https://ops\nSITE_BASE_URL=https://example.com/\n")
            cfg = ops.settings(p, {})
            self.assertEqual(cfg["webhook"], "https://ops")
            self.assertEqual(cfg["site"], "https://example.com")
            self.assertEqual(ops.settings(p, {"DISCORD_OPS_WEBHOOK": "https://env"})["webhook"], "https://env")   # 환경 변수 먼저
        self.assertEqual(ops.settings("/없는/.env", {})["site"], "https://teemofarm.com")


class MessageTest(unittest.TestCase):
    def test_ok_all_good(self):
        fetch, calls = fake()
        msg = ops.message("ok", ["abc123 화면 단순화", "def456 이전"], CFG, fetch=fetch)
        self.assertTrue(msg.startswith("✅ 반영 완료: abc123 화면 단순화"))
        for s in ("캐시 비우기: 완료", "실제 주소 점검: 통과", "정합성: 이상 없음", "기사 읽음률: 97.1%"):
            self.assertIn(s, msg)
        cf = [c for c in calls if "cloudflare" in c[0]][0]
        self.assertEqual(json.loads(cf[1]), {"purge_everything": True})
        self.assertEqual(cf[2]["Authorization"], "Bearer t")
        self.assertTrue(any(c[0].startswith("http://127.0.0.1:8088/api/integrity") for c in calls))   # 데이터 점검은 컨테이너 직접
        self.assertTrue(any(c[0].startswith("https://teemofarm.com/lck/fa?") for c in calls))         # 화면 점검은 실제 주소

    def test_ok_but_problems(self):
        fetch, _ = fake(pages={"/lck/fa": "<html>빈 화면</html>", "/lck": (502, "bad gateway")},
                        integrity=["Zeus: 이적 확정인데 로스터엔 hle"], purge_ok=False)
        msg = ops.message("ok", ["abc", ""], CFG, fetch=fetch)
        self.assertTrue(msg.startswith("⚠️ 반영은 됐지만 확인 필요"))
        self.assertIn("/lck HTTP 502", msg)
        self.assertIn('/lck/fa 화면이 비었거나 깨짐', msg)
        self.assertIn("정합성: 문제 1건 — Zeus", msg)
        self.assertIn("캐시 비우기: 실패(HTTP 403)", msg)

    def test_ok_without_cloudflare(self):
        fetch, calls = fake()
        msg = ops.message("ok", ["abc"], dict(CFG, cf_zone="", cf_token=""), fetch=fetch)
        self.assertIn("캐시 비우기: 설정 없음", msg)
        self.assertFalse(any("cloudflare" in c[0] for c in calls))
        self.assertTrue(msg.startswith("✅"))

    def test_error_page_words(self):
        fetch, _ = fake(pages={"/lck/summary": '<div class="sgrid">Traceback (most recent call last)'})
        self.assertIn("/lck/summary 오류 글자가 보임", ops.message("ok", ["abc"], CFG, fetch=fetch))

    def test_fail_and_restart(self):
        msg = ops.message("fail", ["테스트 실패", "abc 새 커밋", "def 이전"], CFG, log_tail="FAIL: test_x\nAssertionError")
        self.assertTrue(msg.startswith("🚨 반영 실패(테스트 실패)"))
        self.assertIn("건너뜀: abc 새 커밋", msg)
        self.assertIn("유지: def 이전", msg)
        self.assertIn("```\nFAIL: test_x", msg)
        self.assertNotIn("```", ops.message("fail", ["빌드 실패", "a", "b"], CFG, log_tail="  \n"))
        self.assertIn("다시 켰어요", ops.message("restart", [], CFG))

    def test_send(self):
        fetch, calls = fake()
        self.assertEqual(ops.send(CFG, "x" * 3000, fetch), "보냄")
        self.assertEqual(len(json.loads(calls[0][1])["content"]), 1900)          # 디스코드 글자 수 한도 안으로
        self.assertEqual(ops.send(dict(CFG, webhook=""), "x", fetch), "웹훅 없음 — 화면에만")
        fetch, _ = fake(webhook_code=404)
        self.assertEqual(ops.send(CFG, "x", fetch), "못 보냄(HTTP 404)")


if __name__ == "__main__":
    unittest.main()
