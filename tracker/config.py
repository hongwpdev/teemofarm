"""설정: 환경변수, 리그·팀 목록, 판정 단어. 다른 모듈은 여기서 값을 가져다 씀."""
import json
import logging
import os
from datetime import timedelta, timezone

SITE_NAME = os.getenv("SITE_NAME", "티모의 버섯농장")
SITE_DESC = "LoL 리그별 소식·로스터·이적을 리그피디아와 뉴스에서 모아 한 화면에 보여줘요."

KST = timezone(timedelta(hours=9))
DB_PATH = os.getenv("DB_PATH", "/data/stove.db")
PORT = int(os.getenv("PORT", "8080"))
WIKI_INTERVAL = int(os.getenv("WIKI_INTERVAL_SEC", "300"))   # 5분
NEWS_INTERVAL = int(os.getenv("NEWS_INTERVAL_SEC", "600"))   # 10분
FA_INTERVAL = int(os.getenv("FA_INTERVAL_SEC", "1800"))      # 30분(FA·로스터)
NEWS_WINDOW = os.getenv("NEWS_WINDOW", "7d")                 # 구글 뉴스 검색 기간
NEW_HOURS = int(os.getenv("NEW_HOURS", "3"))                 # 몇 시간 이내면 NEW 표시
UA = os.getenv("USER_AGENT", "lck-stove-tracker/1.0 (personal use)")
TEAMS_FILE = os.getenv("TEAMS_FILE", "")
REQUEST_GAP = float(os.getenv("REQUEST_GAP_SEC", "1.5"))     # 요청 사이 쉬는 시간
MANUAL_GAP = float(os.getenv("MANUAL_GAP_SEC", "0.5"))       # [조회] 때는 빨리
MANUAL_COOLDOWN = int(os.getenv("MANUAL_COOLDOWN_SEC", "120"))  # 소식 [조회] 재실행 최소 간격(전체 사용자 공통)
FA_COOLDOWN = int(os.getenv("FA_COOLDOWN_SEC", "30"))        # FA·로스터 [조회] 재실행 최소 간격
AUTO_MINUTES = int(os.getenv("AUTO_MINUTES", "5"))           # 자동 조회 간격
CARGO_GAP = float(os.getenv("CARGO_GAP_SEC", "2"))           # 리그피디아 Cargo 요청 사이 최소 간격(모든 스레드 공통)
PROFILE_MAX_AGE = int(os.getenv("PROFILE_MAX_AGE_SEC", str(6 * 3600)))   # 프로필(커리어)은 6시간마다만 새로 받음
FA_NAME_BATCH = int(os.getenv("FA_NAME_BATCH", "5"))         # FA 선수 본명 검색: 한 번에 묶는 인원

WIKI_API = "https://lol.fandom.com/api.php"
WIKI_BASE = "https://lol.fandom.com/wiki/"


def _words(name, default):
    return [w.strip().lower() for w in os.getenv(name, default).split(",") if w.strip()]


# 오피셜 판정 단어(제목·편집 요약에 하나라도 있으면). 위키 편집 요약은 영어라 영어 단어도 함께 둠
HOT_WORDS = _words("HOT_WORDS",
                   "오피셜,재계약,영입,계약 종료,결별,합류,연장,FA,선임,"
                   "joins,joined,left,leaves,re-sign,contract,extension,promoted,signs,signed")
# 오피셜에서 뺄 단어(추측·무산·분석). 제목에 '[오피셜]'이 붙은 기사는 예외로 항상 오피셜
NOT_HOT_WORDS = _words("NOT_HOT_WORDS", "유력,전망,루머,불발,무산,가능성,협상,관심,소식통,썰,인터뷰,예상,설(說),?")
# 루머(단독·유력) 판정 단어
RUMOR_WORDS = _words("RUMOR_WORDS", "[단독],단독,유력,루머,관측,임박,협상,가능성,설(說),소식통,썰")
# 전망·분석 판정 단어
VIEW_WORDS = _words("VIEW_WORDS", "전망,분석,관전,유망주,정리,예상,포인트,칼럼,돌아보,결산,기대,행방,개막,시장")

