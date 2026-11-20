"""LoL 기사만 남기기: 제외 단어(다른 종목·다른 게임)가 있으면 버리고,
LoL·리그·팀·선수 이름 중 하나라도 있어야 남김. 제목만 보고 판단."""
import re
import threading
import time

from .core import db

# 1단계: 하나는 꼭 있어야 하는 말(리그·게임·팀·선수)
DOMAIN_KO = ("리그 오브 레전드", "리그오브레전드", "롤드컵", "월즈", "이스포츠", "e스포츠", "E스포츠", "라이엇", "소환사의 컵",
             "소환사의 협곡", "케스파컵", "감코진",
             "한화생명", "티원", "젠지", "디플러스", "롤스터", "농심", "레드포스", "피어엑스", "수퍼스", "브리온")
DOMAIN_EN = ("LoL", "LCK", "LPL", "LEC", "LCS", "LCP", "CBLOL", "MSI", "Worlds", "Riot", "KeSPA",
             "HLE", "T1", "GEN", "Gen.G", "DK", "KT", "NS", "BFX", "FEARX", "DRX", "DNS", "BRO")
LOL_WORD = re.compile(r"(?<![가-힣])롤(?![러링백업]|모델|케이크|플레잉)")      # '롤'은 따로: 컨트롤·롤러·롤모델 제외
# 한글 닉네임: 기사에선 보통 '커즈'처럼 따옴표 안에 씀. 흔한 낱말과 겹치는 게 많아 따옴표 안일 때만 인정
KO_NICKS = {
    "Aiming": "에이밍", "Andil": "안딜", "Bdd": "비디디", "Calix": "칼릭스", "Canyon": "캐니언", "Career": "커리어",
    "Casting": "캐스팅", "Chovy": "쵸비", "Clear": "클리어", "Clozer": "클로저", "Crazy": "크레이지", "Cuzz": "커즈",
    "Daystar": "데이스타", "Delight": "딜라이트", "Diable": "디아블", "Doran": "도란", "DuDu": "두두", "Duke": "듀크",
    "Duro": "듀로", "Easyhoon": "이지훈", "Edo": "에도", "Effort": "에포트", "Faker": "페이커", "Frog": "프로그",
    "GIDEON": "기드온", "Ggoong": "꿍", "Gumayusi": "구마유시", "Hachani": "하차니", "Homme": "옴므", "Jiwoo": "지우",
    "Joker": "조커", "Kanavi": "카나비", "Kellin": "켈린", "Keria": "케리아", "Kiin": "기인", "Kingen": "킹겐",
    "Lehends": "리헨즈", "Life": "라이프", "Lira": "리라", "Lucid": "루시드", "Lyn": "린", "Mata": "마타",
    "Minit": "미닛", "Mowgli": "모글리", "Namgung": "남궁", "Nova": "노바", "Oner": "오너", "PerfecT": "퍼펙트",
    "Peter": "피터", "Peyz": "페이즈", "PoohManDu": "푸만두", "Pungyeon": "풍연", "Pyosik": "표식", "Raptor": "랩터",
    "Rather": "래더", "Roamer": "로머", "Ruler": "룰러", "Saroo": "사루", "Scout": "스카웃", "SeTab": "세탭",
    "Sharvel": "샤벨", "ShowMaker": "쇼메이커", "Siwoo": "시우", "Smash": "스매시", "Sonstar": "손스타",
    "Sponge": "스펀지", "Taeyoon": "태윤", "Teddy": "테디", "Tom": "톰", "Ucal": "유칼", "VicLa": "빅라",
    "Vincenzo": "빈센조", "Willer": "윌러", "Zeka": "제카", "Zeus": "제우스", "cvMax": "씨맥", "deokdam": "덕담",
    "kkOma": "꼬마", "Viper": "바이퍼", "Bin": "빈", "Knight": "나이트", "Peanut": "피넛", "Deft": "데프트",
    "BeryL": "베릴", "Morgan": "모건", "Kael": "카엘", "Loke": "로케", "Rooster": "루스터",
    "Roach": "로치", "Umti": "엄티", "Nuguri": "너구리", "Gori": "고리", "Lazyfeel": "레이지필", "Dove": "도브", "Bengi": "벵기",
}
_LEARN = {"at": 0.0, "map": {}}


