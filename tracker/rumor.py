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

from .classify import _ALIAS_RE, article_kind, title_has_team
from .cluster import EVENTS, persons
from .config import TEAMS
from .core import db
from .filters import KO_ALT, ko_nicks, people

DAYS = 14             # 이 기간 안의 기사만 봄
CACHE_SEC = 60
RENEW = EVENTS["renew"]
LEAVE = EVENTS["leave"] + ("마무리", "작별", "이별", "굿바이")   # '3년 동행 마침표', 'T1과 동행 마무리'처럼 재계약 단어가 있어도 떠나는 기사
JOIN = EVENTS["join"] + ("이적", "합의", "손잡", "유니폼", "입성", "돌아오", "돌아가", "유력", "품었", "품에 안", "데려", "협상",
                         "새 출발", "새 팀", "새 탑", "새 정글", "새 미드", "새 원딜", "새 바텀", "새 서포터", "새 서폿",
                         "새 감독", "새 코치", "새 식구", "새 얼굴", "년 계약")
# 재계약·잔류를 말하는 다른 말('농심, 미닛 붙잡았다')
RENEW_MORE = ("붙잡", "지켰다", "남는다", "남기로")
# 결론이 안 난 기사('재계약 협상 난항'): 잔류로도 이적으로도 안 읽음
UNSURE = ("난항", "이견", "진통", "불투명", "안갯속", "미지수")   # '젠지, 탑 시우 유력'
# 영어 기사(Sheep Esports 등): "Sources: Cuzz set to join DN SOOPers", "VicLa extends contract with BNK FEARX"
EN_RENEW = ("re-sign", "resign", "extend", "renew", "stay with", "remain with", "stays with", "remains with",
            "stay at", "stays at", "remain at", "remains at")
EN_JOIN = ("join", "sign", "add ", "adds ", "return to", "returns to", "move to", "moves to", "head to", "heads to",
           "announce", "unveil", "welcome")
EN_LEAVE = ("leave", "left", "part ways", "parts ways", "depart", "release", "won't continue", "will not continue")
EN_NEG = ("not join", "won't join", "deal off", "rejected", "turned down", "fell through")
EN_GUESS = ("sources", "source:", "set to", "expected", "reportedly", "rumor", "in talks", "likely", "close to", "nearing")
EN_UP = ("promoted",)
# 'Hanwha Life Esports'의 Life를 코치 '라이프'로 읽지 않게: 사람 찾기 전에 팀 이름을 줄여 둠
_EN_TEAM = re.compile(r"Hanwha Life(?: Esports)?", re.I)
# 원소속 팀만 나오는 선임·승격('모글리' 코치 → 감독 승격)과 'OO과 2028년까지'는 잔류
STAY_UP = ("승격", "선임", "감독으로", "사령탑으로")
UNTIL = re.compile(r"20\d\d년까지|\d\d년까지")
# 한 제목에 여러 소식이 '…'로 이어진 경우(예: "커즈·유칼, DN 수퍼스로 복귀…빈센조도 BNK 피어엑스행") 그 선수가 나온 토막만 봄
_SPLIT = re.compile(r"…|⋯|\.{2,}|\|")
NEG = ("불발", "결렬", "무산", "거절", "실패", "없던 일", "사실무근", "사실 무근", "오보", "사실이 아니", "부인")   # '재계약 불발' 같은 기사는 행선지로 안 봄
# 계약이 남은 선수는 이적 기사라는 표시가 제목에 있을 때만 봄('합류 후 100승' 같은 경기 기사 제외)
GUESS = ("하나", "할까", "?", "복귀설", "이적설", "합류설", "영입설", "유력", "전망", "가능성", "임박", "근접", "예정")
MOVE_MARK = ("단독", "소식통", "오피셜", "공식", "유력", "임박", "합의", "예정", "근접", "협상", "이적",
             "Sources", "set to", "expected to", "reportedly", "joins", "signs", "join ")
# '카나비 떠난 자리에 …'·'○○ 빈자리'·'○○ 후임': 그 선수가 아니라 그 자리를 채울 다른 선수 얘기
VACANCY = re.compile(r"(?:떠난|빠진|나간|비운)\s*(?:빈\s?)?자리|빈\s?자리|공백|후임|대체자")
_FA_FROM = re.compile(r"\s?(?:FA|출신)")     # '젠지 FA 기인·캐니언': 그 팀은 그 사람들이 떠나온 팀
_CACHE = {}          # 이름 -> {"at", "key", "val"}
_LOCK = threading.Lock()