# ── 리그와 팀 ───────────────────────────────────────────────────────────
# (키, 표시 이름, Leaguepedia 페이지 제목, 뉴스 검색용 이름, 짧은 이름, 제목에서 찾을 이름)
_LCK = [
    ("hle",  "한화생명",      "Hanwha Life Esports", "한화생명e스포츠", "HLE", ["한화", "HLE"]),
    ("t1",   "T1",           "T1",                  "T1",            "T1",  ["T1", "티원"]),
    ("geng", "젠지",          "Gen.G",               "젠지",           "GEN", ["젠지", "Gen.G"]),
    ("dk",   "디플러스 기아",  "Dplus KIA",           "디플러스 기아",    "DK",  ["디플러스", "DK"]),
    ("kt",   "kt 롤스터",     "KT Rolster",          "kt 롤스터",       "KT",  ["kt", "KT"]),
    ("ns",   "농심",          "Nongshim RedForce",   "농심 레드포스",    "NS",  ["농심", "NS"]),
    ("bfx",  "BNK 피어엑스",  "BNK FEARX",           "BNK 피어엑스",    "BFX", ["피어엑스", "FEARX", "BNK"]),
    ("drx",  "키움 DRX",      "Kiwoom DRX",          "키움 DRX",       "DRX", ["DRX"]),
    ("dns",  "DN 수퍼스",     "DN SOOPers",          "DN 수퍼스",       "DNS", ["수퍼스", "DN"]),
    ("bro",  "한진 브리온",    "HANJIN BRION",        "한진 브리온",      "BRO", ["브리온", "BRO"]),
]
DEFAULT_TEAMS = {
    k: {"name": name, "wiki": wiki, "short": short, "aliases": aliases,
        "news": [f"{q} 롤 오피셜 OR 재계약 OR 영입 OR 계약", f"{q} 스토브리그"]}
    for k, name, wiki, q, short, aliases in _LCK
}
# 특정 팀에 묶이지 않는 리그 전체 소식(위키 없음)
DEFAULT_TEAMS["lck"] = {"name": "LCK 공통", "wiki": "", "short": "LCK",
                        "news": ["LCK 스토브리그", "LCK FA 오피셜",
                                 "LCK 이적 OR 리턴 OR 유력 OR 결별 OR 합류"]}
TEAMS = DEFAULT_TEAMS
if TEAMS_FILE and os.path.exists(TEAMS_FILE):
    with open(TEAMS_FILE, encoding="utf-8") as f:
        TEAMS = json.load(f)

# 리그 목록. 소식·로스터·이적은 LCK만 켜져 있음(enabled). 나머지 리그는 '일정·결과'만 보이고 다른 메뉴는 '곧 추가'
# wiki: 리그피디아 대회 이름 앞부분("LPL/2026 Season/Split 1"의 "LPL") — 있으면 일정·결과를 받음
# 리그를 켤 때: teams 를 채우고 enabled=True (수집·화면은 리그별로 돌도록 만들어 둠)
LEAGUES = {
    "lck": {"name": "LCK", "sub": "한국", "enabled": True, "teams": TEAMS, "common": "lck", "wiki": "LCK"},
    "lpl": {"name": "LPL", "sub": "중국", "enabled": False, "teams": {}, "wiki": "LPL"},
    "lec": {"name": "LEC", "sub": "유럽", "enabled": False, "teams": {}, "wiki": "LEC"},
    "lcs": {"name": "LCS", "sub": "북미", "enabled": False, "teams": {}, "wiki": "LCS"},
    "lcp": {"name": "LCP", "sub": "아태", "enabled": False, "teams": {}, "wiki": "LCP"},
    "cblol": {"name": "CBLOL", "sub": "브라질", "enabled": False, "teams": {}, "wiki": "CBLOL"},
}
DEFAULT_LEAGUE = "lck"

# 아바타 테두리용 팀 색(각 팀 로고의 대표 색). teams.json에 "color"가 있으면 그것을 씀
TEAM_COLORS = {"bfx": "#e8b818", "bro": "#0c5424", "dk": "#3a3f47", "dns": "#0c54fc", "drx": "#3a3f47",
               "geng": "#ccb484", "hle": "#fc6c24", "kt": "#e42424", "ns": "#e42424", "t1": "#e40c24"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("stove")
