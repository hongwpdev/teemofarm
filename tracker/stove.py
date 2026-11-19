"""스토브리그 정리 화면용 계산: 팀별 이적 요약 · 계약 만료 예정 · 인기 로스터(로스터 짜기 공유 기록) · 소식통 적중률.
모두 이미 모아 둔 표(fa·roster·shares·items)에서 계산만 하고, 따로 수집하지 않음."""
import threading
import time
from collections import Counter, defaultdict

from .cluster import persons
from .core import db
from .rumor import _guess, _recent_news, MOVE_MARK

_PRED = {"at": 0.0, "val": []}
_PRED_LOCK = threading.Lock()

ROLES = ("Top", "Jungle", "Mid", "Bot", "Support")      # 로스터 짜기 공유 문자열의 자리 순서와 같음


def _rows(table, where="league='lck'"):
    with db() as c:
        return [dict(r) for r in c.execute(f"SELECT * FROM {table} WHERE {where}").fetchall()]


# ── 1. 팀별 이적 요약 ───────────────────────────────────────────────────
def team_summary(team_keys) -> dict:
    """{팀: {"in": [...], "out": [...], "stay": [...], "open": [...], "updated": "YYYY-MM-DD"}}
    in: 이적 확정으로 들어온 사람 + LCK 밖에서 온 영입 · out: 다른 팀으로 간 사람 · stay: 재계약 · open: 계약 끝나고 미정."""
    fa = _rows("fa")
    roster = _rows("roster")
    out = {k: {"in": [], "out": [], "stay": [], "open": [], "updated": ""} for k in team_keys}

    def bump(k, d):
        if k in out and d and d > out[k]["updated"]:
            out[k]["updated"] = d
    moved_in = set()
    for r in fa:
        k, d = r["team_from"], (r["date"] or "")[:10]
        p = {"page": r["page"], "nick": r["nick"], "role": r["role"], "date": d}
        if r["status"] == "move":
            if r["team_to"] in out:
                out[r["team_to"]]["in"].append({**p, "from": k})
                moved_in.add(r["page"])
                bump(r["team_to"], d)
            if k in out:
                out[k]["out"].append({**p, "to": r["team_to"], "to_name": r["team_to_name"]})
                bump(k, d)
        elif r["status"] == "stay" and k in out:
            out[k]["stay"].append(p)
            bump(k, d)
        elif r["status"] == "fa" and k in out:
            out[k]["open"].append(p)
    for r in roster:                                     # LCK 밖(해외·2군 등)에서 온 영입
        if r["joined"] and r["team"] in out and r["page"] not in moved_in:
            out[r["team"]]["in"].append({"page": r["page"], "nick": r["nick"], "role": r["role"], "date": "", "from": ""})
    return out


# ── 2. 계약 만료 예정 ───────────────────────────────────────────────────
def contracts() -> list:
    """지금 로스터의 계약 끝나는 날 기준 정렬: [{"page","nick","real","team","role","until"}] (모르는 사람은 맨 뒤)."""
    rows = _rows("roster")
    rows.sort(key=lambda r: (r["until"] or "9999", r["team"], r["role"]))
    return [{k: r[k] for k in ("page", "nick", "real", "team", "role", "until")} for r in rows]


# ── 3. 인기 로스터(공유된 로스터 짜기) ───────────────────────────────────
def popular(team_keys, min_shares: int = 3) -> dict:
    """{"n": 공유 수, "teams": {팀: {자리: [(page, 횟수), ...]}}}. 같은 사람이 여러 번 공유한 것도 그대로 셈."""
    with db() as c:
        try:
            shares = [r["r"] for r in c.execute("SELECT r FROM shares").fetchall()]
        except Exception:  # noqa: BLE001  공유 표가 아직 없음
            shares = []
    if len(shares) < min_shares:
        return {"n": len(shares), "teams": {}}
    cnt = {k: {role: Counter() for role in ROLES} for k in team_keys}
    for r in shares:
        for i, part in enumerate(r.split("|")[:len(team_keys)]):
            for j, page in enumerate(part.split(",")[:len(ROLES)]):
                if page:
                    cnt[team_keys[i]][ROLES[j]][page] += 1
    return {"n": len(shares), "teams": {k: {role: c_.most_common(3) for role, c_ in v.items()} for k, v in cnt.items()}}


