"""공통: HTTP, DB, 수집 상태, 날짜·제목 도우미."""
import os
import sqlite3
import threading
import urllib.request
from datetime import datetime, timezone

from .config import DB_PATH, KST, UA

STATUS = {}            # (team, source) -> dict(ok, at, msg)
STATUS_LOCK = threading.Lock()
WEEKDAYS = "월화수목금토일"


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db() as c:   # WAL: 수집이 쓰는 중에도 화면 읽기가 기다리지 않게
        c.execute("PRAGMA journal_mode=WAL")
    with db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS items(
                id TEXT, team TEXT, source TEXT, title TEXT, url TEXT,
                outlet TEXT, published TEXT, first_seen TEXT,
                PRIMARY KEY(id, team))"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS ix_pub ON items(published DESC)")
        # FA 현황: 수집할 때마다 통째로 바꿔 씀
        c.execute(
            """CREATE TABLE IF NOT EXISTS fa(
                page TEXT PRIMARY KEY, nick TEXT, real TEXT, team_from TEXT, role TEXT,
                status TEXT, team_to TEXT, team_to_name TEXT, until TEXT, date TEXT, memo TEXT)"""
        )
        c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
        # 선수 프로필(팝업용): FA 수집 때 한꺼번에 받아 둠 → 이름을 눌러도 리그피디아에 요청하지 않음
        c.execute("CREATE TABLE IF NOT EXISTS profile(page TEXT PRIMARY KEY, data TEXT, at TEXT)")
        # 로스터(리그피디아 계약 기준 현재 선수·감독): FA 수집 때 통째로 바꿔 씀
        c.execute(
            """CREATE TABLE IF NOT EXISTS roster(
                league TEXT, team TEXT, role TEXT, page TEXT, nick TEXT, real TEXT, until TEXT, joined INTEGER,
                PRIMARY KEY(league, team, role, page))"""
        )
        # 리그 확장 대비: 예전 DB에는 league 칸이 없어서 추가(기존 행은 LCK)
        for table in ("items", "fa"):
            cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            if "league" not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN league TEXT NOT NULL DEFAULT 'lck'")


def save(rows) -> int:
    now = datetime.now(timezone.utc).isoformat()
    new = 0
    with db() as c:
        for r in rows:
            cur = c.execute(
                "INSERT OR IGNORE INTO items(id,team,source,title,url,outlet,published,first_seen,league) VALUES(?,?,?,?,?,?,?,?,?)",
                (r["id"], r["team"], r["source"], r["title"], r["url"],
                 r["outlet"], r["published"], now, r.get("league", "lck")),
            )
            new += cur.rowcount
    return new


def set_status(team, source, ok, msg):
    with STATUS_LOCK:
        STATUS[(team, source)] = {"ok": ok, "at": datetime.now(timezone.utc), "msg": msg}


def norm_title(t: str) -> str:
    """중복 판단용 제목: 공백·따옴표 차이를 없앰."""
    t = t.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    return " ".join(t.split()).lower()


def to_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def parse_day(v: str):
    """'YYYY-MM-DD' → date, 형식이 틀리면 None."""
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def kst_day_start_utc(d) -> str:
    """KST 기준 그날 0시를 UTC ISO 문자열로."""
    return datetime(d.year, d.month, d.day, tzinfo=KST).astimezone(timezone.utc).isoformat()


def fmt_kst(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(KST).strftime("%m/%d %H:%M")


def rel_time(pub: datetime, now: datetime) -> str:
    m = int((now - pub).total_seconds() // 60)
    if m < 1:
        return "방금"
    if m < 60:
        return f"{m}분 전"
    if m < 1440:
        return f"{m // 60}시간 전"
    return f"{m // 1440}일 전"