def _read_en(title: str, nick: str, team_from: str):
    """영어 제목 읽기(한글 제목과 같은 규칙: 잔류 → 원소속 / 합류 → 다른 팀 하나 / 떠난 팀은 행선지 아님)."""
    t = _EN_TEAM.sub("Hanwha", title)
    low = t.lower()
    # 닉네임은 표기 그대로(대소문자 포함) 한 단어로 있어야 함('Clear'가 'make it clear'에 걸리지 않게)
    nrx = re.compile(rf"(?<![A-Za-z0-9]){re.escape(nick)}(?![A-Za-z0-9])")
    if not nrx.search(t) or any(w in low for w in EN_NEG):
        return None
    # 여러 선수 소식이 한 제목에 있으면('T1 to sign Zeus, Doran heads to DK') 그 선수가 나온 토막만 봄.
    # 토막에 팀이 없는데 다른 선수도 나오면 누구 얘기인지 몰라서 안 읽음
    parts = [p for p in re.split(r",|;|\||—|–|\s-\s|\band\b|\bwhile\b", t) if p.strip()]
    # 'ShowMaker, Smash, and cvMax extend with Dplus KIA'처럼 이름만 늘어놓은 뒤 동사 하나면 모두 같은 소식(나누지 않음)
    verbs = [low.find(w) for w in EN_JOIN + EN_RENEW + EN_LEAVE if low.find(w) > 0]
    head = t[:min(verbs)] if verbs else ""
    if head and nrx.search(head) and not _teams(head) and re.fullmatch(r"\s*[\w.'\-]+(?:\s*,\s*[\w.'\-]+)*(?:\s*,?\s*and\s+[\w.'\-]+)?\s*", head):
        parts = [t]
    if len(parts) > 1:
        mine = " ".join(p for p in parts if nrx.search(p))
        nick_rx = people()[0]
        others_named = {x.lower() for x in (nick_rx.findall(t) if nick_rx else [])} - {nick.lower()}
        if _teams(mine):
            t, low = mine, mine.lower()
        elif others_named:
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


def _win(title: str, start: int, end: int) -> str:
    """제목의 [start:end] 토막. 영문 단어 한가운데서 자르지 않음('DNS'를 잘라 'NS'(농심)로 읽던 문제)."""
    start = max(0, start)
    while 0 < start < len(title) and title[start - 1].isascii() and title[start - 1].isalnum() and title[start].isalnum():
        start -= 1
    return title[start:end]


def _last_team(text: str):
    """토막 안에서 가장 뒤(말에 가장 가까이)에 나온 팀. 'KT, T1 출신'의 출신 팀은 T1."""
    best, pos = None, -1
    for k in _teams(text):
        rx = _ALIAS_RE.get(k)
        for m in (rx.finditer(text) if rx else ()):
            if m.end() > pos:
                best, pos = k, m.end()
    return best


def _joined_team(title: str):
    """'DNS 합류', 'DN 수퍼스로 복귀'처럼 합류하는 말 바로 앞(몇 글자 안)에 나온 팀.
    떠나온 팀('DNS 출신 루스터 데려온다'의 DNS)은 빼고, 둘 이상이면 말에 가장 가까운 팀."""
    left = _left_teams(title)
    for w in JOIN:
        i = title.find(w)
        if i <= 0:
            continue
        win = _win(title, i - 10, i)
        hit = [k for k in _teams(win) if k not in left]
        if len(hit) == 1:
            return hit[0]
        if hit:
            k = _last_team(win)
            if k in hit:
                return k
    return None


def _name_at(title: str, name: str) -> int:
    """제목에서 그 이름(닉네임)이 처음 나오는 자리, 없으면 -1. 다른 이름 속 글자는 안 셈('빈센조' 속 '빈')."""
    low = title.lower()
    for m in re.finditer(re.escape(name.lower()), low):
        before = low[m.start() - 1] if m.start() else " "
        after = low[m.end()] if m.end() < len(low) else " "
        if re.match(r"[a-z0-9가-힣]", before):
            continue
        if re.match(r"[a-z0-9]", after) or (len(name) == 1 and re.match(r"[가-힣]", after)):
            continue
        return m.start()
    return -1