# ── 5. 소식통 적중률 ────────────────────────────────────────────────────
def predictions() -> list:
    """기사 하나 = 예측 하나(그 기사의 매체·선수·행선지). 결과: hit(맞음)·miss(틀림)·wait(아직).
    FA 선수: 이적 확정·잔류 결과와 비교. 계약이 남은 선수: 지금 로스터 팀과 비교(옮기기 전이면 아직). 2분 캐시."""
    with _PRED_LOCK:
        if time.time() - _PRED["at"] < 120:
            return _PRED["val"]
    val = _predictions()
    with _PRED_LOCK:
        _PRED.update(at=time.time(), val=val)
    return val


def _predictions() -> list:
    news = [n for n in _recent_news() if n["outlet"]]
    fa = _rows("fa")
    roster = _rows("roster")
    now_team = {r["page"]: r["team"] for r in roster}
    fa_by = {r["page"]: r for r in fa}
    people = ([{"page": r["page"], "nick": r["nick"], "team_from": r["team_from"]} for r in fa] +
              [{"page": r["page"], "nick": r["nick"], "team_from": r["team"]} for r in roster if r["page"] not in fa_by])
    by_nick = defaultdict(list)
    for who in people:
        by_nick[(who["nick"] or "").lower()].append(who)
    out, seen = [], set()
    for n in news:
        one = [n]
        named = persons(n["title"])                    # 제목에 나온 사람만 확인(빠르게)
        for who in (w for nk in named for w in by_nick.get(nk, [])):
            fa_row = fa_by.get(who["page"])
            hit = _guess([who], one, marks=MOVE_MARK, allow_stay=bool(fa_row)).get(who["page"])
            if not hit or hit["official"]:            # 공식 발표 기사는 예측이 아니라서 뺌
                continue
            key = (n["outlet"], who["page"], hit["team"], hit["stay"])
            if key in seen:
                continue
            seen.add(key)
            if fa_row:
                st, to = fa_row["status"], fa_row["team_to"]
                if st == "fa":
                    res = "wait"
                elif hit["stay"]:
                    res = "hit" if st == "stay" else "miss"
                else:
                    res = "hit" if st == "move" and to == hit["team"] else "miss"
            else:
                res = "hit" if now_team.get(who["page"]) == hit["team"] else "wait"
            out.append({"outlet": outlet_name(n["outlet"]), "title": n["title"], "url": n["url"], "published": n["published"],
                        "page": who["page"], "nick": who["nick"], "from": who["team_from"], "team": hit["team"],
                        "stay": hit["stay"], "result": res})
    out.sort(key=lambda x: x["published"], reverse=True)
    return out


OUTLET_KO = {"xportsnews.com": "엑스포츠뉴스", "osen.co.kr": "OSEN", "inven.co.kr": "인벤", "fomos.kr": "포모스",
             "dailyesports.com": "데일리e스포츠", "sportsseoul.com": "스포츠서울"}


def outlet_name(o: str) -> str:
    """'www.xportsnews.com' 같은 주소 모양 매체 이름을 보기 좋게."""
    o = (o or "").strip()
    host = o[4:] if o.startswith("www.") else o
    return OUTLET_KO.get(host, host)


def accuracy(preds) -> list:
    """매체별 [{"outlet","hit","miss","wait","rate"}] — 결과가 난 예측이 많은 순."""
    by = defaultdict(lambda: {"hit": 0, "miss": 0, "wait": 0})
    for p in preds:
        by[p["outlet"]][p["result"]] += 1
    rows = [{"outlet": o, **v, "rate": (round(100 * v["hit"] / (v["hit"] + v["miss"])) if v["hit"] + v["miss"] else None)}
            for o, v in by.items()]
    rows.sort(key=lambda r: (-(r["hit"] + r["miss"]), -(r["rate"] or 0), -r["wait"], r["outlet"]))
    return rows
