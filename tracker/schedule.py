"""일정·결과 수집: 리그피디아 Cargo(Tournaments·MatchSchedule·Standings)에서 LCK 경기 일정·결과·순위를 받아 둠.

- 지금 시즌(11월부터는 다음 해) 대회가 리그피디아에 올라와 있으면 그 시즌, 아직 없으면 바로 앞 시즌을 보여 줌
  (스토브리그 동안에는 지난 시즌 마지막 결과가 보이고, 새 시즌 일정이 올라오면 저절로 바뀜)
- 경기가 있는 날(앞뒤 몇 시간)에는 5분마다, 그 밖에는 30분마다 새로 받음
- 받은 내용은 data/schedule_lck.json 에도 저장해서, 서버를 다시 켜도 곧바로 화면이 나옴"""
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from .archive import current_season, team_key
from .cargo import _cq, cargo
from .config import DB_PATH, KST, log

_PATH = os.path.join(os.path.dirname(DB_PATH) or ".", "schedule_lck.json")
_LOCK = threading.Lock()
_RUN = threading.Lock()                  # 수집이 겹치지 않게
DATA = {}                                # 마지막으로 받은 내용(아래 refresh 참고)
LIVE_HOURS = 5                           # 시작하고 이 시간 안에 결과가 없으면 '진행 중'으로 봄
FAST_SEC, SLOW_SEC = 300, 1800


def _load():
    global DATA
    try:
        with open(_PATH, encoding="utf-8") as f:
            DATA = json.load(f)
    except (OSError, ValueError):
        DATA = {}


def get() -> dict:
    with _LOCK:
        return DATA


def _tours(year: int):
    return cargo(None, tables="Tournaments", fields="OverviewPage,Name,DateStart,Date,IsPlayoffs",
                 where=f'OverviewPage LIKE "LCK/{year} Season/%" AND TournamentLevel="Primary"', order_by="DateStart")