def _vacancy_of(title: str, nick: str) -> bool:
    """제목이 이 선수가 '떠난 자리·빈자리·후임' 얘기인지(바로 앞 몇 글자 안에 이 선수 이름)."""
    names = _names(nick)
    for m in VACANCY.finditer(title):
        before = _win(title, m.start() - 14, m.start()).lower()
        if any(n in before for n in names):
            return True
    return False


def _left_teams(title: str) -> set:
    """떠나온 팀 모두: '한화생명 떠나'(떠나는 말 앞) + '젠지 FA 기인'·'T1 출신'(FA·출신 앞) + '전 DRX 감독'(전·前 뒤)."""
    out = set()
    for k in _teams(title):
        rx = _ALIAS_RE.get(k)
        for m in (rx.finditer(title) if rx else ()):
            if re.search(r"(?:^|[\s,'‘\"(])(?:전|前)\s*(?:[^\s,]+\s+)?$", title[:m.start()]):
                out.add(k)
    for w in LEAVE + ("출신",):
        for m in re.finditer(re.escape(w), title):
            if re.match(r"\s*(?:빈\s?)?자리", title[m.end():]) or title[m.start():].startswith("떠나보내"):
                continue                       # '카나비 떠난 자리에'·'도란 떠나보내고'의 팀은 그 자리를 채우는(데려오는) 팀
            win = _win(title, m.start() - 12, m.start())
            hit = _teams(win)
            if len(hit) == 1:
                out.add(hit[0])
            elif hit and w == "출신":          # 'KT, T1 출신 사루': 출신 바로 앞 팀
                out.add(_last_team(win))
    for m in _FA_FROM.finditer(title):
        if re.search(r"[,，:]\s*$", title[:m.start()]):     # '한화생명, FA 기인 영입'의 한화생명은 데려오는 팀
            continue
        k = _last_team(_win(title, m.start() - 8, m.start()))
        if k:
            out.add(k)
    return out


def _left_team(title: str):
    """'DK 떠나', '젠지와 결별', '한화생명 출신'처럼 떠나는 말 바로 앞(몇 글자 안)에 나온 팀."""
    for w in LEAVE + ("출신",):
        i = title.find(w)
        if i <= 0:
            continue
        before = _win(title, i - 12, i)
        hit = _teams(before)
        if len(hit) == 1:
            return hit[0]
    return None


_DEST = r"(?:\s?[가-힣A-Za-z]{1,6})?\s*(?:행(?![사보진복운렬])|(?:으)?로\s*(?:가나|갈까|향|이적|임대|간다|떠나))"


def _names(nick: str) -> list:
    """닉네임과 한글 표기들(소문자)."""
    return ([nick.lower()] + [ko for en, ko in ko_nicks().items() if en.lower() == nick.lower() and ko]
            + [ko for ko, en in KO_ALT.items() if en.lower() == nick.lower()])


def _dest_after(title: str, nick: str):
    """'[정리] 스펀지 DNS행·클리어 KT행', '구마유시, DK로 가나'처럼 그 선수 이름 뒤(다음 사람 이름 전)에 'OO행'·'OO로 가나'가 있으면 그 팀."""
    at = [i for i in (_name_at(title, n) for n in _names(nick)) if i >= 0]
    if not at:
        return None
    start, end = min(at), len(title)
    for p in persons(title):
        if p == nick.lower():
            continue
        for n in _names(p):
            i = _name_at(title, n)
            if start < i < end:
                end = i
    seg = title[start:end]
    best, pos = None, len(seg)
    for k in _teams(seg):
        rx = _ALIAS_RE.get(k)
        for m in (rx.finditer(seg) if rx else ()):
            if re.match(_DEST, seg[m.end():]) and m.start() < pos:
                best, pos = k, m.start()
    return best


