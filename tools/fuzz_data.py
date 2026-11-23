"""데이터 오차 확률 재기: 가짜 세상(선수·FA 표·로스터·기사)을 무작위로 아주 많이 만들어 넣고, 화면이 틀리게 보이는 비율을 셈.

A. 기사 제목 읽기: 실제 기사 말투 틀(오피셜 영입·재계약·유력·무산·떠난 자리·여러 명·경기 기사·영문)에
   팀·선수를 무작위로 넣어 '정답'과 read_title 결과를 비교 → 틀 별·전체 오차율(95% 신뢰구간)
B. 화면끼리 맞는지: 무작위 세상(리그피디아 반영 지연 포함)마다 이적 시장 · 팀별 · 로스터 카드 · 데이터 점검을 그려
   같은 사람이 화면마다 다르게 보이는 경우를 셈

  python3 tools/fuzz_data.py [A 표본 수=20000] [B 세상 수=300] [씨앗=7]
"""
import json
import math
import os
import random
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "fuzz.db")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tracker import cluster, farm, filters, integrity, place, rumor, state  # noqa: E402
from tracker.core import db, init_db  # noqa: E402
from tracker.fa import fill_from_fa  # noqa: E402
from tracker.filters import KO_NICKS  # noqa: E402
from tracker.web import views  # noqa: E402

KEYS = ["hle", "t1", "geng", "dk", "kt", "ns", "bfx", "drx", "dns", "bro"]
KO = {"hle": ["한화생명", "한화생명e스포츠", "HLE"], "t1": ["T1"], "geng": ["젠지"], "dk": ["디플러스 기아", "DK"],
      "kt": ["kt 롤스터", "KT"], "ns": ["농심 레드포스", "농심"], "bfx": ["BNK 피어엑스", "피어엑스"], "drx": ["DRX"],
      "dns": ["DN 수퍼스", "DNS"], "bro": ["OK저축은행 브리온", "브리온"]}
EN = {"hle": "Hanwha Life Esports", "t1": "T1", "geng": "Gen.G", "dk": "Dplus KIA", "kt": "KT Rolster", "ns": "Nongshim RedForce",
      "bfx": "BNK FEARX", "drx": "DRX", "dns": "DN SOOPers", "bro": "OKSavingsBank BRION"}
ROLES = ["Top", "Jungle", "Mid", "Bot", "Support"]
POS_KO = {"Top": "탑", "Jungle": "정글", "Mid": "미드", "Bot": "원딜", "Support": "서포터"}
# 다른 말과 헷갈리는 한글 닉네임(지우·린·꿍…)은 따로 세어 봄
AMBIG = {"지우", "린", "꿍", "남궁", "라이프", "노바", "피터", "조커", "클리어", "커리어", "듀크", "에이밍", "모글리", "마타"}


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def reset_caches():
    state.reset()
    place._C.update(snap=None, val=None)
    with rumor._LOCK:
        rumor._CACHE.clear()
    filters._NAMES["at"] = 0.0
    filters._LEARN["at"] = 0.0
    cluster._PEOPLE["at"] = 0.0


# ── A. 기사 제목 읽기 ────────────────────────────────────────────────────
def T(k, rnd):
    return rnd.choice(KO[k])


def q(ko, rnd):
    """기사처럼: 한 글자 닉네임은 늘 따옴표('린'), 나머지는 따옴표가 있기도 없기도."""
    forms = ["'{}'", "‘{}’", "\"{}\""] + ([] if len(ko) < 2 else ["{}"])
    return rnd.choice(forms).format(ko)


