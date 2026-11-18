"""관리 작업(자동): 사람이 손대지 않아도 되게.
- 30분마다: 기사 제목에서 한글 닉네임 배우기("'세탭' 송경진" → SeTab = 세탭)
- 하루 한 번: 90일 지난 기사 정리, DB 백업(data/backup, 최근 7개만 보관)
- 6시간마다: 리그피디아에서 팀 이름이 바뀌었는지 확인 → 바뀌었으면 화면 아래 안내에 표시"""
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from .cargo import _cq, cargo
from .config import DB_PATH, TEAMS, log
from .core import db, set_status

KEEP_DAYS = 90
BACKUPS = 7
_QUOTED = re.compile(r"['‘’\"“”]([가-힣]{1,8})['‘’\"“”]\s*([가-힣]{2,4})")


def init():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS nick_ko(nick TEXT PRIMARY KEY, ko TEXT, real TEXT, hits INTEGER, at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")


def _meta(c, k, v=None):
    if v is None:
        r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r[0] if r else ""
    c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, v))


# ── 한글 닉네임 배우기 ─────────────────────────────────────────────────
def learn_nicks() -> int:
    """제목에서 '한글닉' 본명 짝을 찾아, 본명이 로스터·FA의 선수와 같으면 그 선수의 한글 닉네임으로 저장.
    여러 기사에서 다르게 쓰였으면 가장 많이 나온 표기를 씀."""
    with db() as c:
        real2nick = {}
        for t in ("roster", "fa"):
            for r in c.execute(f"SELECT nick, real FROM {t}"):
                if r["real"] and r["nick"]:
                    real2nick.setdefault(r["real"], set()).add(r["nick"])
        titles = [r[0] for r in c.execute("SELECT title FROM items WHERE source='news' ORDER BY published DESC LIMIT 5000")]
    counts = {}
    for t in titles:
        for ko, real in _QUOTED.findall(t):
            nicks = real2nick.get(real)
            if not nicks or len(nicks) != 1:          # 동명이인이면 건너뜀
                continue
            nick = next(iter(nicks))
            counts.setdefault(nick, {}).setdefault(ko, [0, real])[0] += 1
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for nick, kos in counts.items():
        ko, (hits, real) = max(kos.items(), key=lambda x: x[1][0])
        rows.append((nick, ko, real, hits, now))
    if rows:
        with db() as c:
            c.executemany("INSERT OR REPLACE INTO nick_ko VALUES(?,?,?,?,?)", rows)
    return len(rows)


# ── 오래된 기사 정리 · 백업 ─────────────────────────────────────────────
def cleanup() -> int:
    cut = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    with db() as c:
        n = c.execute("DELETE FROM items WHERE published < ?", (cut,)).rowcount
    return n


def backup() -> str:
    folder = os.path.join(os.path.dirname(DB_PATH) or ".", "backup")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"stove-{datetime.now():%Y%m%d}.db")
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(path)
    try:
        src.backup(dst)                               # 쓰는 중이어도 안전하게 복사
    finally:
        dst.close()
        src.close()
    olds = sorted(f for f in os.listdir(folder) if f.startswith("stove-") and f.endswith(".db"))
    for f in olds[:-BACKUPS]:
        try:
            os.remove(os.path.join(folder, f))
        except OSError:
            pass
    return path


# ── 팀 이름 바뀜 확인 ───────────────────────────────────────────────────
def check_teams():
    """리그피디아 Teams 표의 RenamedTo가 채워져 있으면(팀 이름이 바뀜) 화면 아래 안내에 띄움."""
    names = {t["wiki"]: k for k, t in TEAMS.items() if t.get("wiki")}
    if not names:
        return
    rows = cargo(None, tables="Teams", fields="Name,RenamedTo,IsDisbanded",
                 where=f"Name IN ({','.join(_cq(n) for n in names)})")
    seen = set()
    for r in rows:
        k = names.get(r.get("Name"))
        if not k:
            continue
        seen.add(k)
        new = (r.get("RenamedTo") or "").strip()
        if new:
            set_status(k, "team", False, f"팀 이름 바뀜: 리그피디아에서 '{r['Name']}' → '{new}' — teams.json·config의 wiki 이름을 바꿔 주세요")
        elif r.get("IsDisbanded") in ("1", "Yes", "yes"):
            set_status(k, "team", False, f"팀 해체 표시: 리그피디아에 '{r['Name']}'가 해체로 나와요")
        else:
            set_status(k, "team", True, "ok")
    for name, k in names.items():
        if k not in seen:
            set_status(k, "team", False, f"팀 이름 확인 필요: 리그피디아에서 '{name}' 팀을 못 찾았어요(이름이 바뀌었을 수 있어요)")


def start():
    def loop():
        time.sleep(300)                                # 켠 직후 몰리는 수집과 겹치지 않게
        while True:
            try:
                n = learn_nicks()
                log.info("maint: learned %d korean nicks", n)
            except Exception as e:  # noqa: BLE001
                log.warning("maint learn failed: %s", e)
            now = time.time()
            try:
                with db() as c:
                    last_day = float(_meta(c, "maint_daily") or 0)
                    last_team = float(_meta(c, "maint_team") or 0)
                if now - last_day > 86400:
                    n = cleanup()
                    p = backup()
                    with db() as c:
                        _meta(c, "maint_daily", str(now))
                    log.info("maint: removed %d old items, backup %s", n, p)
                if now - last_team > 6 * 3600:
                    check_teams()
                    with db() as c:
                        _meta(c, "maint_team", str(now))
            except Exception as e:  # noqa: BLE001
                log.warning("maint failed: %s", e)
            time.sleep(1800)
    threading.Thread(target=loop, daemon=True).start()
