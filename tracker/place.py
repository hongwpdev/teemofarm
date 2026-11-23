"""사람마다 '어디에 · 무슨 말로' 보일지 한 번에 정함. 모든 화면(이적 시장 · 로스터 카드 · 팀별 · 이동 보드 · 숫자)은 이것만 그림.

예전엔 화면마다 FA 표 · 로스터 · 기사(유력)를 따로 조합해서, 한 화면을 고치면 다른 화면이 어긋났음
('유력인데 미정', '루시드가 DK·DRX 두 카드에', '듀로가 GEN에 그대로'). 규칙은 여기 한 곳에만 둠:

1. 상태 말은 4개: 확정(move) · 잔류(stay) · 유력(rm, 기사 추측) · 미정(fa). FA 목록에 없는 계약 중 선수는 'on'(말 없음)
   - 리그피디아 FA 목록이 우선. 단 아직 미정인데 오피셜 기사가 있으면 그 기사대로 확정·잔류(news=True: 리그피디아 반영 전)
   - 리그피디아 로스터에 다른 LCK 팀으로 이미 올라온 사람은 그 팀 확정(state.py에서 FA 행을 고쳐 둠)
   - 계약 중 선수라도 다른 LCK 팀 이적 기사가 있으면 유력(오피셜이면 확정)
2. 로스터 카드는 한 사람당 한 팀 카드에만(card): 확정·유력이면 가는 팀, 아니면 지금 계약 팀.
   가는 팀이 LCK 밖이면 갈 카드가 없으니 지금 팀 카드에 두고 '➔ 밖' 표시(away)
3. 행선지(dest)는 하나: 확정 → 새 팀, 잔류 → 원래 팀, 유력 → 기사 팀, 미정 → 없음

    from tracker import place, state; place.of(state.get())  → {page: 사람}
"""
import threading

from .config import TEAMS
from .fa import FA_ROLES

SLOTS = ("Top", "Jungle", "Mid", "Bot", "Support", "Head Coach")
POS = {"Top": "탑", "Jungle": "정글", "Mid": "미드", "Bot": "원딜", "Support": "서폿",
       "Head Coach": "감독", "Coach": "코치", "Analyst": "분석"}
WORD = {"move": "확정", "stay": "잔류", "rm": "유력", "fa": "미정", "on": ""}
_LOCK = threading.Lock()
_C = {"snap": None, "val": None}


def lck() -> set:
    return {k for k in TEAMS if k != "lck" and TEAMS[k].get("wiki")}


def coach_news(art) -> bool:
    """선수 출신이 코치·감독으로 간다는 기사('라이프' 서폿 → 코치)."""
    return bool(art) and any(w in art["title"] for w in ("코치", "감독", "코칭"))


def rm_label(art) -> str:
    """기사 하나의 표시 말: 오피셜이면 확정·잔류(리그피디아 반영 전이라도), 기사 추측이면 잔류 쪽이어도 유력."""
    if art["official"]:
        return "잔류" if art["stay"] else "확정"
    return "유력"


def fa_effective(r, art) -> str:
    """FA 행의 확정 상태: 리그피디아 상태, 단 아직 '미정'인데 오피셜 기사가 있으면 그 기사대로(잔류·확정)."""
    if r["status"] == "fa" and art and art["official"]:
        return "stay" if art["stay"] else "move"
    return r["status"]