# (이름, 만들기(rnd, A=원소속, B=다른 팀, C=또 다른 팀, p=(nick, ko), p2=(nick, ko)) → (제목, {닉: 정답}))
def templates():
    def mk(name, fn):
        return name, fn
    return [
        mk("오피셜 영입", lambda r, A, B, C, p, p2: (f"[오피셜] {T(B, r)}, {q(p[1], r)} 영입", {p[0]: (B, False)})),
        mk("단독 영입 임박", lambda r, A, B, C, p, p2: (f"[단독] {T(B, r)}, {POS_KO[r.choice(ROLES)]} {q(p[1], r)} 영입 임박", {p[0]: (B, False)})),
        mk("행 유력", lambda r, A, B, C, p, p2: (f"{q(p[1], r)}, {T(B, r)}행 유력", {p[0]: (B, False)})),
        mk("떠나 합류", lambda r, A, B, C, p, p2: (f"{T(A, r)} 떠난 {q(p[1], r)}, {T(B, r)} 합류", {p[0]: (B, False)})),
        mk("계약 합의", lambda r, A, B, C, p, p2: (f"[소식통] {q(p[1], r)}, {T(B, r)}와 계약 합의", {p[0]: (B, False)})),
        mk("이적 확정", lambda r, A, B, C, p, p2: (f"{q(p[1], r)} {T(B, r)} 이적 확정", {p[0]: (B, False)})),
        mk("유니폼", lambda r, A, B, C, p, p2: (f"{q(p[1], r)}, {T(B, r)} 유니폼 입는다", {p[0]: (B, False)})),
        mk("품었다", lambda r, A, B, C, p, p2: (f"{T(B, r)}, FA {q(p[1], r)} 품었다", {p[0]: (B, False)})),
        mk("재계약", lambda r, A, B, C, p, p2: (f"{T(A, r)}, {q(p[1], r)}와 재계약", {p[0]: (A, True)})),
        mk("오피셜 재계약", lambda r, A, B, C, p, p2: (f"[오피셜] {T(A, r)}, {q(p[1], r)}와 2027년까지 재계약", {p[0]: (A, True)})),
        mk("동행 연장", lambda r, A, B, C, p, p2: (f"{q(p[1], r)}, {T(A, r)}와 동행 이어간다", {p[0]: (A, True)})),
        mk("잔류 확정", lambda r, A, B, C, p, p2: (f"{T(A, r)} {q(p[1], r)} 잔류 확정", {p[0]: (A, True)})),
        mk("결별(행선지 없음)", lambda r, A, B, C, p, p2: (f"{T(A, r)}, {q(p[1], r)}와 결별", {p[0]: None})),
        mk("FA 시장행", lambda r, A, B, C, p, p2: (f"{q(p[1], r)} 등 FA 시장행…스토브리그 개막", {p[0]: None})),
        mk("영입 무산", lambda r, A, B, C, p, p2: (f"{T(B, r)}, {q(p[1], r)} 영입 무산", {p[0]: None})),
        mk("재계약 불발", lambda r, A, B, C, p, p2: (f"{T(A, r)} {q(p[1], r)} 재계약 불발", {p[0]: None})),
        mk("떠난 자리", lambda r, A, B, C, p, p2: (f"{T(A, r)}, {q(p[1], r)} 떠난 자리에 {q(p2[1], r)} 영입", {p[0]: None, p2[0]: ((A, False), C)})),
        mk("두 명 영입", lambda r, A, B, C, p, p2: (f"[오피셜] {T(B, r)}, {q(p[1], r)}·{q(p2[1], r)} 영입", {p[0]: (B, False), p2[0]: (B, False)})),
        mk("두 명 각자", lambda r, A, B, C, p, p2: (f"{q(p[1], r)} {T(B, r)} 이적 유력…{q(p2[1], r)}는 {T(C, r)} 합류", {p[0]: (B, False), p2[0]: (C, False)})),
        mk("떠나보내고", lambda r, A, B, C, p, p2: (f"{T(A, r)}, {q(p2[1], r)} 떠나보내고 {q(p[1], r)} 영입", {p[0]: ((A, False), C), p2[0]: None})),
        mk("경기 기사", lambda r, A, B, C, p, p2: (f"{T(A, r)} {q(p[1], r)}, {T(B, r)}전 승리 이끌어", {p[0]: None})),
        mk("품에 안다", lambda r, A, B, C, p, p2: (f"{q(p[1], r)}, {T(B, r)} 품에 안겼다", {p[0]: (B, False)})),
        mk("데려온다", lambda r, A, B, C, p, p2: (f"{T(B, r)}, {T(A, r)} 출신 {q(p[1], r)} 데려온다", {p[0]: (B, False)})),
        mk("팀 이름 겹침(DNS·NS)", lambda r, A, B, C, p, p2: (f"[오피셜] {r.choice(['DNS', 'DN 수퍼스'])}, {q(p[1], r)} 영입",
                                                        {p[0]: (("dns", False), "ns")})),
        # 까다로운 기사(실제로 자주 보이는 말투)
        mk("스토브 정리 목록", lambda r, A, B, C, p, p2: (f"[스토브리그 정리] {q(p[1], r)} {T(B, r)}행·{q(p2[1], r)} {T(C, r)}행",
                                                    {p[0]: (B, False), p2[0]: (C, False)})),
        mk("물음표 추측", lambda r, A, B, C, p, p2: (f"{q(p[1], r)}, {T(B, r)}로 가나", {p[0]: (B, False)})),
        mk("영입전 경쟁", lambda r, A, B, C, p, p2: (f"{q(p[1], r)} 영입전…{T(B, r)}·{T(C, r)} 경쟁", {p[0]: None})),
        mk("사실무근", lambda r, A, B, C, p, p2: (f"{T(B, r)} \"{q(p[1], r)} 영입설 사실무근\"", {p[0]: None})),
        mk("은퇴", lambda r, A, B, C, p, p2: (f"{T(A, r)} {q(p[1], r)}, 은퇴 선언", {p[0]: None})),
        mk("인터뷰", lambda r, A, B, C, p, p2: (f"{q(p[1], r)} \"{T(A, r)}에서 우승하고 싶다\"", {p[0]: None})),
        mk("경기 상대", lambda r, A, B, C, p, p2: (f"{T(A, r)} {q(p[1], r)}, {T(B, r)} 상대로 펜타킬", {p[0]: None})),
        mk("임대", lambda r, A, B, C, p, p2: (f"{q(p[1], r)}, {T(B, r)}로 임대 이적", {p[0]: (B, False)})),
        mk("전 감독 선임", lambda r, A, B, C, p, p2: (f"{T(B, r)}, 전 {T(A, r)} 감독 {q(p[1], r)} 선임", {p[0]: (B, False)})),
        mk("감독 선임", lambda r, A, B, C, p, p2: (f"{T(B, r)}, {q(p[1], r)} 신임 감독 선임", {p[0]: (B, False)})),
        mk("EN joins", lambda r, A, B, C, p, p2: (f"{p[0]} joins {EN[B]}", {p[0]: (B, False)})),
        mk("EN sources", lambda r, A, B, C, p, p2: (f"Sources: {p[0]} set to join {EN[B]}", {p[0]: (B, False)})),
        mk("EN re-sign", lambda r, A, B, C, p, p2: (f"{EN[A]} re-signs {p[0]} through 2027", {p[0]: (A, True)})),
        mk("EN leaves", lambda r, A, B, C, p, p2: (f"{p[0]} leaves {EN[A]}", {p[0]: None})),
        mk("EN fell through", lambda r, A, B, C, p, p2: (f"{EN[B]} deal for {p[0]} fell through", {p[0]: None})),
    ]


