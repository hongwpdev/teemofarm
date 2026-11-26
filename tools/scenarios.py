"""상황별 점검: 실제로 있었던(또는 있을 법한) 이적 상황을 하나씩 데이터로 넣고, 모든 화면이 기대대로 보이는지 확인.

무작위 점검(fuzz_data.py)은 '화면끼리 서로 다른 말을 하는지'를 봄. 여기는 사람이 정한 규칙(정답)을 상황마다 적어 두고 그대로 나오는지 봄:
  - 상태 말 4개(확정·잔류·유력·미정), 모든 화면 같은 말·같은 행선지
  - 로스터 카드는 한 사람당 한 카드(유력·확정이면 가는 팀), 원래 팀엔 안 보임
  - 숫자(이적 시장 칸 · 소식 숫자 줄 · 오른쪽 요약 · 팀별 숫자)가 모두 같음
새 상황(제보)이 생기면 SCENARIOS에 한 줄 더함.

    python3 tools/scenarios.py            # 상황마다 따로 + 전부 한꺼번에(한 세상) 점검, 틀리면 종료 코드 1
    SCENARIO=all python3 tools/dev_server.py   # 전부 넣은 세상으로 시험 서버 → 브라우저로 직접 보기·crawl.js
"""
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone

if __name__ == "__main__":
    os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "scenarios.db"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tracker import cluster, filters, place, rumor, state  # noqa: E402
from tracker.core import db  # noqa: E402
from tracker.fa import fill_from_fa  # noqa: E402

KEYS = ["hle", "t1", "geng", "dk", "kt", "ns", "bfx", "drx", "dns", "bro"]


def F(page, frm, role, status="fa", to="", to_name=""):
    """FA 목록 한 줄(리그피디아)."""
    return (page, page, "", frm, role, status, to, to_name, "", "2026-11-18", "")


def R(team, role, page, joined=0, until="2027-11-30"):
    """로스터 한 줄(리그피디아 계약)."""
    return (team, role, page, page, "", until, joined)


