"""수다방(채팅): 로그인 없이 쓰는 사이트 전체 대화방. 최근 KEEP개만 보관.
브라우저마다 임의 번호(cid)를 만들어 보내고, 서버는 그 번호로 도배만 막음(누구인지는 모름)."""
import re
import threading
import time
from datetime import datetime, timezone

from .core import db

KEEP = 200            # 보관하는 메시지 수
MAX_LEN = 200         # 메시지 글자 수
NAME_MAX = 12         # 닉네임 글자 수
FIRST_LOAD = 80       # 처음 열 때 보여 줄 메시지 수
ONLINE_SEC = 70       # 이 시간 안에 들른 브라우저를 '보는 중'으로 셈
BAD_WORDS = ("씨발", "시발", "씨빨", "씨바", "ㅅㅂ", "ㅆㅂ", "병신", "ㅂㅅ", "개새끼", "새끼", "좆", "지랄",
             "미친놈", "미친년", "닥쳐", "엠창", "느금", "애미", "애비", "꺼져")

_LOCK = threading.Lock()
_ONLINE = {}          # cid -> 마지막으로 들른 시각
_SENT = {}            # cid -> 최근 보낸 시각들
_LAST = {}            # cid -> (마지막 메시지, 시각)
_ALL = []             # 전체 보낸 시각(한꺼번에 몰릴 때 막기)
_CID = re.compile(r"^[A-Za-z0-9_-]{8,40}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]")


def init():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS chat(
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, name TEXT, cid TEXT, text TEXT)""")


def _ok_cid(cid: str) -> bool:
    return bool(cid and _CID.match(cid))


def _online(cid: str) -> int:
    now = time.time()
    with _LOCK:
        if _ok_cid(cid):
            _ONLINE[cid] = now
        for k in [k for k, t in _ONLINE.items() if now - t > ONLINE_SEC]:
            del _ONLINE[k]
        return max(1, len(_ONLINE))


def mask(text: str) -> str:
    for w in BAD_WORDS:
        if w in text:
            text = text.replace(w, "●" * len(w))
    return text


def clean_name(name: str) -> str:
    name = " ".join(_CTRL.sub("", name or "").split())
    return mask(name[:NAME_MAX])


def fetch(after: int, cid: str) -> dict:
    with db() as c:
        if after > 0:
            rows = c.execute("SELECT id, at, name, cid, text FROM chat WHERE id>? ORDER BY id LIMIT ?",
                             (after, KEEP)).fetchall()
        else:
            rows = c.execute("SELECT * FROM (SELECT id, at, name, cid, text FROM chat ORDER BY id DESC LIMIT ?) ORDER BY id",
                             (FIRST_LOAD,)).fetchall()
        last = c.execute("SELECT COALESCE(MAX(id), 0) FROM chat").fetchone()[0]
    msgs = [{"id": r["id"], "at": r["at"], "name": r["name"], "text": r["text"], "mine": bool(cid) and r["cid"] == cid}
            for r in rows]
    return {"msgs": msgs, "last": last, "online": _online(cid)}


def post(cid: str, name: str, text: str) -> tuple:
    """→ (http 코드, 결과). 결과의 msg는 화면에 그대로 보여 줄 안내 문구."""
    if not _ok_cid(cid):
        return 400, {"msg": "새로고침한 뒤 다시 보내 주세요"}
    name = clean_name(name)
    text = " ".join(_CTRL.sub(" ", text or "").split())   # 한 줄 메시지: 줄바꿈·제어문자는 띄어쓰기로
    if not name:
        return 400, {"msg": "닉네임을 정해 주세요"}
    if not text:
        return 400, {"msg": "내용을 입력해 주세요"}
    if len(text) > MAX_LEN:
        return 400, {"msg": f"{MAX_LEN}자까지 보낼 수 있어요"}
    now = time.time()
    with _LOCK:
        sent = [t for t in _SENT.get(cid, []) if now - t < 15]
        _ALL[:] = [t for t in _ALL if now - t < 10]
        if sent and now - sent[-1] < 0.7:
            return 429, {"msg": "조금 천천히 보내 주세요"}
        if len(sent) >= 8:
            return 429, {"msg": "너무 빨리 보내고 있어요. 잠시 뒤 다시 보내 주세요"}
        last = _LAST.get(cid)
        if last and last[0] == text and now - last[1] < 60:
            return 429, {"msg": "같은 내용은 연달아 보낼 수 없어요"}
        if len(_ALL) >= 40:
            return 429, {"msg": "지금 대화가 몰려 있어요. 잠시 뒤 다시 보내 주세요"}
        sent.append(now)
        _SENT[cid] = sent
        _LAST[cid] = (text, now)
        _ALL.append(now)
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as c:
        cur = c.execute("INSERT INTO chat(at, name, cid, text) VALUES(?,?,?,?)", (at, name, cid, mask(text)))
        new_id = cur.lastrowid
        c.execute("DELETE FROM chat WHERE id <= ?", (new_id - KEEP,))
    return 200, {"id": new_id}