def holdout():
    """추가 말투 틀: 처음엔 규칙이 못 읽던 말투(첫 결과 53.8% 오차 → 규칙 보강). 새 말투를 찾으면 여기에 더함."""
    def mk(name, fn):
        return name, fn
    return [
        mk("영입 공식 발표", lambda r, A, B, C, p, p2: (f"{T(B, r)}, {q(p[1], r)} 영입 공식 발표", {p[0]: (B, False)})),
        mk("새 팀은", lambda r, A, B, C, p, p2: (f"{q(p[1], r)} 새 팀은 {T(B, r)}", {p[0]: (B, False)})),
        mk("새 포지션", lambda r, A, B, C, p, p2: (f"{T(B, r)} 새 {POS_KO[r.choice(ROLES)]} {q(p[1], r)}", {p[0]: (B, False)})),
        mk("떠난다", lambda r, A, B, C, p, p2: (f"{q(p[1], r)}, {T(A, r)} 떠난다", {p[0]: None})),
        mk("협상 중", lambda r, A, B, C, p, p2: (f"{q(p[1], r)}, {T(B, r)}와 협상 중", {p[0]: (B, False)})),
        mk("붙잡았다", lambda r, A, B, C, p, p2: (f"{T(A, r)}, {q(p[1], r)} 붙잡았다", {p[0]: (A, True)})),
        mk("재계약 난항", lambda r, A, B, C, p, p2: (f"{T(A, r)} {q(p[1], r)} 재계약 협상 난항", {p[0]: None})),
        mk("유니폼 입은", lambda r, A, B, C, p, p2: (f"{T(B, r)} 유니폼 입은 {q(p[1], r)}", {p[0]: (B, False)})),
        mk("결별한 팀", lambda r, A, B, C, p, p2: (f"{q(p[1], r)}·{q(p2[1], r)} 결별한 {T(A, r)}, 리빌딩 착수", {p[0]: None, p2[0]: None})),
        mk("영입 추진", lambda r, A, B, C, p, p2: (f"{T(B, r)}, {q(p[1], r)} 영입 추진", {p[0]: (B, False)})),
        mk("거취 미정 관심", lambda r, A, B, C, p, p2: (f"{q(p[1], r)} 거취 미정…{T(B, r)}·{T(C, r)} 관심", {p[0]: None})),
        mk("EN announce", lambda r, A, B, C, p, p2: (f"{EN[B]} announce {p[0]} as new {r.choice(['top', 'mid'])} laner", {p[0]: (B, False)})),
        mk("EN to stay", lambda r, A, B, C, p, p2: (f"{p[0]} to stay at {EN[A]}", {p[0]: (A, True)})),
        mk("새 출발", lambda r, A, B, C, p, p2: (f"{q(p[1], r)}, {T(B, r)}서 새 출발", {p[0]: (B, False)})),
    ]