def ko_nicks() -> dict:
    """영문 닉네임 → 한글 닉네임. 손으로 넣은 사전(KO_NICKS) + 기사 제목에서 배운 것(nick_ko 표, maint.py). 10분마다 다시 읽음."""
    if time.time() - _LEARN["at"] > 600:
        learned = {}
        try:
            with db() as c:
                learned = {r["nick"]: r["ko"] for r in c.execute("SELECT nick, ko FROM nick_ko")}
        except Exception:  # noqa: BLE001  (표가 아직 없을 때)
            pass
        _LEARN.update(at=time.time(), map={**learned, **KO_NICKS})      # 손으로 넣은 게 우선
    return _LEARN["map"]


QUOTES = "'\u2018\u2019\"\u201c\u201d"

# 2단계: 하나라도 있으면 버리는 말
BLACK_KO = ("프로야구", "한국시리즈", "야구", "농구", "점프볼", "K리그", "축구", "배구", "V리그", "골프", "호나우지뉴",
            "FC 온라인", "FC온라인", "피파", "발로란트", "배그", "배틀그라운드", "오버워치", "스타크래프트", "철권", "이터널 리턴",
            "투수", "타자", "포수", "내야수", "외야수", "홈런", "이글스", "위즈", "자이언츠", "트윈스", "베어스", "랜더스",
            "라이온즈", "타이거즈", "다이노스", "히어로즈", "소닉붐", "프로미", "점보스")
BLACK_EN = ("KBO", "MLB", "KBL", "WKBL", "NBA", "EPL", "PUBG", "LPGA", "KLPGA", "FIFA", "VCT", "FSL", "APBC", "F1")


def _words(words):
    return re.compile("|".join(rf"(?<![A-Za-z0-9]){re.escape(w)}(?![A-Za-z0-9])" for w in words), re.I)


_DOMAIN_EN = _words(DOMAIN_EN)
_BLACK_EN = _words(BLACK_EN)

# 로스터·FA에 있는 선수·감독 닉네임. 10분마다 다시 읽음
_NAMES = {"at": 0.0, "nick": None, "real": None}
_NAMES_LOCK = threading.Lock()


def people():
    """→ (영문 닉네임 정규식, 따옴표 안 한글 닉네임 정규식). 로스터·FA 표의 닉네임 + 알려진 한글 표기"""
    with _NAMES_LOCK:
        if time.time() - _NAMES["at"] > 600:
            nicks = set()
            try:
                with db() as c:
                    for t in ("roster", "fa"):
                        nicks.update(r["nick"] for r in c.execute(f"SELECT nick FROM {t}") if r["nick"])
            except Exception:  # noqa: BLE001  (표가 아직 없을 때)
                pass
            en = sorted(n for n in nicks if len(n) >= 4)          # 짧은 영문(Sin·Tom 등)은 다른 뜻과 겹쳐서 뺌
            ko = sorted({v.strip() for v in ko_nicks().values() if v.strip()})
            q = re.escape(QUOTES)
            _NAMES.update(at=time.time(), nick=_words(en) if en else None,
                          real=re.compile(rf"[{q}](?:{'|'.join(map(re.escape, ko))})[{q}]"))
        return _NAMES["nick"], _NAMES["real"]


def black_hit(title: str) -> bool:
    return any(w in title for w in BLACK_KO) or bool(_BLACK_EN.search(title))


# 다른 종목 말이 함께 있어도 LoL 기사로 볼 만큼 확실한 말('페이커, 야구장 시구… T1 LCK 우승 기념').
# 팀 이름(KT·한화생명…)은 야구·농구 팀과 겹쳐서 여기엔 안 넣음('KT 위즈 FA 영입'은 계속 버림)
_SURE = _words(("LCK", "LoL", "리그 오브 레전드", "리그오브레전드", "롤드컵"))


def is_lol_news(title: str) -> bool:
    if not title or (black_hit(title) and not _SURE.search(title)):
        return False
    if any(w in title for w in DOMAIN_KO) or _DOMAIN_EN.search(title) or LOL_WORD.search(title):
        return True
    nick, ko = people()
    return bool((nick and nick.search(title)) or (ko and ko.search(title)))