# 상황: (이름, 설명, FA 목록, 로스터, 기사 [(제목, 몇 시간 전)], 정답 {닉: {...}})
# 정답 칸: fa = 이적 시장 상태 말(목록에 없으면 None) · card = (로스터 카드 팀, on|news|rm) 또는 None(어느 카드에도 없음)
#          sum = 팀별 줄 {(팀, in|out|stay|rm|open)} · board = 이동 보드 (행선지, 말) 또는 None · pos = 직책 글자(모든 화면 같게)
SCENARIOS = [
    ("계약 중 후보가 다른 팀 유력(루시드)", "DK 정글은 카나비(영입), 루시드는 계약 남았지만 DRX 유력 기사",
     [], [R("dk", "Jungle", "Kanavi", 1), R("dk", "Jungle", "Lucid")],
     [("[단독] DRX, '루시드' 영입 임박", 3)],
     {"Lucid": {"fa": "유력", "card": ("drx", "rm"), "sum": {("drx", "rm"), ("dk", "rm")}, "board": ("drx", "유력")},
      "Kanavi": {"fa": None, "card": ("dk", "on")}}),
    ("계약 중 주전이 다른 팀 유력(듀로)", "GEN 서폿 듀로가 DRX 유력 → GEN 서폿은 빈자리, DRX 서폿에 유력",
     [], [R("geng", "Support", "Duro")],
     [("[단독] DRX, '듀로' 영입 임박", 4)],
     {"Duro": {"fa": "유력", "card": ("drx", "rm"), "sum": {("drx", "rm"), ("geng", "rm")}, "board": ("drx", "유력")}}),
    ("맞바꾸기 유력(딜라이트↔커리어)", "HLE 딜라이트는 DK, DK 커리어는 HLE 유력 → 각자 가는 팀 카드에만",
     [], [R("hle", "Support", "Delight"), R("dk", "Support", "Career")],
     [("[단독] 디플러스 기아, '딜라이트' 영입 임박", 5), ("[단독] 한화생명, '커리어' 영입 임박", 5)],
     {"Delight": {"fa": "유력", "card": ("dk", "rm"), "sum": {("dk", "rm"), ("hle", "rm")}, "board": ("dk", "유력")},
      "Career": {"fa": "유력", "card": ("hle", "rm"), "sum": {("hle", "rm"), ("dk", "rm")}, "board": ("hle", "유력")}}),
    ("FA 미정 + 다른 팀 유력(기인)", "FA 목록 미정, 기사는 HLE행 유력 → 이적 시장 유력, HLE 카드 유력, 팀별은 양쪽",
     [F("Kiin", "geng", "Top")], [],
     [("'기인', 한화생명행 유력", 6)],
     {"Kiin": {"fa": "유력", "card": ("hle", "rm"), "sum": {("hle", "rm"), ("geng", "rm")}, "board": ("hle", "유력")}}),
    ("FA 미정 + 오피셜 이적(리그피디아 반영 전, 제우스)", "오피셜 기사가 나오면 리그피디아 전이라도 확정",
     [F("Zeus", "hle", "Top")], [],
     [("[오피셜] T1, '제우스' 영입", 2)],
     {"Zeus": {"fa": "확정", "card": ("t1", "news"), "sum": {("t1", "in"), ("hle", "out")}, "board": ("t1", "확정")}}),
    ("FA 미정 + 오피셜 재계약(쵸비)", "오피셜 재계약이면 잔류(원래 팀 카드를 채움)",
     [F("Chovy", "geng", "Mid")], [],
     [("[오피셜] 젠지, '쵸비'와 2027년까지 재계약", 2)],
     {"Chovy": {"fa": "잔류", "card": ("geng", "news"), "sum": {("geng", "stay")}, "board": None}}),
    ("FA 미정 + 잔류 쪽 기사(페이즈)", "재계약 임박 기사 = 잔류 쪽 추측도 '유력'(원래 팀 카드에)",
     [F("Peyz", "t1", "Bot")], [],
     [("T1, '페이즈'와 재계약 임박", 7)],
     {"Peyz": {"fa": "유력", "card": ("t1", "rm"), "sum": {("t1", "rm")}, "board": None}}),
    ("FA 미정, 기사 없음(바이퍼)", "아무 카드에도 없고 이적 시장·팀별은 미정",
     [F("Viper", "hle", "Bot")], [], [],
     {"Viper": {"fa": "미정", "card": None, "sum": {("hle", "open")}, "board": None}}),
    ("리그피디아 확정 이적(도란)", "FA 목록 확정 + 새 팀 로스터",
     [F("Doran", "t1", "Top", "move", "dk")], [R("dk", "Top", "Doran", 1)], [],
     {"Doran": {"fa": "확정", "card": ("dk", "on"), "sum": {("dk", "in"), ("t1", "out")}, "board": ("dk", "확정")}}),
    ("리그피디아 잔류(케리아)", "FA 목록 잔류 + 원래 팀 로스터",
     [F("Keria", "t1", "Support", "stay", "t1")], [R("t1", "Support", "Keria")], [],
     {"Keria": {"fa": "잔류", "card": ("t1", "on"), "sum": {("t1", "stay")}, "board": None}}),
    ("FA 목록이 늦음(캐니언)", "FA 목록은 아직 미정인데 리그피디아 로스터엔 HLE → 모든 화면 HLE 확정",
     [F("Canyon", "geng", "Jungle")], [R("hle", "Jungle", "Canyon", 1)], [],
     {"Canyon": {"fa": "확정", "card": ("hle", "on"), "sum": {("hle", "in"), ("geng", "out")}, "board": ("hle", "확정")}}),
    ("확정 뒤 옛 소문(비디디)", "이미 GEN 확정인데 예전 'T1행 유력' 기사 → 무시",
     [F("Bdd", "kt", "Mid", "move", "geng")], [R("geng", "Mid", "Bdd", 1)],
     [("'비디디', T1행 유력", 30)],
     {"Bdd": {"fa": "확정", "card": ("geng", "on"), "sum": {("geng", "in"), ("kt", "out")}, "board": ("geng", "확정")}}),
    ("선수가 코치로 간다는 기사(손스타)", "서폿 선수가 코치로 간다는 기사 → 모든 화면 '코치', HLE 감독·스태프 칸에 유력",
     [F("Sonstar", "ns", "Support")], [],
     [("[단독] 한화생명e스포츠, '손스타' 코치 합류 유력", 8)],
     {"Sonstar": {"fa": "유력", "card": ("hle", "rm"), "sum": {("hle", "rm"), ("ns", "rm")}, "board": ("hle", "유력"), "pos": "코치"}}),
    ("선수가 다른 팀 코치로 확정(라이프 실제)", "리그피디아: DNS 서폿으로 나가 HLE 코치로 합류 → FA 직책은 코치, HLE 서폿 칸엔 안 들어감",
     [("Life", "Life", "", "dns", "Coach", "move", "hle", "", "", "2026-11-16", "선수 → 코치")], [],
     [],
     {"Life": {"fa": "확정", "card": None, "sum": {("hle", "in"), ("dns", "out")}, "board": ("hle", "확정"), "pos": "코치"}}),
    ("LCK 밖으로 확정(스카웃)", "해외 팀 이적 확정: 카드 없음, 팀별 이탈, 이동 보드 'Team Liquid'",
     [F("Scout", "ns", "Mid", "move", "", "Team Liquid")], [], [],
     {"Scout": {"fa": "확정", "card": None, "sum": {("ns", "out")}, "board": ("", "확정")}}),
    ("LCK 밖에서 온 영입(로머)", "FA 목록에 없이 로스터 '영입' → 팀별 영입, 카드는 그 팀",
     [], [R("bro", "Mid", "Roamer", 1)], [],
     {"Roamer": {"fa": None, "card": ("bro", "on"), "sum": {("bro", "in")}}}),
    ("유력 → 무산(제카)", "더 새 기사가 무산이면 유력을 거둠",
     [F("Zeka", "hle", "Mid")], [],
     [("'제카', 디플러스 기아행 유력", 40), ("디플러스 기아, '제카' 영입 무산", 2)],
     {"Zeka": {"fa": "미정", "card": None, "sum": {("hle", "open")}, "board": None}}),
    ("계약 중 선수 오피셜 이적(시우)", "로스터는 DK지만 오피셜 GEN 영입 → GEN 카드 확정, DK엔 없음, 팀별 양쪽",
     [], [R("dk", "Top", "Siwoo")],
     [("[오피셜] 젠지, '시우' 영입", 3)],
     {"Siwoo": {"fa": "확정", "card": ("geng", "news"), "sum": {("geng", "in"), ("dk", "out")}, "board": ("geng", "확정")}}),
    ("FA 미정인데 원래 팀 로스터에 남음 + 다른 팀 유력(킹겐)", "계약 기간이 아직 남아 원래 팀 로스터에 있어도 유력이면 가는 팀에만",
     [F("Kingen", "ns", "Top")], [R("ns", "Top", "Kingen", 0, "2026-11-30")],
     [("'킹겐', T1행 유력", 9)],
     {"Kingen": {"fa": "유력", "card": ("t1", "rm"), "sum": {("t1", "rm"), ("ns", "rm")}, "board": ("t1", "유력")}}),
]