def part_a(n, rnd, tpls=None):
    players = [(en, ko) for en, ko in KO_NICKS.items() if ko]
    with db() as c:
        c.execute("DELETE FROM fa")
        c.executemany("INSERT INTO fa(page,nick,real,team_from,role,status,team_to,team_to_name,until,date,memo) "
                      "VALUES(?,?,'','hle','Top','fa','','','','','')", [(en, en) for en, _ in players])
    reset_caches()
    tpls = tpls or templates()
    stat = defaultdict(Counter)
    kinds = Counter()
    bad_examples = defaultdict(list)
    for _ in range(n):
        name, fn = rnd.choice(tpls)
        A, B, C = rnd.sample(KEYS, 3)
        p, p2 = rnd.sample(players, 2)
        title, truth = fn(rnd, A, B, C, p, p2)
        for nick, want in truth.items():
            frm = A
            if isinstance(want, tuple) and len(want) == 2 and isinstance(want[0], tuple):
                want, frm = want                              # (정답, 원소속)
            got = rumor.read_title(title, nick, frm)
            ok = got == want
            ko = dict(players)[nick]
            # 틀린 종류: 엉뚱한 팀(가장 나쁨) · 없는데 있다고(헛유력) · 있는데 못 읽음(놓침)
            kind = "ok" if ok else ("wrong" if got and want else "false+" if got else "miss")
            stat[name][kind] += 1
            kinds[kind] += 1
            if ko in AMBIG:
                stat["(헷갈리는 닉네임)"][kind] += 1
            if not ok and len(bad_examples[name]) < 3:
                bad_examples[name].append((title, nick, frm, want, got))
    return stat, kinds, bad_examples


