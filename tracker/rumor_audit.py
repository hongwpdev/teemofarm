"""못 읽은 기사 모으기: 최근 2주 기사 중 '선수 이름 + 이적·재계약 말'이 있는데 행선지를 못 읽은 제목을 따로 저장.
가끔 이 목록(/api/rumor-audit)을 보고 정답을 매겨 tests/fixtures/real_titles_2026.json 에 더하면
실제 기사 기준 오차율 표본이 늘고, 놓친 말투를 바로 고칠 수 있음(tools/fuzz_data.py 의 'C. 실제 기사 표본').

읽은 것 · 못 읽은 것을 모두 남겨서 '읽음률'도 같이 봄. 화면 계산(state)이 새로 만들어질 때 뒤에서(최대 5분에 한 번) 돌림."""
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from . import rumor
from .classify import article_kind
from .cluster import persons
from .core import db
from .filters import people

KEEP_DAYS = 30
EVERY = 300
_RUN = {"at": 0.0, "busy": False}
_LOCK = threading.Lock()
# 이적·재계약 이야기라는 표시(이 말이 없는 제목은 경기·인터뷰 기사라 행선지가 없는 게 정상)
WORDS = tuple(dict.fromkeys(rumor.JOIN + rumor.RENEW + rumor.RENEW_MORE + rumor.STAY_UP + rumor.MOVE_MARK))
EN_WORDS = rumor.EN_JOIN + rumor.EN_RENEW


def init():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS rumor_audit(
            title TEXT, nick TEXT, team_from TEXT, got TEXT, outlet TEXT, url TEXT, published TEXT, seen TEXT,
            PRIMARY KEY(title, nick))""")


def _pairs(fa, roster, news):
    """(제목, 닉네임, 원소속, 읽은 결과, 기사) — 이적·재계약 말이 있고 아는 사람이 나오는 제목만."""
    team = {r["nick"].lower(): (r["nick"], r["team_from"]) for r in fa if r.get("nick")}
    for r in roster:
        if r.get("nick"):
            team.setdefault(r["nick"].lower(), (r["nick"], r["team"]))
    nick_rx = people()[0]
    for n in news:
        title = n["title"]
        low = title.lower()
        ko = bool(re.search(r"[가-힣]", title))
        if ko and not any(w in title for w in WORDS) or not ko and not any(w in low for w in EN_WORDS):
            continue
        if any(w in title for w in rumor.NEG + rumor.UNSURE):
            continue                                 # 무산·결렬·난항: 행선지가 없는 게 정답
        outlet = (n["outlet"] if "outlet" in n.keys() else "") or ""
        if article_kind(title, "news", outlet) in ("view", "talk"):
            continue
        who = set(persons(title)) if ko else {x.lower() for x in (nick_rx.findall(title) if nick_rx else [])}
        for p in who:
            if p not in team:
                continue
            nick, frm = team[p]
            got = rumor.read_title(title, nick, frm)
            yield title, nick, frm, got, n


def record(fa, roster, force=False):
    """뒤에서 한 번: 최근 기사 판독 결과를 표에 남김(같은 제목·같은 사람은 덮어씀)."""
    with _LOCK:
        if _RUN["busy"] or (not force and time.time() - _RUN["at"] < EVERY):
            return False
        _RUN.update(busy=True, at=time.time())
    try:
        init()
        now = datetime.now(timezone.utc)
        rows = [(t, nick, frm, f"{got[0]}:{'s' if got[1] else 'm'}" if got else "", n["outlet"] or "", n["url"] or "",
                 n["published"] or "", now.isoformat())
                for t, nick, frm, got, n in _pairs(fa, roster, rumor._recent_news())]
        with db() as c:
            c.executemany("INSERT OR REPLACE INTO rumor_audit(title,nick,team_from,got,outlet,url,published,seen) VALUES(?,?,?,?,?,?,?,?)", rows)
            c.execute("DELETE FROM rumor_audit WHERE published < ?", ((now - timedelta(days=KEEP_DAYS)).isoformat(),))
        return True
    finally:
        with _LOCK:
            _RUN["busy"] = False


def record_async(fa, roster):
    if _RUN["busy"] or time.time() - _RUN["at"] < EVERY:
        return
    threading.Thread(target=record, args=(fa, roster), daemon=True).start()


def report(limit: int = 60) -> dict:
    """/api/rumor-audit: 읽음률 + 못 읽은 제목(최근부터). 못 읽은 것 중엔 행선지가 원래 없는 제목도 섞여 있음(사람이 확인할 후보)."""
    init()
    with db() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM rumor_audit ORDER BY published DESC")]
    unread = [r for r in rows if not r["got"]]
    return {"pairs": len(rows), "read": len(rows) - len(unread), "unread": len(unread),
            "read_rate": round((len(rows) - len(unread)) / len(rows), 3) if rows else None,
            "note": "이적·재계약 말이 있는 제목 × 그 제목의 선수. 못 읽은 것은 확인 후보(행선지가 원래 없는 제목도 섞임)",
            "unread_list": [{k: r[k] for k in ("title", "nick", "team_from", "outlet", "url", "published")} for r in unread[:limit]]}