def _leave_mine(title: str, nick: str) -> bool:
    """떠나는 말(떠난·결별·계약 종료…)이 이 사람 얘기인지: 그 말 바로 앞에 나온 사람이 이 사람이거나 사람이 없을 때.
    ("'옴므' 떠난 한화생명, '모글리' 감독 승격"의 '떠난'은 옴므 얘기라 모글리는 잔류(승격))"""
    pos = {}
    for p in persons(title):
        at = [i for i in (_name_at(title, n) for n in _names(p)) if i >= 0]
        if at:
            pos[p] = min(at)
    me = pos.get(nick.lower(), -1)
    for w in LEAVE:
        for m in re.finditer(re.escape(w), title):
            # 이 사람 이름 뒤에 나온 떠나는 말('기인·캐니언과 동행 마침표')이거나, 앞에 아무도 없으면('T1 떠난 도란') 이 사람 얘기
            if 0 <= me < m.start() or not any(i < m.start() for i in pos.values()):
                return True
    return False


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
        # 그 선수 토막 바로 뒤의 사람 없는 토막은 이어지는 말('…T1행 유력')이라 함께 봄
        mine = [p for p in segs if nick.lower() in persons(p)]
        my_teams = set(_teams(" ".join(mine)))
        keep = []
        for i, p in enumerate(segs):
            # (단, '…이동주, DNS와 재계약'처럼 다른 이름(본명)이 주어로 나오면 다른 사람 얘기)
            follows = i > 0 and segs[i - 1] in mine and not persons(p) and not re.match(r"\s*[가-힣]{2,4}(?:,|\s?(?:은|는|이|가)\s)", p)
            if p in mine or follows or (not persons(p) and set(_teams(p)) <= my_teams):
                keep.append(p)
        title = " ".join(keep)
    if any(w in title for w in NEG + UNSURE) or _vacancy_of(title, nick):
        return None
    # '한화생명, 도란 떠나보내고 캐니언 영입': '떠나보내' 앞에 나온 선수는 그 팀을 떠나는 쪽(뒤 선수만 영입)
    sendoff = title.find("떠나보내")
    if sendoff >= 0:
        names = _names(nick)
        at = [i for i in (_name_at(title, n) for n in names) if i >= 0]
        if at and min(at) < sendoff:
            return None
    dest = _dest_after(title, nick)
    if dest and dest != team_from:
        return (dest, False)
    teams = _teams(title)
    left = _left_teams(title)
    # 원소속이 아닌 '떠난 팀'은 행선지가 아님('한화생명 떠나 DN 수퍼스 합류'는 이미 DNS 로스터인 블러핑에게 HLE행이 아님,
    # '젠지 FA 기인·캐니언 영입설'의 젠지는 그 사람들이 떠나온 팀)
    others = [k for k in teams if k != team_from and k not in left]
    renew = any(w in title for w in RENEW + RENEW_MORE) or UNTIL.search(title) or (team_from in teams and any(w in title for w in STAY_UP))
    if renew and not _leave_mine(title, nick) and not others:
        return (team_from, True) if team_from else None
    if team_from and _joined_team(title) == team_from:
        return None                           # '한화생명 출신 블러핑, DNS 합류': 이미 DNS 선수에겐 지금 팀 얘기
    if any(w in title for w in JOIN) and len(others) == 1:
        return (others[0], False)
    # 'DK 떠나 한화생명 서포터로'처럼 '영입' 같은 말 없이 원소속을 떠나 다른 팀 하나로 가는 기사.
    # 떠나는 말 바로 앞의 팀이 원소속일 때만('KT 떠난 커즈, DNS로'는 DNS 선수 기준으로 KT행이 아님)
    if len(others) == 1 and _left_team(title) == team_from:
        return (others[0], False)
    return None


def called_off_hit(title: str, nick: str, team_from: str):
    """'T1, 제우스 영입 무산' 같은 무산·결렬 기사 → 그 선수의 (팀 키, 잔류 여부) 또는 None.
    무산 말을 빼고 같은 규칙으로 읽고, 그래도 안 읽히면 그 선수 + 원소속이 아닌 팀 하나('T1과 협상 결렬')."""
    if not re.search(r"[가-힣]", title) or not any(w in title for w in NEG) or nick.lower() not in persons(title):
        return None
    plain = title
    for w in NEG:
        plain = plain.replace(w, " ")
    hit = read_title(plain, nick, team_from)
    if hit:
        return hit
    others = [k for k in _teams(title) if k != team_from]
    return (others[0], False) if len(others) == 1 else None