# ── B. 화면끼리 맞는지 ──────────────────────────────────────────────────
def world(rnd, now):
    """선수 60명쯤: 계약 중(로스터만) · FA 미정 · FA 잔류 · FA 이적. 리그피디아 로스터는 일부러 늦게(지연) 반영되기도."""
    players = [(en, ko) for en, ko in KO_NICKS.items() if ko]
    rnd.shuffle(players)
    fa, roster, news, truth = [], [], [], {}
    lag = {}
    for i, (nick, ko) in enumerate(players[:60]):
        team = KEYS[i % 10]
        role = ROLES[(i // 10) % 5]
        kind = rnd.choices(["contract", "fa", "stay", "move", "ahead"], [33, 24, 19, 19, 5])[0]
        d = (now - timedelta(days=rnd.randint(1, 6))).strftime("%Y-%m-%d")
        if kind == "contract":
            roster.append((team, role, nick, nick, "", "2027-11-30", 0))
            truth[nick] = ("contract", team)
            if rnd.random() < 0.15:                           # 계약 중 선수 이적설
                b = rnd.choice([k for k in KEYS if k != team])
                news.append((f"[단독] {T(b, rnd)}, {q(ko, rnd)} 영입 임박", now - timedelta(hours=rnd.randint(1, 100))))
            continue
        if kind == "ahead":                                   # 도란처럼: 로스터엔 새 팀(B), FA 목록은 아직 원소속 '미정'
            b = rnd.choice([k for k in KEYS if k != team])
            fa.append((nick, nick, "", team, role, "fa", "", "", "", d, "계약 만료"))
            roster.append((b, role, nick, nick, "", "2027-11-30", 1))
            truth[nick] = ("move", b)
            lag[nick] = "fa-behind"
            if rnd.random() < 0.5:                            # 옛 소문(원소속 잔류 유력·다른 팀 유력)
                news.append((f"{q(ko, rnd)}, {T(rnd.choice(KEYS), rnd)}행 유력", now - timedelta(days=rnd.randint(3, 9))))
            continue
        if kind == "fa":
            fa.append((nick, nick, "", team, role, "fa", "", "", "", d, "계약 만료"))
            truth[nick] = ("fa", team)
            x = rnd.random()
            if x < 0.25:                                      # 오피셜 기사(리그피디아 반영 전)
                if rnd.random() < 0.5:
                    b = rnd.choice([k for k in KEYS if k != team])
                    news.append((f"[오피셜] {T(b, rnd)}, {q(ko, rnd)} 영입", now - timedelta(hours=rnd.randint(1, 48))))
                    truth[nick] = ("official-move", b)
                else:
                    news.append((f"[오피셜] {T(team, rnd)}, {q(ko, rnd)}와 재계약", now - timedelta(hours=rnd.randint(1, 48))))
                    truth[nick] = ("official-stay", team)
            elif x < 0.6:                                     # 유력 기사
                b = rnd.choice([k for k in KEYS if k != team])
                news.append((f"{q(ko, rnd)}, {T(b, rnd)}행 유력", now - timedelta(hours=rnd.randint(1, 100))))
                truth[nick] = ("rumor", b)
            continue
        dest = team if kind == "stay" else rnd.choice([k for k in KEYS if k != team])
        fa.append((nick, nick, "", team, role, kind, dest, "", "", d, "재계약" if kind == "stay" else ""))
        truth[nick] = (kind, dest)
        if rnd.random() < 0.3:                                # 확정 전 옛 소문(다른 팀행 유력)
            other = rnd.choice([k for k in KEYS if k not in (team, dest)])
            news.append((f"{q(ko, rnd)}, {T(other, rnd)}행 유력", datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc) - timedelta(days=2)))
        y = rnd.random()
        if y < 0.2:                                           # 리그피디아 로스터 반영 지연: 아직 옛 팀에 있음
            roster.append((team, role, nick, nick, "", "", 0))
            lag[nick] = "old"
        elif y < 0.3:                                         # 아직 어느 로스터에도 없음
            lag[nick] = "none"
        else:
            roster.append((dest, role, nick, nick, "", "2027-11-30", int(dest != team)))
    return fa, roster, news, truth, lag


def load(fa, roster, news):
    # 실제 수집과 같게: 리그피디아 로스터에서 빠진 잔류·이적 확정 선수는 FA 기록으로 채움(fa.fill_from_fa)
    roster = [r[1:] for r in fill_from_fa([("lck",) + tuple(r) for r in roster], fa, set(KEYS))]
    with db() as c:
        c.execute("DELETE FROM fa")
        c.execute("DELETE FROM roster")
        c.execute("DELETE FROM items")
        c.execute("DELETE FROM farm_items")
        c.executemany("INSERT INTO fa(page,nick,real,team_from,role,status,team_to,team_to_name,until,date,memo) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?)", fa)
        c.executemany("INSERT OR REPLACE INTO roster(league,team,role,page,nick,real,until,joined) VALUES('lck',?,?,?,?,?,?,?)", roster)
        for i, (t, at) in enumerate(news):
            iso = at.isoformat()
            c.execute("INSERT INTO items(id,team,source,title,url,outlet,published,first_seen,league) VALUES(?,?,?,?,?,?,?,?,'lck')",
                      (f"n{i}", "", "news", t, f"https://e.com/{i}", "인벤", iso, iso))
    reset_caches()


def screens():
    """화면에서 사람마다 보이는 것 뽑기: 이적 시장(상태·유력 팀) · 팀별(줄) · 로스터 카드(어느 팀 카드에 확정으로)."""
    fa_html = views.render_fa("lck")
    falist = {}
    for m in re.finditer(r'class="fa-row" data-page="([^"]+)"(.*?)</li>', fa_html, re.S):
        s = re.search(r'data-s="(\w+)"', m.group(0))
        falist[m.group(1)] = s.group(1) if s else "?"
    sm_html = views.render_summary("lck")
    summ = defaultdict(set)
    for card in re.finditer(r'<article class="scard" id="m-(\w+)".*?</article>', sm_html, re.S):
        k = card.group(1)
        for line in re.finditer(r'<div class="sl (\w+)"><em>.*?</em><div>(.*?)</div></div>', card.group(0), re.S):
            for nick in re.findall(r'<span class="pc [^"]*"[^>]*>([^<]+)<small>', line.group(2)):
                summ[nick].add((k, line.group(1)))
    ro_html = views.render_roster("lck")
    cards = defaultdict(set)
    for art in re.finditer(r'<article class="rc[^"]*"[^>]*data-team="(\w+)".*?</article>', ro_html, re.S):
        k = art.group(1)
        for li in re.finditer(r"<li([^>]*)>(.*?)</li>", art.group(0), re.S):
            body = li.group(2)
            first = True
            for sp in re.finditer(r'<span class="(pn(?: sub)?)"[^>]*data-page="([^"]+)"[^>]*>[^<]*</span>((?:(?!<span class="pn).)*)', body, re.S):
                tail = sp.group(3)
                rm = ('class="in rm' in tail or 'class="in s rm' in tail or "rml" in body[max(0, sp.start() - 30):sp.start()]
                      or (first and "rmv" in li.group(1)))     # 빈자리에 들어올 것 같은 선수(유력): 맨 끝에 '유력' 표
                first = False
                cards[sp.group(2)].add((k, "rm" if rm else "in"))
    return falist, summ, cards


def part_b(n, rnd):
    now = datetime.now(timezone.utc)
    checks = Counter()
    fails = Counter()
    examples = defaultdict(list)
    integ = Counter()
    for w in range(n):
        fa, roster, news, truth, lag = world(rnd, now)
        load(fa, roster, news)
        falist, summ, cards = screens()
        snap = state.get()
        rms = snap["rumors"]
        probs = integrity.check()
        # 숫자: 이적 시장 버튼 숫자 = 소식 화면·오른쪽 요약 숫자(fa_counts)
        fa_html = views.render_fa("lck")
        btn = {k: int(v) for k, v in re.findall(r'>(전체|확정|잔류|미정|유력) <b>(\d+)</b></button>', fa_html)}
        cnt = views.fa_counts()
        checks["숫자 일치(이적 시장=요약)"] += 1
        if {k: v for k, v in btn.items() if k != "전체"} != {"확정": cnt.get("move", 0), "잔류": cnt.get("stay", 0),
                                                              "미정": cnt.get("fa", 0), "유력": cnt.get("rm", 0)}:
            fails["숫자 일치(이적 시장=요약)"] += 1
        checks["네 칸 합 = FA 전체"] += 1
        if btn.get("전체") != sum(v for k, v in btn.items() if k != "전체"):
            fails["네 칸 합 = FA 전체"] += 1
        sm_html = views.render_summary("lck")
        st = {k: int(v) for v, k in re.findall(r'<span><b>(\d+)</b>(영입|잔류|미정|유력)</span>', sm_html)}
        checks["숫자 일치(이적 시장=팀별)"] += 1
        if (st.get("미정"), st.get("유력")) != (btn.get("미정"), btn.get("유력")):
            fails["숫자 일치(이적 시장=팀별)"] += 1
        # 독버섯 판: 이미 확정된 사람의 판이 '열린 판'으로 남지 않음(만들고 → 결과 매기기)
        farm.sync(force=True)
        farm.sync(force=True)
        with db() as c:
            open_pages = {r["page"] for r in c.execute("SELECT page FROM farm_items WHERE result IS NULL AND kind='rumor'")}
        flagged = {p.get("page") for p in probs if isinstance(p, dict)} | {
            m for p in probs for m in re.findall(r"[A-Za-z][\w.]+", str(p)) if m in truth}

        def bad(rule, nick, detail):
            fails[rule] += 1
            if len(examples[rule]) < 3:
                examples[rule].append((nick, truth[nick], lag.get(nick, ""), detail))

        for nick, (kind, team) in truth.items():
            row = next((r for r in snap["fa"] if r["page"] == nick), None)
            # 화면 규칙(사람이 기대하는 것)
            if kind in ("move", "official-move"):
                exp_status = "move"
            elif kind in ("stay", "official-stay"):
                exp_status = "stay"
            elif kind in ("fa", "rumor"):
                exp_status = "fa"
            else:
                exp_status = None
            if row:
                checks["이적 시장 상태"] += 1
                if falist.get(nick) != exp_status:
                    bad("이적 시장 상태", nick, falist.get(nick))
            # 팀별: 확정 이적이면 도착 팀 '영입' + 원소속 '이탈', 잔류면 원소속 '잔류', 미정이면 '미정' 또는 '유력'
            s = summ.get(nick, set())
            if row:
                checks["팀별 줄"] += 1
                frm = row["team_from"]
                if exp_status == "move":
                    want = {(team, "in"), (frm, "out")}
                    ok = s == want
                elif exp_status == "stay":
                    ok = s == {(frm, "stay")}
                else:   # 미정: 기사 추측이 없으면 원소속 카드 '미정'만, 있으면 원소속 카드 '유력' + (이적 유력이면) 행선지 카드 '유력'
                    g = rms.get(nick)
                    if g and not g["official"]:
                        ok = s == ({(frm, "rm")} | ({(g["team"], "rm")} if not g["stay"] and g["team"] in KEYS else set()))
                    else:
                        ok = s == {(frm, "open")}
                if not ok:
                    bad("팀별 줄", nick, sorted(s))
                # 팀별 유력 줄의 팀 = 이적 시장의 유력 팀
                rm = rms.get(nick)
                if exp_status == "fa" and rm and not rm["stay"] and not rm["official"]:
                    checks["유력 팀 일치(이적 시장=팀별)"] += 1
                    if (rm["team"], "rm") not in s:
                        bad("유력 팀 일치(이적 시장=팀별)", nick, (rm["team"], sorted(s)))
            checks["독버섯 판"] += 1
            if nick in open_pages and kind in ("move", "stay"):
                bad("독버섯 판", nick, "확정됐는데 열린 판")
            # 로스터 카드: 확정(오피셜 포함)된 사람은 정확히 한 팀 카드에 '확정'으로. 두 팀 카드에 확정으로 보이면 모순
            c = cards.get(nick, set())
            sure = {k for k, t in c if t == "in"}
            checks["로스터 카드 한 팀"] += 1
            if len(sure) > 1:
                bad("로스터 카드 한 팀", nick, sorted(c))
            if kind in ("move", "stay", "official-move", "official-stay", "contract"):
                checks["로스터 카드 위치"] += 1
                lv = snap["leaving"].get(nick) if kind == "contract" else None
                if lv and lv["team"] in KEYS and lv["team"] != team:
                    # 계약 중인데 다른 LCK 팀 이적 기사: 원래 팀 카드엔 없고 가는 팀 카드에만(유력, 오피셜이면 확정 칸)
                    if c != {(lv["team"], "in" if lv["official"] else "rm")}:
                        bad("로스터 카드 위치", nick, ("leaving", lv["team"], sorted(c)))
                elif sure != {team}:
                    bad("로스터 카드 위치", nick, sorted(c))
            # 데이터 점검: 리그피디아 로스터가 FA 확정보다 늦은 사람을 잡아내는지
            if lag.get(nick) == "fa-behind":
                integ["FA 목록 지연"] += 1
                integ["FA 지연 알림"] += nick in flagged
            elif row and not lag.get(nick):
                integ["지연 없음"] += 1
                integ["헛경보"] += nick in flagged
        if (w + 1) % 50 == 0:
            print(f"  세상 {w + 1}/{n}", file=sys.stderr)
    return checks, fails, examples, integ



# ── C. 실제 기사 제목(2026.11 teemofarm.com에 모인 스토브리그 기사) + 사람이 매긴 정답 ─────────────
# (제목, 닉네임, 원소속, 정답): 정답 = (팀, 잔류 여부) 또는 None(행선지 없음)
REAL = [(x["title"], x["nick"], x["from"], tuple(x["want"]) if x["want"] else None)
        for x in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "fixtures",
                                             "real_titles_2026.json"), encoding="utf-8"))]


