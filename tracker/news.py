"""수집: 구글 뉴스 RSS 검색(팀 검색어 + 리그 단독·소식통 검색어 + FA·로스터 선수 본명).
(이 파일은 직접 고쳐 씀 — gen_modules.py로 다시 만들지 않음)

구글이 너무 잦은 요청을 429로 막으므로
- 모든 뉴스 요청은 한 줄로 세워 NEWS_MIN_GAP초 이상 띄우고([조회]도 마찬가지)
- 429를 받으면 그 바퀴의 남은 요청을 멈추고 10분(거듭되면 최대 40분) 쉰 뒤 다시 가져옴."""
import hashlib
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from .classify import _has_aliases, title_has_team
from .config import FA_NAME_BATCH, NEWS_WINDOW, REQUEST_GAP, ROSTER_NAME_BATCH, TEAMS, log
from .core import db, http_get, norm_title, save, set_status, to_utc_iso
from .filters import is_lol_news

NAME_CTX = "(LCK OR 롤 OR LoL OR e스포츠 OR 스토브리그)"   # 선수 본명 검색에 붙이는 말
NEWS_MIN_GAP = 1.2              # 구글 뉴스 요청 사이 최소 간격(초)
BLOCK_BASE = 600                # 429를 받으면 쉬는 시간(초), 거듭되면 두 배씩
BLOCK_MAX = 2400
_LOCK = threading.Lock()
_STATE = {"last": 0.0, "until": 0.0, "strikes": 0, "roster_at": 0.0}
ROSTER_POLL_SEC = 1800          # 계약이 남은 로스터 선수 본명 검색은 30분에 한 번(FA 본명·팀 검색은 매번)


class Blocked(Exception):
    """구글 뉴스가 잠시 막아서 쉬는 중."""


def _is_429(e) -> bool:
    return isinstance(e, urllib.error.HTTPError) and e.code == 429 or "429" in str(e)


def blocked_left() -> int:
    return max(0, int(_STATE["until"] - time.time()))


def _get(url: str, gap) -> bytes:
    with _LOCK:                                       # 뉴스 요청은 한 번에 하나씩, 간격을 두고
        if time.time() < _STATE["until"]:
            raise Blocked()
        wait = max(NEWS_MIN_GAP, REQUEST_GAP if gap is None else gap) - (time.time() - _STATE["last"])
        if wait > 0:
            time.sleep(wait)
        _STATE["last"] = time.time()
        try:
            data = http_get(url)
        except Exception as e:  # noqa: BLE001
            if _is_429(e):
                _STATE["strikes"] += 1
                _STATE["until"] = time.time() + min(BLOCK_MAX, BLOCK_BASE * 2 ** (_STATE["strikes"] - 1))
                log.warning("news: google 429 → %d초 쉼", blocked_left())
                raise Blocked() from e
            raise
        _STATE["strikes"] = 0
        return data


EN_ONLY = "news_en"     # 한글이 없는 제목(영어 기사): 소식 목록엔 안 보이고 '유력' 판단에만 씀


def source_of(title: str) -> str:
    return "news" if re.search(r"[가-힣]", title) else EN_ONLY


def _clean_title(title: str, outlet: str) -> str:
    """' - 매체' 꼬리와 겹친 공백을 뗀 제목."""
    title = re.sub(r"\s+", " ", (title or "").strip())
    if outlet and title.endswith(f" - {outlet}"):
        title = title[: -(len(outlet) + 3)].rstrip()
    return title


def fetch_news(query, key, gap=None, keep=None) -> int:
    """구글 뉴스 검색 한 번 → 저장한 새 항목 수. LoL 기사만 저장하고, keep(title)이 있으면 그 조건도 봄."""
    q = urllib.parse.urlencode({
        "q": f"{query} when:{NEWS_WINDOW}", "hl": "ko", "gl": "KR", "ceid": "KR:ko",
    })
    root = ET.fromstring(_get(f"https://news.google.com/rss/search?{q}", gap))
    rows, seen = [], set()
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        src = it.find("source")
        outlet = (src.text or "").strip() if src is not None else ""
        title = _clean_title(it.findtext("title") or "", outlet)
        # (RSS <description>은 구글 뉴스에선 제목 링크 + 매체 이름뿐이라 보지 않음: '데일리e스포츠'가 붙어 아무 기사나 LoL로 통과됨)
        if not link or not title or not is_lol_news(title) or (keep and not keep(title)):
            continue
        nt = norm_title(title)
        if (outlet, nt) in seen:                # 같은 검색 결과 안에서 같은 매체·같은 제목은 한 번만
            continue
        seen.add((outlet, nt))
        try:
            pub = to_utc_iso(parsedate_to_datetime(it.findtext("pubDate")))
        except Exception:  # noqa: BLE001
            pub = datetime.now(timezone.utc).isoformat()
        rows.append({
            "id": "news:" + hashlib.sha1(f"{outlet}|{nt}".encode()).hexdigest()[:16],
            "team": key, "source": source_of(title), "title": title, "url": link,
            "outlet": outlet, "published": pub,
        })
    return save(rows)


