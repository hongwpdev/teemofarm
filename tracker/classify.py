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


# 커뮤니티 글(인벤 게시판 등이 구글 뉴스에 섞여 들어옴): 말머리가 게시판 분류인 글.
# 이런 글은 제목에 '오피셜'·'합류'가 있어도 오피셜·단독·유력이 아님(소식에는 '커뮤니티'로만, 이적 '유력·발표' 판단과 독버섯 판에는 안 씀)
COMMUNITY = re.compile(r"^\s*\[(잡담|일반|수다|계층|기타|모집|이벤트|정보|질문|유머|펌|짤|영상|스샷|후기|토론|뻘글|공략|팁|자유|응원|대회|소식|뉴스)\]")


def is_community(title: str) -> bool:
    return bool(COMMUNITY.match(title or ""))


def is_official(title: str) -> bool:
    t = title.lower()
    if "[오피셜]" in t:
        return True
    return any(w in t for w in HOT_WORDS) and not any(w in t for w in NOT_HOT_WORDS)


# 스토브리그(선수·감독 이동) 소식인지: 오피셜·단독·유력 + 이동 사건 말(cluster.EVENTS: 재계약·떠난·복귀·입단·승격…)
# + 아래 말 + 다음 시즌 이야기('2027시즌 감독으로', "'커즈'의 2027 LCK는 DN 수퍼스"). 인터뷰·경기 결과·패치 소식은 빠짐
STOVE_MARK = ("FA", "이적", "스토브리그", "로스터", "행선지", "트레이드", "임대", "감코진", "선수단", "강등", "소속", "재회", "나가고")


def is_stove(title: str, kind: str, season: int) -> bool:
    """kind: article_kind() 결과, season: 지금 시즌(archive.current_season — 11월부터는 다음 해)."""
    if kind in ("official", "rumor"):
        return True
    if kind == "edit":
        return False
    from .cluster import EVENTS                  # (cluster가 이 파일을 불러서 여기서)
    # '마침표'는 '동행 마침표'(동행으로 잡힘) 말고도 '세계 정상 마침표'처럼 쓰여서 뺌
    if any(w in title for ws in EVENTS.values() for w in ws if w != "마침표") or any(w in title for w in STOVE_MARK):
        return True
    return bool(re.search(rf"{season}\s?(?:시즌(?!\s?\d)|LCK)", title))     # '2027 시즌 1 패치'는 아님


def article_kind(title: str, source: str = "news") -> str:
    """기사 성격: official(오피셜) · rumor(단독·유력) · view(전망·분석) · talk(커뮤니티 글) · news(그 밖).
    리그피디아 편집은 로스터 변동이면 official, 아니면 edit."""
    t = title.lower()
    if source == "wiki":
        return "official" if is_official(title) else "edit"
    if is_community(title):
        return "talk"
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
                    r"sort|style|wording|grammar|spelling|^\(편집 요약 없음\)$|^update[sd]?$|"
                    # 되돌리기·거절·관리용 편집(무엇을 바꿨는지 알 수 없음): 'Rejected the last 2 text changes', 'Undo revision', 'Reverted edits by', 'rv'
                    r"^rejected the last|^undo revision|^undid revision|^reverted (edits|\d+ edits)|^rv\b|^revert|"
                    r"^disambiguat|^moved page|^protected|^changed protection", re.I)
_WIKILINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")   # [[문서|보이는 글]] → 보이는 글


_SECTION = re.compile(r"/\*.*?\*/")   # 리그피디아가 문서 한 칸을 고칠 때 자동으로 붙이는 칸 이름('/* Current */')


def strip_section(summary: str) -> str:
    """'/* Current */ added [[Faker]]' → 'added Faker'. 칸 이름만 있으면 ''. 위키 링크 문법도 글자만 남김."""
    return _WIKILINK.sub(r"\1", _SECTION.sub("", summary or "")).strip(" -–:")


def is_minor_wiki(summary: str) -> bool:
    s = strip_section(summary)
    if not s:                        # 칸 이름만 있는 편집(설명 없음): 무엇을 고쳤는지 알 수 없어 숨김
        return True
    return not is_official(s) and bool(_MINOR.search(s))


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
    s = re.sub(r"^roster change:\s*", "", strip_section(summary), flags=re.I)
    for rx, fmt in _WIKI_KO:
        m = rx.search(s)
        if m:
            who = (m.group(1) if m.groups() else "").strip(" .,:;")
            if len(who) > 40:
                continue
            return "로스터 변경: " + fmt.format(who).strip()
    return None