def part_c():
    """실제 기사 표본: 사람이 매긴 정답과 비교."""
    nicks = sorted({x[1] for x in REAL} | set(KO_NICKS))
    with db() as c:
        c.execute("DELETE FROM fa")
        c.execute("DELETE FROM roster")
        c.executemany("INSERT INTO fa(page,nick,real,team_from,role,status,team_to,team_to_name,until,date,memo) "
                      "VALUES(?,?,'','hle','Top','fa','','','','','')", [(n, n) for n in nicks])
    reset_caches()
    res = Counter()
    bad = []
    for title, nick, frm, want in REAL:
        got = rumor.read_title(title, nick, frm)
        kind = "ok" if got == want else ("wrong" if got and want else "false+" if got else "miss")
        res[kind] += 1
        if kind != "ok":
            bad.append((kind, title, nick, frm, want, got))
    return res, bad


def main():
    na = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    nb = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 7
    rnd = random.Random(seed)
    init_db()
    farm.init()
    print(f"# A. 기사 제목 읽기 — 표본 {na:,}개 (씨앗 {seed})")
    stat, kinds, ex = part_a(na, rnd)
    tot = sum(kinds.values())
    err = tot - kinds["ok"]
    p, lo, hi = wilson(err, tot)
    print(f"전체 오차율 {p:.2%} (95% 구간 {lo:.2%}~{hi:.2%}) · 판정 {tot:,}건")
    for k in ("wrong", "false+", "miss"):
        p2, lo2, hi2 = wilson(kinds[k], tot)
        print(f"  {dict(wrong='엉뚱한 팀', **{'false+': '헛유력(없는 행선지)', 'miss': '놓침'})[k]}: {p2:.2%} ({lo2:.2%}~{hi2:.2%})")
    print("틀 별 오차율:")
    for name, c in sorted(stat.items(), key=lambda x: -(sum(x[1].values()) - x[1]["ok"]) / max(1, sum(x[1].values()))):
        n = sum(c.values())
        e = n - c["ok"]
        print(f"  {name:<18} {e / n:6.1%}  ({e}/{n})  엉뚱 {c['wrong']} · 헛 {c['false+']} · 놓침 {c['miss']}")
    for name, xs in ex.items():
        for t, nick, A, want, got in xs[:2]:
            print(f"    예) [{name}] {t!r} · {nick}(원소속 {A}) 정답 {want} → 읽음 {got}")
    print(f"\n# C. 실제 기사 표본 {len(REAL)}건(teemofarm.com에 모인 2026.11 스토브리그 기사, 정답은 사람이 매김)")
    rc, bad = part_c()
    n = sum(rc.values())
    p, lo, hi = wilson(n - rc["ok"], n)
    print(f"오차율 {p:.1%} (95% 구간 {lo:.1%}~{hi:.1%}) · 엉뚱 {rc['wrong']} · 헛유력 {rc['false+']} · 놓침 {rc['miss']} / {n}건")
    for x in bad:
        print(f"  [{x[0]}] {x[1]!r} · {x[2]}({x[3] or '-'}) 정답 {x[4]} → 읽음 {x[5]}")
    print("\n# A'. 추가 말투 틀(처음 돌렸을 땐 53.8% 틀려서 규칙을 보강함 — 이제 완전한 검증용은 아님)")
    stat2, kinds2, ex2 = part_a(max(2000, na // 4), rnd, holdout())
    tot2 = sum(kinds2.values())
    p, lo, hi = wilson(tot2 - kinds2["ok"], tot2)
    print(f"전체 오차율 {p:.2%} (95% 구간 {lo:.2%}~{hi:.2%}) · 엉뚱 {kinds2['wrong']} · 헛유력 {kinds2['false+']} · 놓침 {kinds2['miss']} / {tot2:,}건")
    for name, c in sorted(stat2.items(), key=lambda x: -(sum(x[1].values()) - x[1]["ok"]) / max(1, sum(x[1].values()))):
        n = sum(c.values())
        e = n - c["ok"]
        if e:
            print(f"  {name:<18} {e / n:6.1%}  엉뚱 {c['wrong']} · 헛 {c['false+']} · 놓침 {c['miss']}  예) {(ex2[name] or [('', '', '', '', '')])[0][0]!r} → {(ex2[name] or [('', '', '', '', '')])[0][4]}")
    print(f"\n# B. 화면끼리 맞는지 — 무작위 세상 {nb}개(세상마다 60명)")
    checks, fails, exb, integ = part_b(nb, rnd)
    allc = sum(checks.values())
    allf = sum(fails.values())
    p, lo, hi = wilson(allf, allc)
    print(f"전체 모순율 {p:.3%} (95% 구간 {lo:.3%}~{hi:.3%}) · 점검 {allc:,}건")
    for rule, n in checks.items():
        p2, lo2, hi2 = wilson(fails[rule], n)
        print(f"  {rule:<24} {p2:7.3%} ({fails[rule]}/{n})")
    for rule, xs in exb.items():
        for x in xs:
            print(f"    예) [{rule}] {x}")
    if integ["FA 목록 지연"]:
        print(f"데이터 점검(운영 알림): 리그피디아 FA 목록이 로스터보다 늦은 {integ['FA 목록 지연']}건 중 {integ['FA 지연 알림']}건 알림"
              f" · 지연 없는 {integ['지연 없음']}건 중 헛경보 {integ['헛경보']}건")


if __name__ == "__main__":
    main()
