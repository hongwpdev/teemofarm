"""이적·FA '유력' 표시: 아직 리그피디아에 확정되지 않은 FA 선수에 대해, 최근 뉴스 제목에서 행선지를 읽어 옴.
예) "[단독] 한화생명, '기인' 김기인·'캐니언' 김건부 영입" → Kiin·Canyon: 한화생명 유력
- 제목에 그 선수 + 영입·계약 합의 같은 말 + 원소속이 아닌 팀이 딱 하나 → 그 팀으로 '유력'
- 제목에 그 선수 + 재계약·잔류 + (원소속 팀만 나오거나 팀이 없음) → '잔류 유력'
- [오피셜]·[공식] 기사면 '발표'(리그피디아 반영 전)
공식 상태(이적 확정·잔류)는 계속 리그피디아 기준이고, 이건 미정인 선수에게만 덧붙이는 참고 표시예요."""
import threading
import time
from datetime import datetime, timedelta, timezone

from .classify import article_kind, title_has_team
from .cluster import EVENTS, persons
from .config import TEAMS
from .core import db

DAYS = 14             # 이 기간 안의 기사만 봄
CACHE_SEC = 60
RENEW = EVENTS["renew"]
LEAVE = EVENTS["leave"]                  # '3년 동행 마침표'처럼 재계약 단어가 있어도 떠나는 기사
JOIN = EVENTS["join"] + ("이적", "합의", "손잡", "유니폼", "입성")
NEG = ("불발", "결렬", "무산", "거절", "실패", "없던 일")   # '재계약 불발' 같은 기사는 행선지로 안 봄
_CACHE = {"at": 0.0, "key": None, "val": {}}
_LOCK = threading.Lock()


def read_title(title: str, nick: str, team_from: str):
    """제목 하나에서 그 선수의 행선지를 읽음 → (팀 키, 잔류 여부) 또는 None."""
    if nick.lower() not in persons(title):
        return None
    if any(w in title for w in NEG):
        return None
    teams = [k for k in TEAMS if k != "lck" and TEAMS[k].get("aliases") and title_has_team(title, k)]
    others = [k for k in teams if k != team_from]
    if any(w in title for w in RENEW) and not any(w in title for w in LEAVE) and not others:
        return (team_from, True) if team_from else None
    if any(w in title for w in JOIN) and len(others) == 1:
        return (others[0], False)
    return None


def _guess(rows, news):
    out = {}
    for r in rows:
        if r["status"] != "fa":
            continue
        best = None
        for n in news:                          # 최신순
            kind = article_kind(n["title"])
            if kind == "view":                  # 전망·분석 기사는 빼고
                continue
            hit = read_title(n["title"], r["nick"], r["team_from"])
            if not hit:
                continue
            cand = {"team": hit[0], "stay": hit[1], "official": kind == "official", "title": n["title"],
                    "url": n["url"], "outlet": n["outlet"] or "", "published": n["published"]}
            if best is None or (cand["official"] and not best["official"]):
                best = cand
            if best["official"]:
                break
        if best:
            out[r["page"]] = best
    return out


def rumors(rows) -> dict:
    """FA 행 목록 → {page: {"team", "stay", "official", "title", "url", "outlet", "published"}}. 1분 캐시."""
    key = tuple((r["page"], r["status"]) for r in rows)
    with _LOCK:
        if _CACHE["key"] == key and time.time() - _CACHE["at"] < CACHE_SEC:
            return _CACHE["val"]
    since = (datetime.now(timezone.utc) - timedelta(days=DAYS)).isoformat()
    try:
        with db() as c:
            news = c.execute("SELECT title, MIN(url) url, MIN(outlet) outlet, MAX(published) published FROM items "
                             "WHERE source='news' AND published >= ? GROUP BY title ORDER BY published DESC", (since,)).fetchall()
    except Exception:  # noqa: BLE001  표시용 참고 정보라 실패해도 화면은 그대로
        news = []
    val = _guess(rows, news)
    with _LOCK:
        _CACHE.update(at=time.time(), key=key, val=val)
    return val
