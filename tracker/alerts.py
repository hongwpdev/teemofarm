"""운영 알림: 데이터 정합성 점검(integrity.check)에 새 문제가 생기면 디스코드 운영 채널로 한 번 알림.

- 웹훅 주소는 환경 변수 DISCORD_OPS_WEBHOOK에만 둠(코드·설정 파일에 적지 않음). 없으면 로그에만 남김.
  소식 알림 채널(DISCORD_WEBHOOK)과 따로: 독자가 보는 채널에 운영 메시지가 섞이지 않게.
- 같은 문제는 한 번만. 사라졌다가 다시 생기면 다시 알림. 지금 문제 목록은 meta 표에 저장(서버를 다시 켜도 다시 안 보냄)."""
import json
import os
import urllib.request

from .config import SITE_NAME, log
from .core import db

WEBHOOK = os.getenv("DISCORD_OPS_WEBHOOK", "").strip()
KEY = "integrity_seen"
MAX_LINES = 15


def _meta(k, v=None):
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
        if v is None:
            r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
            return r["v"] if r else ""
        c.execute("INSERT OR REPLACE INTO meta(k, v) VALUES(?, ?)", (k, v))


def _post(content: str):
    req = urllib.request.Request(WEBHOOK, data=json.dumps({"content": content[:1900]}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "teemofarm (ops)"})
    urllib.request.urlopen(req, timeout=15).read()


def integrity_alert(problems: list) -> list:
    """새로 생긴 문제만 골라 알림(웹훅이 있으면 디스코드, 없으면 로그). → 새 문제 목록."""
    try:
        seen = set(json.loads(_meta(KEY) or "[]"))
    except ValueError:
        seen = set()
    new = [p for p in problems if p not in seen]
    _meta(KEY, json.dumps(sorted(set(problems)), ensure_ascii=False))     # 지금 목록(해결된 건 빠짐 → 다시 생기면 다시 알림)
    if not new:
        return []
    lines = "\n".join(f"• {p}" for p in new[:MAX_LINES]) + (f"\n… 외 {len(new) - MAX_LINES}건" if len(new) > MAX_LINES else "")
    msg = f"⚠️ {SITE_NAME} 데이터 점검: 새 문제 {len(new)}건\n{lines}\n전체 목록: /api/integrity"
    if WEBHOOK:
        try:
            _post(msg)
        except Exception as e:  # noqa: BLE001  알림 실패해도 수집은 그대로
            log.warning("ops alert failed: %s", e)
    else:
        log.warning("정합성 새 문제 %d건(DISCORD_OPS_WEBHOOK 없음 — 로그에만)", len(new))
    return new
