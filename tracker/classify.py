"""제목 판정: 팀 찾기, 기사 성격(오피셜·루머·전망), 리그피디아 편집 요약 정리."""
import re

from .config import HOT_WORDS, NOT_HOT_WORDS, RUMOR_WORDS, TEAMS, VIEW_WORDS

_ALIAS_RE = {}


def title_has_team(title: str, k: str) -> bool:
    """제목에 팀 이름이 있는지. 영문 이름은 앞뒤가 영문·숫자가 아닐 때만 인정(예: 'kt'가 'market'에 걸리지 않게).
    이름 목록이 없는 팀은 거르지 않음."""
    if k not in _ALIAS_RE:
        names = TEAMS.get(k, {}).get("aliases")
        _ALIAS_RE[k] = re.compile("|".join(
            rf"(?<![A-Za-z0-9]){re.escape(n)}(?![A-Za-z0-9])" for n in names), re.I) if names else None
    rx = _ALIAS_RE[k]
    return True if rx is None else bool(rx.search(title))


def _has_aliases(k: str) -> bool:
    return bool(TEAMS.get(k, {}).get("aliases"))


def news_teams(title: str, teams: list) -> list:
    """뉴스 태그로 보일 팀: 제목에 이름이 나오는 팀(어느 검색어로 찾았든). 하나도 없으면 'LCK 공통'.
    이름 목록이 없는 팀(teams.json으로 추가한 팀 등)은 예전처럼 검색어 기준."""
    hit = [k for k in TEAMS if k != "lck" and _has_aliases(k) and title_has_team(title, k)]
    hit += [k for k in teams if k != "lck" and not _has_aliases(k) and k not in hit]
    return hit or ["lck"]


def is_official(title: str) -> bool:
    t = title.lower()
    if "[오피셜]" in t:
        return True
    return any(w in t for w in HOT_WORDS) and not any(w in t for w in NOT_HOT_WORDS)


def article_kind(title: str, source: str = "news") -> str:
    """기사 성격: official(오피셜) · rumor(단독·유력) · view(전망·분석) · news(그 밖).
    리그피디아 편집은 로스터 변동이면 official, 아니면 edit."""
    t = title.lower()
    if source == "wiki":
        return "official" if is_official(title) else "edit"
    if "[오피셜]" in t or "[공식]" in t:
        return "official"
    if any(w in t for w in RUMOR_WORDS):
        return "rumor"
    if "오피셜" in t or "공식" in t:
        return "official"
    if any(w in t for w in VIEW_WORDS):        # 'FA 시장 개막' 같은 전망 기사는 오피셜 단어가 있어도 전망
        return "view"
    if is_official(title):
        return "official"
    return "news"


# 리그피디아에서 숨길 사소한 편집(표 정리·오타 등). 로스터 변동 단어가 있으면 숨기지 않음
_MINOR = re.compile(r"format|typo|fix|cleanup|clean up|layout|template|infobox|image|photo|link|"
                    r"sort|style|wording|grammar|spelling|^\(편집 요약 없음\)$|^update[sd]?$", re.I)


def is_minor_wiki(summary: str) -> bool:
    return not is_official(summary) and bool(_MINOR.search(summary.strip()))


# 리그피디아 편집 요약(영어) → 한국어 한 줄. 모르는 형식이면 None
_WIKI_KO = [
    (re.compile(r"moved (.+?) to former", re.I), "{0} 이탈"),
    (re.compile(r"(?:removed|remove) (.+?)(?: from|$)", re.I), "{0} 이탈"),
    (re.compile(r"(.+?) (?:left|leaves)\b", re.I), "{0} 이탈"),
    (re.compile(r"(?:added|add) (.+?)(?: to| as|$)", re.I), "{0} 합류"),
    (re.compile(r"(.+?) (?:joins|joined)\b", re.I), "{0} 합류"),
    (re.compile(r"(.+?) (?:re-signed|re-signs|resigned)\b", re.I), "{0} 재계약"),
    (re.compile(r"(.+?) (?:signs|signed)\b", re.I), "{0} 영입"),
    (re.compile(r"(.+?) (?:promoted)\b", re.I), "{0} 승격"),
    (re.compile(r"contract|extension", re.I), "계약 정보 갱신"),
]


def wiki_ko(summary: str):
    s = re.sub(r"^roster change:\s*", "", summary.strip(), flags=re.I)
    for rx, fmt in _WIKI_KO:
        m = rx.search(s)
        if m:
            who = (m.group(1) if m.groups() else "").strip(" .,:;")
            if len(who) > 40:
                continue
            return "로스터 변경: " + fmt.format(who).strip()
    return None