def _dt(s: str):
    try:
        return datetime.strptime((s or "")[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _match(r: dict, tour: dict) -> dict:
    t1, t2 = r.get("Team1") or "TBD", r.get("Team2") or "TBD"
    return {"id": r.get("MatchId") or "", "page": tour["OverviewPage"], "tour": tour["Name"],
            "playoff": tour.get("IsPlayoffs") == "1", "tab": r.get("Tab") or "",
            "at": r.get("DT") or "", "bo": r.get("BestOf") or "",
            "t1": t1, "k1": team_key(t1), "t2": t2, "k2": team_key(t2),
            "s1": r.get("Team1Score") or "", "s2": r.get("Team2Score") or "",
            "win": r.get("Winner") or "", "ff": r.get("FF") or ""}


def _groups(table, matches, page):
    """순위표를 그룹별로 나눔. 리그피디아 순위표엔 그룹 칸이 없어서(같은 순위가 둘씩 나옴),
    그 대회에서 서로 맞붙은 팀끼리 한 그룹으로 묶음. 그룹이 하나면 [('', 표)]."""
    places = [r["place"] for r in table]
    if len(set(places)) == len(places):
        return [{"name": "", "table": table}]
    link = {r["team"]: {r["team"]} for r in table}
    for m in matches:
        if m["page"] == page and m["t1"] in link and m["t2"] in link:
            a, b = link[m["t1"]], link[m["t2"]]
            if a is not b:
                a |= b
                for x in b:
                    link[x] = a
    comps = []
    for r in table:
        if not any(link[r["team"]] is c for c in comps):
            comps.append(link[r["team"]])
    groups = [[r for r in table if r["team"] in c] for c in comps]
    groups.sort(key=lambda g: -sum(int(r["w"] or 0) for r in g) / max(len(g), 1))
    names = ["상위 그룹", "하위 그룹"] if len(groups) == 2 else [f"{i + 1}조" for i in range(len(groups))]
    return [{"name": n, "table": g} for n, g in zip(names, groups)]


def refresh(gap=None) -> bool:
    """대회 목록 → 그 시즌 모든 경기 → 지금(또는 마지막) 정규 대회 순위. 실패하면 이전 내용을 그대로 둠."""
    global DATA
    with _RUN:
        try:
            cs = current_season()
            season, tours = cs, _tours(cs)
            if not tours:                              # 새 시즌 일정이 아직 없으면 지난 시즌
                season, tours = cs - 1, _tours(cs - 1)
            by_page = {t["OverviewPage"]: t for t in tours}
            matches = []
            if by_page:
                rows = cargo(gap, tables="MatchSchedule",
                             fields="Team1,Team2,Winner,Team1Score,Team2Score,DateTime_UTC=DT,BestOf,Tab,MatchId,OverviewPage,FF,IsNullified",
                             where=f'OverviewPage IN ({",".join(_cq(p) for p in by_page)})', order_by="DateTime_UTC")
                matches = [_match(r, by_page[r["OverviewPage"]]) for r in rows
                           if r.get("OverviewPage") in by_page and r.get("IsNullified") != "1" and r.get("DT")]
            # 순위표: 이미 시작한 정규(플레이오프 아닌) 대회 중 가장 최근 것
            today = datetime.now(KST).date().isoformat()
            regular = [t for t in tours if t.get("IsPlayoffs") != "1" and (t.get("DateStart") or "9") <= today]
            stand = {}
            if regular:
                t = regular[-1]
                rows = cargo(gap, tables="Standings", fields="Team,Place,WinSeries,LossSeries,WinGames,LossGames",
                             where=f'OverviewPage={_cq(t["OverviewPage"])}', order_by="Place")
                seen, table = set(), []
                for r in rows:
                    if r["Team"] in seen:
                        continue
                    seen.add(r["Team"])
                    table.append({"team": r["Team"], "key": team_key(r["Team"]), "place": r.get("Place") or "",
                                  "w": r.get("WinSeries") or "0", "l": r.get("LossSeries") or "0",
                                  "gw": r.get("WinGames") or "0", "gl": r.get("LossGames") or "0"})
                stand = {"name": t["Name"], "page": t["OverviewPage"], "groups": _groups(table, matches, t["OverviewPage"])}
            d = {"season": season, "current": season == cs, "at": datetime.now(timezone.utc).isoformat(),
                 "tours": [{"page": t["OverviewPage"], "name": t["Name"], "start": t.get("DateStart") or "",
                            "end": t.get("Date") or "", "playoff": t.get("IsPlayoffs") == "1"} for t in tours],
                 "matches": matches, "standings": stand}
        except Exception as e:  # noqa: BLE001
            log.warning("schedule refresh failed: %s", e)
            with _LOCK:
                DATA = {**DATA, "error": str(e)[:200]}
            return False
        with _LOCK:
            DATA = d                                   # 통째로 바꿔 끼움(읽는 쪽은 잠금 없이 써도 안전)
        try:
            with open(_PATH, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
        except OSError as e:
            log.warning("schedule save failed: %s", e)
        log.info("schedule %s: %d matches, standings %d", season, len(matches), sum(len(g["table"]) for g in stand.get("groups") or []))
        return True


def _busy_now() -> bool:
    """경기 시작 3시간 전 ~ 시작 후 LIVE_HOURS 시간 사이면 자주 새로 받음."""
    now = datetime.now(timezone.utc)
    for m in get().get("matches") or []:
        at = _dt(m["at"])
        if at and at - timedelta(hours=3) <= now <= at + timedelta(hours=LIVE_HOURS):
            return True
    return False


def start():
    """켜자마자 저장해 둔 내용을 읽고, 1분 뒤부터 주기적으로 새로 받음."""
    _load()

    def loop():
        time.sleep(60)
        while True:
            ok = refresh()
            time.sleep(FAST_SEC if (ok and _busy_now()) else SLOW_SEC if ok else 600)
    threading.Thread(target=loop, daemon=True).start()
