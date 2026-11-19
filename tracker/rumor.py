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
# 계약이 남은 선수는 이적 기사라는 표시가 제목에 있을 때만 봄('합류 후 100승' 같은 경기 기사 제외)
GUESS = ("하나", "할까", "?", "복귀설", "이적설", "합류설", "영입설", "유력", "전망", "가능성", "임박", "근접", "예정")
MOVE_MARK = ("단독", "소식통", "오피셜", "공식", "유력", "임박", "합의", "예정", "근접", "협상", "이적")
_CACHE = {}          # 이름 -> {"at", "key", "val"}
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


def _guess(people, news, marks=None, allow_stay=True):
    """people: [{"page", "nick", "team_from"}] → {page: 유력 정보}. marks를 주면 그 말이 제목에 있는 기사만 봄."""
    out = {}
    for r in people:
        best = None
        for n in news:                          # 최신순
            kind = article_kind(n["title"])
            if kind == "view" or (marks and not any(w in n["title"] for w in marks)):     # 전망·분석 기사는 빼고
                continue
            hit = read_title(n["title"], r["nick"], r["team_from"])
            if not hit or (hit[1] and not allow_stay):
                continue
            # '[오피셜] 제우스 계약 종료, T1 리턴하나'처럼 공식 기사 안의 추측(…하나, 설, 유력)은 '발표'가 아니라 '유력'
            official = kind == "official" and not any(w in n["title"] for w in GUESS)
            cand = {"team": hit[0], "stay": hit[1], "official": official, "title": n["title"],
                    "url": n["url"], "outlet": n["outlet"] or "", "published": n["published"]}
            if best is None or (cand["official"] and not best["official"]):
                best = cand
            if best["official"]:
                break
        if best:
            out[r["page"]] = best
    return out


def _recent_news():
    since = (datetime.now(timezone.utc) - timedelta(days=DAYS)).isoformat()
    try:
        with db() as c:
            return c.execute("SELECT title, MIN(url) url, MIN(outlet) outlet, MAX(published) published FROM items "
                             "WHERE source='news' AND published >= ? GROUP BY title ORDER BY published DESC", (since,)).fetchall()
    except Exception:  # noqa: BLE001  표시용 참고 정보라 실패해도 화면은 그대로
        return []


def _cached(name, key, make):
    with _LOCK:
        c = _CACHE.setdefault(name, {"at": 0.0, "key": None, "val": {}})
        if c["key"] == key and time.time() - c["at"] < CACHE_SEC:
            return c["val"]
    val = make()
    with _LOCK:
        _CACHE[name] = {"at": time.time(), "key": key, "val": val}
    return val


def rumors(rows) -> dict:
    """FA 행 목록(미정인 선수만 봄) → {page: {"team", "stay", "official", "title", "url", "outlet", "published"}}. 1분 캐시."""
    key = tuple((r["page"], r["status"]) for r in rows)
    people = [{"page": r["page"], "nick": r["nick"], "team_from": r["team_from"]} for r in rows if r["status"] == "fa"]
    return _cached("fa", key, lambda: _guess(people, _recent_news()))


def movers(rows) -> dict:
    """계약이 남은 로스터 선수(roster 행)의 이적 유력: 단독·소식통·오피셜·합의·예정 같은 말이 있는 기사에서 다른 팀 합류만 봄(잔류는 뺌).
    예) "[소식통] '시우' 전시우, 2027 LCK 시즌 젠지 합류 예정" → Siwoo: DK → GEN 유력"""
    key = tuple((r["page"], r["team"]) for r in rows)
    people = [{"page": r["page"], "nick": r["nick"], "team_from": r["team"]} for r in rows if r["team"] and r["nick"]]
    return _cached("roster", key, lambda: _guess(people, _recent_news(), marks=MOVE_MARK, allow_stay=False))
