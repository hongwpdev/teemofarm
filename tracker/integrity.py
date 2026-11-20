"""데이터 정합성 점검: 같은 사람이 화면마다 다르게 보이지 않는지(코치/감독, 미정/확정, 두 팀에 동시에 등).
화면은 모두 fa·roster 표와 '유력'(rumor.py)에서 만들어지므로, 그 원본끼리 서로 맞는지 봄.

    from tracker import integrity; integrity.check()   → 문제 목록(빈 목록이면 정상)
/api/integrity 로도 볼 수 있고(tools/crawl.js가 확인), FA를 새로 받을 때마다 로그에 남김."""
from collections import defaultdict

from .core import db
from .rumor import movers, rumors

POS = {"Top": "탑", "Jungle": "정글", "Mid": "미드", "Bot": "원딜", "Support": "서폿", "Head Coach": "감독", "Coach": "코치"}


def _rows(sql):
    with db() as c:
        return [dict(r) for r in c.execute(sql).fetchall()]


def check() -> list:
    fa = _rows("SELECT * FROM fa WHERE league='lck'")
    roster = _rows("SELECT * FROM roster WHERE league='lck'")
    bad = []

    # 1) 한 사람은 FA 목록에 한 줄(원소속 기준)
    seen = defaultdict(list)
    for r in fa:
        seen[(r["nick"].lower(), r["team_from"])].append(r)
    for (nick, frm), rs in seen.items():
        if len(rs) > 1:
            bad.append(f"FA 목록에 {rs[0]['nick']}({frm})이 {len(rs)}줄: " +
                       ", ".join(f"{POS.get(r['role'], r['role'])} {r['status']}" for r in rs))

    # 2) 한 사람은 로스터에서 한 팀·한 자리
    on = defaultdict(list)
    for r in roster:
        on[r["nick"].lower()].append(r)
    for nick, rs in on.items():
        if len(rs) > 1:
            bad.append(f"로스터에 {rs[0]['nick']}이 {len(rs)}곳: " + ", ".join(f"{r['team']} {POS.get(r['role'], r['role'])}" for r in rs))

    # 3) FA 상태와 로스터가 같은 말을 하는지
    ro = {r["nick"].lower(): r for r in roster}
    for r in fa:
        x = ro.get(r["nick"].lower())
        if not x:
            continue
        who = f"{r['nick']}({r['team_from']})"
        if r["status"] == "fa" and x["team"] == r["team_from"] and (x["until"] or "") <= (r["date"] or ""):
            bad.append(f"{who}: FA 목록은 미정인데 로스터엔 {x['team']} 소속")
        elif r["status"] == "move" and r["team_to"] and x["team"] != r["team_to"]:
            bad.append(f"{who}: FA 목록은 {r['team_to']} 이적 확정인데 로스터엔 {x['team']}")
        elif r["status"] == "stay" and x["team"] != r["team_from"]:
            bad.append(f"{who}: FA 목록은 잔류인데 로스터엔 {x['team']}")
        # 4) 같은 사람의 자리(감독/코치/포지션)
        if r["status"] != "fa" and POS.get(r["role"]) != POS.get(x["role"]) and not (
                r["role"] == "Coach" and x["role"] == "Head Coach" and r["memo"] in ("감독 승격", "정식 감독")):
            bad.append(f"{who}: FA 목록은 {POS.get(r['role'], r['role'])}, 로스터는 {POS.get(x['role'], x['role'])}")

    # 5) '유력'은 아직 미정인 사람에게만, 그리고 지금 팀이 행선지가 되면 안 됨
    rm = rumors(fa)
    for r in fa:
        x = rm.get(r["page"])
        if x and r["status"] != "fa":
            bad.append(f"{r['nick']}: 이미 {r['status']}인데 '유력' 표시")
    for page, x in movers(roster).items():
        r = next((y for y in roster if y["page"] == page), None)
        if r and x["team"] == r["team"]:
            bad.append(f"{r['nick']}: 지금 {r['team']} 선수인데 '{r['team']} 이적 유력'으로 읽음 ({x['title']})")
    return bad
