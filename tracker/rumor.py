"""이적·FA '유력' 표시: 아직 리그피디아에 확정되지 않은 FA 선수에 대해, 최근 뉴스 제목에서 행선지를 읽어 옴.
예) "[단독] 한화생명, '기인' 김기인·'캐니언' 김건부 영입" → Kiin·Canyon: 한화생명 유력
- 제목에 그 선수 + 영입·계약 합의 같은 말 + 원소속이 아닌 팀이 딱 하나 → 그 팀으로 '유력'
- 제목에 그 선수 + 재계약·잔류 + (원소속 팀만 나오거나 팀이 없음) → '잔류 유력'
- [오피셜]·[공식] 기사면 '발표'(리그피디아 반영 전)
공식 상태(이적 확정·잔류)는 계속 리그피디아 기준이고, 이건 미정인 선수에게만 덧붙이는 참고 표시예요."""
import re
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
JOIN = EVENTS["join"] + ("이적", "합의", "손잡", "유니폼", "입성", "돌아오", "돌아가", "유력")   # '젠지, 탑 시우 유력'
# 영어 기사(Sheep Esports 등): "Sources: Cuzz set to join DN SOOPers", "VicLa extends contract with BNK FEARX"
EN_RENEW = ("re-sign", "resign", "extend", "renew", "stay with", "remain with", "stays with", "remains with")
EN_JOIN = ("join", "sign", "add ", "adds ", "return to", "returns to", "move to", "moves to", "head to", "heads to")
EN_LEAVE = ("leave", "left", "part ways", "parts ways", "depart", "release", "won't continue", "will not continue")
EN_NEG = ("not join", "won't join", "deal off", "rejected", "turned down", "fell through")
EN_GUESS = ("sources", "source:", "set to", "expected", "reportedly", "rumor", "in talks", "likely", "close to", "nearing")
EN_UP = ("promoted",)
# 'Hanwha Life Esports'의 Life를 코치 '라이프'로 읽지 않게: 사람 찾기 전에 팀 이름을 줄여 둠
_EN_TEAM = re.compile(r"Hanwha Life(?: Esports)?", re.I)
# 원소속 팀만 나오는 선임·승격('모글리' 코치 → 감독 승격)과 'OO과 2028년까지'는 잔류
STAY_UP = ("승격", "선임")
UNTIL = re.compile(r"20\d\d년까지|\d\d년까지")
# 한 제목에 여러 소식이 '…'로 이어진 경우(예: "커즈·유칼, DN 수퍼스로 복귀…빈센조도 BNK 피어엑스행") 그 선수가 나온 토막만 봄
_SPLIT = re.compile(r"…|⋯|\.{2,}|\|")
NEG = ("불발", "결렬", "무산", "거절", "실패", "없던 일")   # '재계약 불발' 같은 기사는 행선지로 안 봄
# 계약이 남은 선수는 이적 기사라는 표시가 제목에 있을 때만 봄('합류 후 100승' 같은 경기 기사 제외)
GUESS = ("하나", "할까", "?", "복귀설", "이적설", "합류설", "영입설", "유력", "전망", "가능성", "임박", "근접", "예정")
MOVE_MARK = ("단독", "소식통", "오피셜", "공식", "유력", "임박", "합의", "예정", "근접", "협상", "이적",
             "Sources", "set to", "expected to", "reportedly", "joins", "signs", "join ")
_CACHE = {}          # 이름 -> {"at", "key", "val"}
_LOCK = threading.Lock()


def _read_en(title: str, nick: str, team_from: str):
    """영어 제목 읽기(한글 제목과 같은 규칙: 잔류 → 원소속 / 합류 → 다른 팀 하나 / 떠난 팀은 행선지 아님)."""
    t = _EN_TEAM.sub("Hanwha", title)
    low = t.lower()
    # 닉네임은 표기 그대로(대소문자 포함) 한 단어로 있어야 함('Clear'가 'make it clear'에 걸리지 않게)
    named = re.search(rf"(?<![A-Za-z0-9]){re.escape(nick)}(?![A-Za-z0-9])", t)
    if not named or any(w in low for w in EN_NEG):
        return None
    teams = _teams(t)
    left = None
    for w in EN_LEAVE:                       # 'leaves KT', 'parts ways with T1': 떠나는 말 바로 뒤의 팀
        i = low.find(w)
        if i >= 0:
            hit = _teams(t[i:i + len(w) + 16])
            left = hit[0] if len(hit) == 1 else left
    others = [k for k in teams if k != team_from and k != left]
    stay = any(w in low for w in EN_RENEW) or (team_from in teams and any(w in low for w in EN_UP))
    if stay and not others:
        return (team_from, True) if team_from else None
    if any(w in low for w in EN_JOIN) and len(others) == 1:
        return (others[0], False)
    return None


def _teams(text: str) -> list:
    return [k for k in TEAMS if k != "lck" and TEAMS[k].get("aliases") and title_has_team(text, k)]


def _left_team(title: str):
    """'DK 떠나', '젠지와 결별'처럼 떠나는 말 바로 앞(몇 글자 안)에 나온 팀."""
    for w in LEAVE:
        i = title.find(w)
        if i <= 0:
            continue
        before = title[max(0, i - 12):i]
        hit = _teams(before)
        if len(hit) == 1:
            return hit[0]
    return None


def read_title(title: str, nick: str, team_from: str):
    """제목 하나에서 그 선수의 행선지를 읽음 → (팀 키, 잔류 여부) 또는 None."""
    if not re.search(r"[가-힣]", title):
        return _read_en(title, nick, team_from)
    if nick.lower() not in persons(title):
        return None
    segs = _SPLIT.split(title)
    if len(segs) > 1:
        # 다른 선수 토막은 빼고 봄. 사람이 안 보이는 토막도 다른 팀 얘기면 뺌('…빈센조도 BNK 피어엑스행')
        # '…2028년까지 재계약'처럼 팀·사람이 없는 토막은 그 선수 얘기로 둠
        mine = [p for p in segs if nick.lower() in persons(p)]
        my_teams = set(_teams(" ".join(mine)))
        title = " ".join(p for p in segs if p in mine or (not persons(p) and set(_teams(p)) <= my_teams))
    if any(w in title for w in NEG):
        return None
    teams = _teams(title)
    left = _left_team(title)
    # 원소속이 아닌 '떠난 팀'은 행선지가 아님('한화생명 떠나 DN 수퍼스 합류'는 이미 DNS 로스터인 블러핑에게 HLE행이 아님)
    others = [k for k in teams if k != team_from and k != left]
    renew = any(w in title for w in RENEW) or UNTIL.search(title) or (team_from in teams and any(w in title for w in STAY_UP))
    if renew and not any(w in title for w in LEAVE) and not others:
        return (team_from, True) if team_from else None
    if any(w in title for w in JOIN) and len(others) == 1:
        return (others[0], False)
    # 'DK 떠나 한화생명 서포터로'처럼 '영입' 같은 말 없이 원소속을 떠나 다른 팀 하나로 가는 기사.
    # 떠나는 말 바로 앞의 팀이 원소속일 때만('KT 떠난 커즈, DNS로'는 DNS 선수 기준으로 KT행이 아님)
    if len(others) == 1 and _left_team(title) == team_from:
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
            official = (kind == "official" and not any(w in n["title"] for w in GUESS)
                        and not any(w in n["title"].lower() for w in EN_GUESS))
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
                             "WHERE source IN ('news', 'news_en') AND published >= ? GROUP BY title ORDER BY published DESC",
                             (since,)).fetchall()
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