# 시간 흐름: 같은 사람의 데이터를 단계마다 바꿔 넣고(기사 추가·리그피디아 반영), 단계마다 모든 화면이 정답대로 바뀌는지
# 단계: (설명, FA 목록, 로스터, 기사, 정답) — 기사는 그 시점까지 나온 것 전부
_K1 = ("'기인', 한화생명행 유력", 50)
_K2 = ("한화생명, '기인' 영입 무산", 30)
_K3 = ("[오피셜] T1, '기인' 영입", 3)
_L1 = ("[단독] DRX, '루시드' 영입 임박", 40)
_L2 = ("[오피셜] DRX, '루시드' 영입", 2)
TIMELINES = [
    ("기인: 미정 → 유력 → 무산 → 오피셜 → 리그피디아 반영", [
        ("FA 미정, 기사 없음", [F("Kiin", "geng", "Top")], [], [],
         {"Kiin": {"fa": "미정", "card": None, "sum": {("geng", "open")}, "board": None}}),
        ("HLE행 유력 기사", [F("Kiin", "geng", "Top")], [], [_K1],
         {"Kiin": {"fa": "유력", "card": ("hle", "rm"), "sum": {("hle", "rm"), ("geng", "rm")}, "board": ("hle", "유력")}}),
        ("HLE 영입 무산 기사", [F("Kiin", "geng", "Top")], [], [_K1, _K2],
         {"Kiin": {"fa": "미정", "card": None, "sum": {("geng", "open")}, "board": None}}),
        ("T1 오피셜(리그피디아 전)", [F("Kiin", "geng", "Top")], [], [_K1, _K2, _K3],
         {"Kiin": {"fa": "확정", "card": ("t1", "news"), "sum": {("t1", "in"), ("geng", "out")}, "board": ("t1", "확정")}}),
        ("리그피디아 반영(FA 목록 확정 + T1 로스터)", [F("Kiin", "geng", "Top", "move", "t1")], [R("t1", "Top", "Kiin", 1)], [_K1, _K2, _K3],
         {"Kiin": {"fa": "확정", "card": ("t1", "on"), "sum": {("t1", "in"), ("geng", "out")}, "board": ("t1", "확정")}}),
    ]),
    ("루시드(계약 중): 그대로 → 유력 → 오피셜 → 리그피디아 반영", [
        ("DK 계약 중, 기사 없음", [], [R("dk", "Jungle", "Kanavi", 1), R("dk", "Jungle", "Lucid")], [],
         {"Lucid": {"fa": None, "card": ("dk", "on"), "board": None}}),
        ("DRX 영입 임박 기사", [], [R("dk", "Jungle", "Kanavi", 1), R("dk", "Jungle", "Lucid")], [_L1],
         {"Lucid": {"fa": "유력", "card": ("drx", "rm"), "sum": {("drx", "rm"), ("dk", "rm")}, "board": ("drx", "유력")}}),
        ("DRX 오피셜(리그피디아 전)", [], [R("dk", "Jungle", "Kanavi", 1), R("dk", "Jungle", "Lucid")], [_L1, _L2],
         {"Lucid": {"fa": "확정", "card": ("drx", "news"), "sum": {("drx", "in"), ("dk", "out")}, "board": ("drx", "확정")}}),
        # 실제 리그피디아는 계약 중 선수 트레이드도 '나감(DK)·들어옴(DRX)' 기록이 남아 FA 목록에 이적 확정으로 잡힘(fa.classify_fa)
        ("리그피디아 반영(이적 기록 + DRX 로스터)", [F("Lucid", "dk", "Jungle", "move", "drx")],
         [R("dk", "Jungle", "Kanavi", 1), R("drx", "Jungle", "Lucid", 1)], [_L1, _L2],
         {"Lucid": {"fa": "확정", "card": ("drx", "on"), "sum": {("drx", "in"), ("dk", "out")}, "board": ("drx", "확정")}}),
    ]),
]


