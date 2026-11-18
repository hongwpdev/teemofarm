"""로스터 짜기 공유용 짧은 주소: /s/<코드> (예: /s/aB3x9K). 같은 로스터·이름이면 같은 코드."""
import hashlib
from datetime import datetime, timezone

from .core import db

ALPHA = "0123456789abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"   # 헷갈리는 l·I·O 뺌


def init():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS shares(code TEXT PRIMARY KEY, r TEXT, n TEXT, at TEXT)")


def _code(seed: str, n: int) -> str:
    v = int(hashlib.sha1(seed.encode()).hexdigest(), 16)
    out = ""
    for _ in range(n):
        v, i = divmod(v, len(ALPHA))
        out += ALPHA[i]
    return out


def make(r: str, name: str) -> str:
    r, name = (r or "")[:3000], " ".join((name or "").split())[:12]
    if not r.strip("|,"):
        raise ValueError("빈 로스터예요")
    seed = r + "\n" + name
    with db() as c:
        for size in (6, 7, 8, 10):
            code = _code(seed, size)
            row = c.execute("SELECT r, n FROM shares WHERE code=?", (code,)).fetchone()
            if row and (row["r"], row["n"]) == (r, name):
                return code
            if not row:
                c.execute("INSERT INTO shares VALUES(?,?,?,?)", (code, r, name, datetime.now(timezone.utc).isoformat()))
                return code
    raise RuntimeError("코드를 만들지 못했어요")


def get(code: str):
    if not code or len(code) > 12:
        return None
    with db() as c:
        row = c.execute("SELECT r, n FROM shares WHERE code=?", (code,)).fetchone()
    return (row["r"], row["n"]) if row else None