def _guess(people, news, marks=None, allow_stay=True, off=None, since=None):  # noqa: F811 (people: 사람 목록)
    """people: [{"page", "nick", "team_from"}] → {page: 유력 정보}. marks를 주면 그 말이 제목에 있는 기사만 봄.
    더 새 기사가 같은 행선지를 '무산·결렬'이라 하면 그 유력은 버림. off(dict)를 주면 {page: {(팀, 잔류 여부)}}로 채워 줌.
    since({page: {"date": 'YYYY-MM-DD', "from": 팀 키}})를 주면 그날보다 앞선 기사는 안 봄(이적·재계약이 확정되기 전 소문),
    그리고 방금 떠나온 팀으로 '다시 이적 유력'도 안 봄('T1 → DK 입단한 도란: T1 이적 유력'은 지난 소문)."""
    out = {}
    for r in people:
        best, gone = None, set()
        st = (since or {}).get(r["page"]) or {}
        cut, came_from = st.get("date") or "", st.get("from") or ""
        for n in news:                          # 최신순
            if cut and (n["published"] or "")[:10] < cut:
                break                           # (최신순이라 이 뒤는 모두 더 예전)
            kind = article_kind(n["title"], "news", (n["outlet"] if "outlet" in n.keys() else "") or "")
            if kind in ("view", "talk"):        # 전망·분석 기사와 커뮤니티 글은 빼고('[기타] 오피셜 HLE 기인 영입'은 발표가 아님)
                continue
            nix = called_off_hit(n["title"], r["nick"], r["team_from"])
            if nix:
                gone.add(nix)
                continue
            if marks and not any(w in n["title"] for w in marks):
                continue
            hit = read_title(n["title"], r["nick"], r["team_from"])
            if not hit or (hit[1] and not allow_stay) or hit in gone or (came_from and hit[0] == came_from and not hit[1]):
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
        if gone and off is not None:
            off[r["page"]] = gone
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
    return _cached("fa", key, lambda: _both(people))[0]


def _both(people, **kw):
    off = {}
    return _guess(people, _recent_news(), off=off, **kw), off


def called_off(fa_rows, roster_rows) -> dict:
    """{page: {(팀 키, 잔류 여부), …}}: 최근 기사가 '무산·결렬'이라 한 행선지(독버섯 판을 일찍 마감하는 데 씀)."""
    rumors(fa_rows)
    movers(roster_rows)
    with _LOCK:
        a = (_CACHE.get("fa") or {}).get("val") or ({}, {})
        b = (_CACHE.get("roster") or {}).get("val") or ({}, {})
    return {**b[1], **a[1]}


def movers(rows) -> dict:
    """계약이 남은 로스터 선수(roster 행)의 이적 유력: 단독·소식통·오피셜·합의·예정 같은 말이 있는 기사에서 다른 팀 합류만 봄(잔류는 뺌).
    예) "[소식통] '시우' 전시우, 2027 LCK 시즌 젠지 합류 예정" → Siwoo: DK → GEN 유력"""
    key = tuple((r["page"], r["team"]) for r in rows)
    people = [{"page": r["page"], "nick": r["nick"], "team_from": r["team"]} for r in rows if r["team"] and r["nick"]]
    now = {r["page"]: r["team"] for r in rows}
    return _cached("roster", key, lambda: _both(people, marks=MOVE_MARK, allow_stay=False, since=_settled(now)))[0]


def _settled(now_team=None) -> dict:
    """{page: {"date", "from"}}: 이번 스토브리그에 이적·재계약이 확정된 날과 떠나온 팀(리그피디아).
    그 전 기사는 지금 팀 기준 소문이 아니고, 떠나온 팀으로 돌아간다는 '이적 유력'도 지난 소문.
    FA 표가 아직 '미정'이어도 로스터에 다른 팀으로 올라와 있으면(now_team) 그 FA 표의 원소속이 떠나온 팀."""
    now_team = now_team or {}
    try:
        with db() as c:
            rows = c.execute("SELECT page, date, status, team_from FROM fa").fetchall()
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for r in rows:
        moved = r["status"] == "move" or (now_team.get(r["page"]) and r["team_from"] and now_team[r["page"]] != r["team_from"])
        if r["status"] in ("move", "stay") or moved:
            out[r["page"]] = {"date": (r["date"] or "")[:10] if r["status"] in ("move", "stay") else "",
                              "from": r["team_from"] if moved else ""}
    return out