def reset_caches():
    state.reset()
    place._C.update(snap=None, val=None)
    with rumor._LOCK:
        rumor._CACHE.clear()
    filters._NAMES["at"] = 0.0
    filters._LEARN["at"] = 0.0
    cluster._PEOPLE["at"] = 0.0


def load(fa, roster, news, now=None, wipe_news=True):
    """FA 목록 · 로스터 · 기사를 DB에 넣음(실제 수집처럼 로스터는 fill_from_fa로 채움). wipe_news=False면 원래 기사는 둠."""
    now = now or datetime.now(timezone.utc)
    roster = [r[1:] for r in fill_from_fa([("lck",) + tuple(r) for r in roster], list(fa), set(KEYS))]
    with db() as c:
        for t in ("fa", "roster", "farm_items") + (("items",) if wipe_news else ()):
            try:
                c.execute(f"DELETE FROM {t}")
            except Exception:  # noqa: BLE001  (표가 아직 없음)
                pass
        c.executemany("INSERT INTO fa(page,nick,real,team_from,role,status,team_to,team_to_name,until,date,memo) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?)", fa)
        c.executemany("INSERT OR REPLACE INTO roster(league,team,role,page,nick,real,until,joined) VALUES('lck',?,?,?,?,?,?,?)", roster)
        for i, (t, hrs) in enumerate(news):
            iso = (now - timedelta(hours=hrs)).isoformat()
            c.execute("INSERT INTO items(id,team,source,title,url,outlet,published,first_seen,league) VALUES(?,?,?,?,?,?,?,?,'lck')",
                      (f"sc{i}", "", "news", t, f"https://example.com/sc{i}", "인벤", iso, iso))
    reset_caches()


def world(names=None):
    """상황 여러 개를 한 세상으로(선수가 겹치지 않게 만들어 둠) → (fa, roster, news, 정답)."""
    fa, roster, news, want = [], [], [], {}
    for name, _, f, r, n, w in SCENARIOS:
        if names and name not in names:
            continue
        fa += f
        roster += r
        news += n
        want.update(w)
    return fa, roster, news, want


def apply(name="all"):
    """dev_server.py에서 씀: 상황(또는 전부)을 지금 DB에 넣음."""
    fa, roster, news, _ = world(None if name == "all" else {name})
    load(fa, roster, news, wipe_news=False)


