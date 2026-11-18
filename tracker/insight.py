"""기사 한 줄에 붙이는 덧정보: 신뢰도(버섯 1~3개), 해외 기사 한국어 요약 태그, 스포일러(경기 결과) 여부, 검색어 넓히기."""
import re

from .config import TEAMS
from .core import db
from .filters import ko_nicks

STRONG = ("[단독]", "단독", "유력", "임박", "협상", "가닥", "합류 예정", "[소식통]", "근접", "최종 단계")
SPOILER = re.compile(r"우승|준우승|패배|승리|꺾고|꺾었|역전|결승|올킬|탈락|격파|전멸|연패|연승|\d\s*[:대]\s*\d")
EN_EVENTS = (   # (영문 정규식, 한국어)
    (r"re-?sign|extend|extension|renew|stay", "재계약"),
    (r"part(?:s|ed)? ways|leave|leaves|left|depart|released?|free agen", "결별"),
    (r"join|joins|joined|sign(?:s|ed|ing)?\b|acquire|promot|hire|appoint|return", "영입"),
)
EN_RUMOR = re.compile(r"rumou?r|reportedly|sources?|expected|likely|close to|in talks|set to|nearing|according to", re.I)
_EN_TEAM = {"HLE": "hle", "Hanwha": "hle", "T1": "t1", "Gen.G": "geng", "GEN": "geng", "Dplus": "dk", "DK": "dk",
            "KT": "kt", "Nongshim": "ns", "NS": "ns", "FEARX": "bfx", "BFX": "bfx", "DRX": "drx",
            "DN SOOPers": "dns", "DNS": "dns", "Freecs": "dns", "BRION": "bro", "BRO": "bro"}


def trust(title: str, kind: str) -> int:
    """신뢰도: 3 = 구단 공식(황금 버섯), 2 = 단독·유력 보도, 1 = 루머·썰, 0 = 표시 안 함(일반 기사·전망)."""
    if kind == "official":
        return 3
    if kind == "rumor":
        return 2 if any(w in title for w in STRONG) else 1
    return 0


def is_spoiler(title: str) -> bool:
    return bool(SPOILER.search(title))


def _is_english(title: str) -> bool:
    return len(re.findall(r"[가-힣]", title)) < 3 and len(re.findall(r"[A-Za-z]", title)) >= 10


def overseas_tag(title: str, short) -> str:
    """영문 기사 제목 → '[해외] DNS · Ggoong·Minit 재계약 유력' 같은 한 줄(규칙으로 뽑은 요약, 번역 아님). 못 뽑으면 ''."""
    if not _is_english(title):
        return ""
    teams = []
    for name, k in _EN_TEAM.items():
        if re.search(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", title) and k in TEAMS and k not in teams:
            teams.append(k)
    try:
        with db() as c:
            nicks = {r["nick"] for t in ("roster", "fa") for r in c.execute(f"SELECT nick FROM {t}") if r["nick"]}
    except Exception:  # noqa: BLE001
        nicks = set()
    people = [n for n in sorted(nicks, key=len, reverse=True)
              if len(n) >= 3 and re.search(rf"(?<![A-Za-z0-9]){re.escape(n)}(?![A-Za-z0-9])", title, re.I)]
    ev = next((ko for rx, ko in EN_EVENTS if re.search(rx, title, re.I)), "")
    if not (teams or people) or not ev:
        return ""
    who = "·".join(ko_nicks().get(p, p) for p in people[:3])
    lead = " · ".join(x for x in (" ".join(short(k) for k in teams[:2]), who) if x)
    return f"[해외] {lead} {ev}{' 유력' if EN_RUMOR.search(title) else ''}"


def search_terms(q: str) -> list:
    """검색어 넓히기: '커즈' → ['커즈', 'Cuzz', '문우찬'], '문우찬' → ['문우찬', 'Cuzz', '커즈']."""
    q = " ".join((q or "").split())[:30]
    if not q:
        return []
    terms = {q}
    kmap = ko_nicks()
    ko2en = {v: k for k, v in kmap.items()}
    try:
        with db() as c:
            people = [(r["nick"], r["real"]) for t in ("roster", "fa") for r in c.execute(f"SELECT nick, real FROM {t}")]
    except Exception:  # noqa: BLE001
        people = []
    for nick, real in people:
        ko = kmap.get(nick, "")
        if q.lower() in {(nick or "").lower(), real or "", ko} - {""}:
            terms.update(x for x in (nick, real, ko) if x)
    if q in ko2en:
        terms.add(ko2en[q])
    return sorted(terms, key=len, reverse=True)
