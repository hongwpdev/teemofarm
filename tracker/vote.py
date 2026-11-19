"""FA 행선지 투표: 아직 행선지가 정해지지 않은(미정) 선수에게 '어디로 갈까' 한 표. 로그인 없이 브라우저 번호(cid)로 한 사람 한 표(바꾸기 가능).
행선지가 정해지면 투표는 닫히고, 맞힌 비율을 보여 줌."""
import re
import threading
import time
from datetime import datetime, timezone

from .core import db

OTHER = "other"                       # LCK 밖(해외·2군·은퇴 등)
_CID = re.compile(r"^[A-Za-z0-9_-]{8,40}$")
_SENT = {}
_LOCK = threading.Lock()


def init():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS votes(page TEXT, cid TEXT, choice TEXT, at TEXT, PRIMARY KEY(page, cid))")


def tally() -> dict:
    """{page: {choice: 표 수}}"""
    out = {}
    with db() as c:
        for r in c.execute("SELECT page, choice, COUNT(*) n FROM votes GROUP BY page, choice"):
            out.setdefault(r["page"], {})[r["choice"]] = r["n"]
    return out


def mine(cid: str) -> dict:
    if not _CID.match(cid or ""):
        return {}
    with db() as c:
        return {r["page"]: r["choice"] for r in c.execute("SELECT page, choice FROM votes WHERE cid=?", (cid,))}


def cast(page: str, choice: str, cid: str, teams) -> str:
    """투표(같은 사람이 다시 누르면 바꿈). 성공하면 '', 아니면 이유."""
    if not _CID.match(cid or ""):
        return "잘못된 요청이에요"
    if choice not in teams and choice != OTHER:
        return "고를 수 없는 팀이에요"
    now = time.time()
    with _LOCK:                                    # 도배 방지: 한 브라우저 1분에 30번까지
        sent = [t for t in _SENT.get(cid, []) if now - t < 60]
        if len(sent) >= 30:
            return "잠시 뒤에 다시 눌러 주세요"
        _SENT[cid] = sent + [now]
    with db() as c:
        row = c.execute("SELECT status FROM fa WHERE page=? AND league='lck'", (page,)).fetchone()
        if not row:
            return "투표할 수 없는 선수예요"
        if row["status"] != "fa":
            return "이미 행선지가 정해졌어요"
        c.execute("INSERT INTO votes(page, cid, choice, at) VALUES(?,?,?,?) "
                  "ON CONFLICT(page, cid) DO UPDATE SET choice=excluded.choice, at=excluded.at",
                  (page, cid, choice, datetime.now(timezone.utc).isoformat()))
    return ""