def screens():
    """화면마다 사람이 어떻게 보이는지 뽑기."""
    from tracker.web import views
    got = defaultdict(lambda: {"fa": None, "cards": [], "sum": set(), "board": [], "pos": set()})
    fa_html = views.render_fa("lck")
    for m in re.finditer(r'<li class="fa-row" data-page="([^"]+)"[^>]*data-pos="([^"]*)" data-label="([^"]*)" data-dest="([^"]*)"', fa_html):
        got[m.group(1)]["fa"] = (m.group(3), m.group(4))
        got[m.group(1)]["pos"].add(("이적 시장", m.group(2)))
    btn = {k: int(v) for k, v in re.findall(r'>(전체|확정|잔류|유력|미정) <b>(\d+)</b></button>', fa_html)}
    ro_html = views.render_roster("lck")
    for art in re.finditer(r'<article class="rc[^"]*"[^>]*data-team="(\w+)".*?</article>', ro_html, re.S):
        k = art.group(1)
        for li in re.finditer(r"<li([^>]*)>(.*?)</li>", art.group(0), re.S):
            body, first = li.group(2), True
            for sp in re.finditer(r'<span class="pn(?: sub)?"[^>]*data-page="([^"]+)"[^>]*data-pos="([^"]*)"[^>]*>[^<]*</span>((?:(?!<span class="pn).)*)', body, re.S):
                tail = sp.group(3)
                before = body[max(0, sp.start() - 30):sp.start()]
                # 칸 맨 끝의 큰 표(유력·영입·잔류)는 첫 사람 것(작은 표는 이름 바로 뒤)
                last = re.search(r'<i class="in( stay| rm)?" title="([^"]*)">[^<]*</i>$', body.strip()) if first else None
                if 'class="in s rm' in tail.split('<span class="subl')[0] or "rml" in before or (last and last.group(1) == " rm"):
                    kind = "rm"
                elif re.search(r'class="in s(?: stay)?" title="오피셜', tail.split('<span class="subl')[0]) or (last and last.group(2).startswith("오피셜")):
                    kind = "news"
                else:
                    kind = "on"
                first = False
                got[sp.group(1)]["cards"].append((k, kind))
                got[sp.group(1)]["pos"].add(("로스터", sp.group(2)))
    sm_html = views.render_summary("lck")
    for card in re.finditer(r'<article class="scard" id="m-(\w+)".*?</article>', sm_html, re.S):
        for line in re.finditer(r'<div class="sl (\w+)"><em>.*?</em><div>(.*?)</div></div>', card.group(0), re.S):
            for nick in re.findall(r'<span class="pc [^"]*"[^>]*>([^<]+)<small>', line.group(2)):
                got[nick]["sum"].add((card.group(1), line.group(1)))
    for li in re.finditer(r'<li(?: class=rm)?(?: data-label="([^"]*)" data-dest="([^"]*)")?>(.*?)</li>', views.moves_board()):
        m = re.search(r'data-page="([^"]+)"[^>]*data-pos="([^"]*)"', li.group(3))
        if m and li.group(1) is not None:
            got[m.group(1)]["board"].append((li.group(2), li.group(1)))
            got[m.group(1)]["pos"].add(("이동 보드", m.group(2)))
    st = {k: int(v) for v, k in re.findall(r'<span><b>(\d+)</b>(영입|잔류|유력|미정)</span>', sm_html)}
    strip = {k: int(v) for v, k in re.findall(r'<em>(\d+)</em>(확정|잔류|유력|미정)</a>', views.stove_strip("lck"))}
    rail = {k: int(v) for v, k in re.findall(r'<b>(\d+)</b>(확정|잔류|유력|미정)</a>', views.rail("lck", "all"))}
    return got, {"이적 시장": btn, "팀별": st, "소식 숫자 줄": strip, "오른쪽 요약": rail}