def fa_name_queries():
    """아직 팀이 정해지지 않은 FA 선수의 한국어 본명으로 만든 검색어. 예: '"최우제" OR "김기인" OR …'
    ('제우스' 최우제, T1 리턴 유력)처럼 팀 검색어에는 안 걸리는 선수 기사를 잡으려고.
    이미 행선지가 정해진 선수는 팀 검색어로 충분해서 뺌(요청 수 줄이기)."""
    try:
        with db() as c:
            names = sorted({r["real"] for r in c.execute("SELECT real FROM fa WHERE real != '' AND status='fa'")})
    except sqlite3.Error:
        return []
    return [names[i:i + FA_NAME_BATCH] for i in range(0, len(names), FA_NAME_BATCH)]


def roster_name_queries():
    """계약이 남은 로스터 선수의 본명 묶음. 트레이드·계약 해지 단독 기사는 팀 정식 이름('한화생명e스포츠')이나
    '영입' 같은 말 없이 나올 때가 많아서(예: "[단독] '커리어' 오형석, DK 떠나 한화생명 서포터로") 이름으로도 찾음.
    FA 검색에 이미 있는 이름은 뺌."""
    try:
        with db() as c:
            fa = {r["real"] for r in c.execute("SELECT real FROM fa WHERE real != '' AND status='fa'")}
            names = sorted({r["real"] for r in c.execute("SELECT real FROM roster WHERE league='lck' AND real != ''")} - fa)
    except sqlite3.Error:
        return []
    return [names[i:i + ROSTER_NAME_BATCH] for i in range(0, len(names), ROSTER_NAME_BATCH)]


_MOVE_HINT = re.compile(r"오피셜|\[단독\]|소식통|재계약|스토브리그|FA 시장")   # (여기까지 온 제목은 is_lol_news도 통과한 것)


def lol_title(title: str, names) -> bool:
    """본명 검색 결과 중 LoL 기사만: 제목에 그 이름이 있고, 닉네임 따옴표나 팀·LCK·롤 같은 말이 함께 있어야 함
    (흔한 이름의 다른 분야 기사를 거르려고)."""
    if not any(n in title for n in names):
        return False
    if any(ch in title for ch in "'‘’\"“”"):
        return True
    if re.search(r"LCK|롤|e스포츠|이스포츠|롤드컵|LoL", title, re.I) or _MOVE_HINT.search(title):
        return True
    return any(_has_aliases(k) and title_has_team(title, k) for k in TEAMS)


def poll_news(gap=None):
    jobs = [(key, query, None) for key, t in TEAMS.items() for query in t.get("news", [])]
    # 이름만 찾으면 흔한 이름(김건우·이정현…)의 다른 분야 기사가 100건을 채워 정작 LoL 기사가 밀려남 → LoL 말과 함께
    names = fa_name_queries()
    # 계약이 남은 선수 본명은 30분에 한 번만([조회] 버튼은 매번): 구글 요청 수를 줄여 429를 덜 맞게
    roster_due = gap is not None or time.time() - _STATE["roster_at"] >= ROSTER_POLL_SEC
    if roster_due:
        names += roster_name_queries()
    jobs += [("fa", "(" + " OR ".join(f'"{n}"' for n in ns) + f") {NAME_CTX}", ns) for ns in names]
    if blocked_left():
        set_status("google", "news", False, f"HTTP Error 429 · {blocked_left() // 60 + 1}분 뒤 다시 가져와요")
        return
    if roster_due:
        _STATE["roster_at"] = time.time()
    totals, errors = {}, {}
    for key, query, names in jobs:
        try:
            keep = (lambda title, names=names: lol_title(title, names)) if names else None
            totals[key] = totals.get(key, 0) + fetch_news(query, "lck" if key == "fa" else key, gap, keep)
        except Blocked:
            # 남은 요청은 멈춤(계속 두드리면 더 오래 막힘). 팀별 상태는 지난번 것을 그대로 두고 한 줄로만 알림
            set_status("google", "news", False, f"HTTP Error 429 · {blocked_left() // 60 + 1}분 뒤 다시 가져와요")
            break
        except Exception as e:  # noqa: BLE001
            errors.setdefault(key, []).append(str(e)[:80])
            log.warning("news %s '%s' failed: %s", key, query, e)
    else:
        set_status("google", "news", True, "ok")
    for key in dict.fromkeys(k for k, _, _ in jobs):
        if key in errors:
            set_status(key, "news", False, "; ".join(errors[key]))
        elif key in totals:
            set_status(key, "news", True, f"새 항목 {totals[key]}건")
    log.info("news: %s", ", ".join(f"{k} {n}" for k, n in totals.items()))