def _person(fa=None, ro=None, art=None, keys=frozenset()):
    base = fa or ro
    frm = fa["team_from"] if fa else ro["team"]
    p = {"page": base["page"], "nick": base["nick"], "real": base.get("real") or "", "role": base["role"],
         "frm": frm, "fa": fa, "ro": ro, "rm": None, "news": False, "in_fa": bool(fa),
         "status": "on", "dest": "", "dest_name": "", "card": "", "kind": "", "slot": "", "away": None}
    # 1) 상태 말
    if fa and fa["status"] in ("move", "stay"):
        p["status"] = fa["status"]
        p["dest"] = (fa["team_to"] or "") if fa["status"] == "move" else frm
        p["dest_name"] = fa["team_to_name"] or "" if fa["status"] == "move" else ""
    elif art:
        p["rm"] = art
        if art["official"]:
            p["news"] = True
            p["status"] = "stay" if art["stay"] else "move"
        else:
            p["status"] = "rm"
        p["dest"] = frm if art["stay"] else art["team"]
    elif fa:
        p["status"] = "fa"
    p["label"] = WORD[p["status"]]
    # 2) 로스터 카드: 한 사람당 한 카드
    to_other = art and not art["stay"] and art["team"] in keys and art["team"] != (ro["team"] if ro else frm)
    if art and (to_other or not ro):
        if art["team"] in keys:                       # 기사로 가는 팀(또는 잔류 기사로 원래 팀) 카드에
            p["card"] = art["team"]
            p["kind"] = "news" if art["official"] else "rm"
            p["slot"] = base["role"] if base["role"] in SLOTS and not coach_news(art) else "Head Coach"
    elif ro:
        p["card"], p["kind"], p["slot"] = ro["team"], "on", ro["role"]
        if art and not art["stay"] and art["team"] not in keys:
            p["away"] = art                           # LCK 밖으로: 갈 카드가 없으니 지금 팀 카드에 '➔' 표시
    p["shown"] = shown_pos(p["role"], art)
    return p


def shown_pos(role: str, art=None) -> str:
    """직책 글자(모든 화면 공통): 리그피디아 직책, 선수가 코치로 간다는 기사면 기사 기준."""
    if coach_news(art) and role in FA_ROLES:
        return "감독" if "감독" in art["title"] and "코치" not in art["title"] else "코치"
    return POS.get(role, role)


def build(snap) -> dict:
    """스냅숏(state.get) → {page: 사람}. 같은 사람이 FA 목록과 로스터에 다 있으면 한 사람으로 합침."""
    keys = lck()
    fa_rows, roster, rumors, leaving = snap["fa"], snap["roster"], snap["rumors"], snap["leaving"]
    ro_of = {}
    for r in roster:
        ro_of.setdefault(r["page"], r)
    out = {}
    for r in fa_rows:
        ro = ro_of.get(r["page"])                     # (미정인데 다른 팀 로스터에 있으면 state.py가 이미 확정으로 바꿔 둠)
        art = None
        if r["status"] == "fa":                       # 기사: FA 기사 읽기가 먼저, 없으면 계약 중 선수 규칙으로 읽은 것
            art = rumors.get(r["page"]) or leaving.get(r["page"])
        out[r["page"]] = _person(dict(r), dict(ro) if ro else None, art, keys)
    for r in roster:
        if r["page"] in out:
            continue
        out[r["page"]] = _person(None, dict(r), leaving.get(r["page"]), keys)
    return out


def of(snap) -> dict:
    """같은 스냅숏이면 다시 계산하지 않음(스냅숏은 원본이 바뀔 때만 새로 만들어짐)."""
    with _LOCK:
        if _C["snap"] is snap:
            return _C["val"]
    val = build(snap)
    with _LOCK:
        _C.update(snap=snap, val=val)
    return val


def counts(people) -> dict:
    """이적 시장 숫자(FA 목록 사람만): {"move","stay","rm","fa"} — 네 칸은 겹치지 않음."""
    out = {}
    for p in people.values():
        if p["in_fa"]:
            out[p["status"]] = out.get(p["status"], 0) + 1
    return out


def on_card(people, k) -> dict:
    """로스터 카드 한 팀: {자리: {"on": [...], "news": [...], "rm": [...]}} (on은 로스터 순서 그대로)."""
    out = {}
    for p in people.values():
        if p["card"] == k:
            out.setdefault(p["slot"], {"on": [], "news": [], "rm": []})[p["kind"]].append(p)
    return out