def check(want, label=""):
    got, nums = screens()
    bad = []
    say = lambda nick, msg: bad.append(f"{label}{nick}: {msg}")   # noqa: E731
    for nick, w in want.items():
        g = got[nick]
        fa = g["fa"][0] if g["fa"] else None
        if fa != w.get("fa"):
            say(nick, f"이적 시장 '{fa}' (정답 '{w.get('fa')}')")
        card = g["cards"]
        exp = [w["card"]] if w.get("card") else []
        if card != exp:
            say(nick, f"로스터 카드 {card} (정답 {exp} — 한 사람은 한 카드에만)")
        if "sum" in w and g["sum"] != w["sum"]:
            say(nick, f"팀별 {sorted(g['sum'])} (정답 {sorted(w['sum'])})")
        if "board" in w:
            exp_b = [w["board"]] if w["board"] else []
            if g["board"] != exp_b:
                say(nick, f"이동 보드 {g['board']} (정답 {exp_b})")
        # 같은 사람은 모든 화면 같은 행선지: 이적 시장 행선지 = 로스터 카드(유력·확정) = 이동 보드
        if g["fa"] and g["fa"][0] in ("확정", "유력") and g["fa"][1]:
            for k, kind in card:
                if kind in ("rm", "news") and k != g["fa"][1]:
                    say(nick, f"이적 시장 행선지 {g['fa'][1]}인데 로스터 카드는 {k}")
            for d, _ in g["board"]:
                if d != g["fa"][1]:
                    say(nick, f"이적 시장 행선지 {g['fa'][1]}인데 이동 보드는 {d}")
        pos = {p for _, p in g["pos"]}
        if len(pos) > 1:
            say(nick, f"직책 글자가 화면마다 다름 {sorted(g['pos'])}")
        if w.get("pos") and pos and pos != {w["pos"]}:
            say(nick, f"직책 '{sorted(pos)}' (정답 '{w['pos']}')")
    # 한 사람은 로스터 카드 한 곳에만(정답에 없는 사람도)
    for nick, g in got.items():
        if len(g["cards"]) > 1:
            say(nick, f"로스터 카드 {len(g['cards'])}곳 {g['cards']}")
    # 숫자: 이적 시장 = 소식 숫자 줄 = 오른쪽 요약 (확정·잔류·유력·미정), 팀별 유력·미정도 같게
    base = {k: nums["이적 시장"].get(k, 0) for k in ("확정", "잔류", "유력", "미정")}
    if sum(base.values()) != nums["이적 시장"].get("전체", 0):
        bad.append(f"{label}이적 시장: 네 칸 합 {sum(base.values())} ≠ 전체 {nums['이적 시장'].get('전체')}")
    for where in ("소식 숫자 줄", "오른쪽 요약"):
        x = {k: nums[where].get(k, 0) for k in base}
        if nums[where] and x != base:
            bad.append(f"{label}숫자: 이적 시장 {base} ≠ {where} {x}")
    if (nums["팀별"].get("유력", 0), nums["팀별"].get("미정", 0)) != (base["유력"], base["미정"]):
        bad.append(f"{label}숫자: 이적 시장 유력·미정 {base['유력']}·{base['미정']} ≠ 팀별 {nums['팀별'].get('유력', 0)}·{nums['팀별'].get('미정', 0)}")
    return bad


def run_all(verbose=True) -> list:
    from unittest import mock
    from tracker.web import views
    fails = []
    with mock.patch.object(views, "in_season", return_value=True):      # 소식 숫자 줄은 스토브리그 때만 나옴
        for name, desc, fa, roster, news, want in SCENARIOS:
            load(fa, roster, news)
            bad = check(want, f"[{name}] ")
            fails += bad
            if verbose:
                print(f"{'통과' if not bad else '실패'}  {name} — {desc}")
                for b in bad:
                    print("      " + b)
        for name, steps in TIMELINES:
            tl_bad = []
            for i, (desc, fa, roster, news, want) in enumerate(steps, 1):
                load(fa, roster, news)
                tl_bad += check(want, f"[{name} · {i}단계 {desc}] ")
            fails += tl_bad
            if verbose:
                print(f"{'통과' if not tl_bad else '실패'}  {name} ({len(steps)}단계)")
                for b in tl_bad:
                    print("      " + b)
        fa, roster, news, want = world()
        load(fa, roster, news)
        bad = check(want, "[전부 한꺼번에] ")
        fails += bad
        if verbose:
            print(f"{'통과' if not bad else '실패'}  전부 한꺼번에(상황 {len(SCENARIOS)}개를 한 세상에)")
            for b in bad:
                print("      " + b)
    return fails


if __name__ == "__main__":
    from tracker.core import init_db
    from tracker import farm
    init_db()
    farm.init()
    fails = run_all()
    print(f"\n상황 {len(SCENARIOS)}개 + 시간 흐름 {len(TIMELINES)}개({sum(len(s) for _, s in TIMELINES)}단계) · 실패 {len(fails)}건")
    sys.exit(1 if fails else 0)
