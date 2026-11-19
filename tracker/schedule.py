"""일정·결과 수집: 리그피디아 Cargo(Tournaments·MatchSchedule·Standings·Teams)에서 리그별 경기 일정·결과·순위를 받아 둠.

- 대상 리그: config.LEAGUES 중 "wiki"(리그피디아 이름, 예: "LPL")가 있는 리그. 로스터·소식이 아직 없는 리그도 일정은 보여 줌
- 지금 시즌(11월부터는 다음 해) 대회가 리그피디아에 올라와 있으면 그 시즌, 아직 없으면 바로 앞 시즌을 보여 줌
  (스토브리그 동안에는 지난 시즌 마지막 결과가 보이고, 새 시즌 일정이 올라오면 저절로 바뀜)
- 리그마다 경기 앞뒤 몇 시간에는 5분마다, 그 밖에는 30분마다 새로 받음
- 받은 내용은 data/schedule_<리그>.json 에도 저장해서, 서버를 다시 켜도 곧바로 화면이 나옴"""
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from . import teamlogos
from .archive import current_season, team_key
from .cargo import _cq, cargo
from .config import DB_PATH, KST, LEAGUES, log

_DIR = os.path.dirname(DB_PATH) or "."
_LOCK = threading.Lock()
_RUN = threading.Lock()                  # 수집이 겹치지 않게
DATA = {}                                # 리그 -> 마지막으로 받은 내용(아래 refresh 참고)
LIVE_HOURS = 5                           # 시작하고 이 시간 안에 결과가 없으면 '진행 중'으로 봄
FAST_SEC, SLOW_SEC, RETRY_SEC = 300, 1800, 600
_NOT_LEAGUE = re.compile(r"Promotion|Qualifier|Regional Finals|Play-In|Showmatch|Tiebreak", re.I)   # 순위표로 안 쓰는 단계


def leagues():
    """일정을 받는 리그(설정 순서)."""
    return [k for k, v in LEAGUES.items() if v.get("wiki")]


def _path(league: str) -> str:
    return os.path.join(_DIR, f"schedule_{league}.json")


def _load():
    global DATA
    out = {}
    for lg in leagues():
        try:
            with open(_path(lg), encoding="utf-8") as f:
                out[lg] = json.load(f)
        except (OSError, ValueError):
            pass
    with _LOCK:
        DATA = out


def get(league: str = "lck") -> dict:
    with _LOCK:
        return DATA.get(league) or {}


def slug(name: str) -> str:
    """팀 이름 → 화면용 키(영문 소문자·숫자·-). 예: 'Bilibili Gaming' → 'bilibili-gaming'."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def team_id(league: str, name: str) -> str:
    """LCK는 기존 팀 키(로고·색·내 팀과 같음), 다른 리그는 이름에서 만든 키."""
    if not name or name == "TBD":
        return ""
    return (team_key(name) if league == "lck" else "") or slug(name)


def _tours(prefix: str, year: int):
    return cargo(None, tables="Tournaments", fields="OverviewPage,Name,DateStart,Date,IsPlayoffs",
                 where=f'OverviewPage LIKE "{prefix}/{year} Season/%" AND TournamentLevel="Primary"', order_by="DateStart")


def _dt(s: str):
    try:
        return datetime.strptime((s or "")[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _match(league: str, r: dict, tour: dict) -> dict:
    t1, t2 = r.get("Team1") or "TBD", r.get("Team2") or "TBD"
    return {"id": r.get("MatchId") or "", "page": tour["OverviewPage"], "tour": tour["Name"],
            "playoff": tour.get("IsPlayoffs") == "1", "tab": r.get("Tab") or "",
            "at": r.get("DT") or "", "bo": r.get("BestOf") or "",
            "t1": t1, "k1": team_id(league, t1), "t2": t2, "k2": team_id(league, t2),
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


def _team_rows(names, gap):
    """리그피디아 Teams 표에서 팀 약칭(BLG, G2 …)·로고 파일 이름. 못 받으면 빈 dict(화면은 긴 이름·글자 로고로).
    일정의 팀 이름은 팀 문서 이름(OverviewPage)이라 그것으로 찾고, 못 찾은 이름(이름이 바뀐 팀)은 TeamRedirects로 한 번 더."""
    def by_page(pages):
        got = {}
        pages = sorted(pages)
        for i in range(0, len(pages), 40):
            rows = cargo(gap, tables="Teams", fields="Name,OverviewPage,Short,Image",
                         where=f'OverviewPage IN ({",".join(_cq(n) for n in pages[i:i + 40])})')
            got.update({r["OverviewPage"]: r for r in rows})
        return got
    names = {n for n in names if n and n != "TBD"}
    try:
        out = by_page(names)
        missing = sorted(names - set(out))
        if missing:
            redir = {}
            for i in range(0, len(missing), 40):
                rows = cargo(gap, tables="TeamRedirects", fields="AllName,_pageName=P",
                             where=f'AllName IN ({",".join(_cq(n) for n in missing[i:i + 40])})')
                redir.update({r["AllName"]: r["P"] for r in rows if r.get("P")})
            found = by_page(set(redir.values()))
            out.update({n: found[p] for n, p in redir.items() if p in found})
    except Exception as e:  # noqa: BLE001
        log.warning("schedule team names failed: %s", e)
        return {}
    return out


def refresh(league: str = "lck", gap=None) -> bool:
    """대회 목록 → 그 시즌 모든 경기 → 지금(또는 마지막) 정규 대회 순위 → 팀 약칭. 실패하면 이전 내용을 그대로 둠."""
    global DATA
    prefix = LEAGUES[league]["wiki"]
    with _RUN:
        try:
            cs = current_season()
            tours = _tours(prefix, cs - 1) + _tours(prefix, cs)   # 지난 시즌 + 지금 시즌(새 시즌 초반에도 지난 결과가 보이게)
            by_page = {t["OverviewPage"]: t for t in tours}
            matches = []
            pages = list(by_page)
            for i in range(0, len(pages), 10):
                for off in range(0, 5000, 500):                    # 500개씩 끝까지
                    rows = cargo(gap, tables="MatchSchedule",
                                 fields="Team1,Team2,Winner,Team1Score,Team2Score,DateTime_UTC=DT,BestOf,Tab,MatchId,OverviewPage,FF,IsNullified",
                                 where=f'OverviewPage IN ({",".join(_cq(p) for p in pages[i:i + 10])})',
                                 order_by="DateTime_UTC", offset=off)
                    matches += [_match(league, r, by_page[r["OverviewPage"]]) for r in rows
                                if r.get("OverviewPage") in by_page and r.get("IsNullified") != "1" and r.get("DT")]
                    if len(rows) < 500:
                        break
            matches.sort(key=lambda m: m["at"])
            cur = f"{prefix}/{cs} Season/"
            season = cs if any(m["page"].startswith(cur) for m in matches) else cs - 1
            # 순위표: 이미 시작한 정규 대회(플레이오프·승강전·선발전 제외) 중 순위표가 있는 가장 최근 것
            today = datetime.now(KST).date().isoformat()
            regular = [t for t in tours if t.get("IsPlayoffs") != "1" and (t.get("DateStart") or "9") <= today
                       and not _NOT_LEAGUE.search(t["OverviewPage"])]
            stand = {}
            for t in reversed(regular[-3:]):
                rows = cargo(gap, tables="Standings", fields="Team,Place,WinSeries,LossSeries,WinGames,LossGames",
                             where=f'OverviewPage={_cq(t["OverviewPage"])}', order_by="Place")
                seen, table = set(), []
                for r in rows:
                    if r["Team"] in seen:
                        continue
                    seen.add(r["Team"])
                    table.append({"team": r["Team"], "key": team_id(league, r["Team"]), "place": r.get("Place") or "",
                                  "w": r.get("WinSeries") or "0", "l": r.get("LossSeries") or "0",
                                  "gw": r.get("WinGames") or "0", "gl": r.get("LossGames") or "0"})
                if table:
                    stand = {"name": t["Name"], "page": t["OverviewPage"], "groups": _groups(table, matches, t["OverviewPage"])}
                    break
            # 팀 목록(키 → 이름·약칭). LCK는 기존 팀 정보를 쓰므로 약칭을 따로 받지 않음
            names = {m[s] for m in matches for s in ("t1", "t2")}
            names |= {r["team"] for g in stand.get("groups") or [] for r in g["table"]}
            rows = {} if league == "lck" else _team_rows(names, gap)
            teams = {team_id(league, n): {"name": n, "short": (rows.get(n) or {}).get("Short") or n,
                                          "image": (rows.get(n) or {}).get("Image") or ""}
                     for n in names if team_id(league, n)}
            d = {"league": league, "season": season, "current": season == cs, "at": datetime.now(timezone.utc).isoformat(),
                 "tours": [{"page": t["OverviewPage"], "name": t["Name"], "start": t.get("DateStart") or "",
                            "end": t.get("Date") or "", "playoff": t.get("IsPlayoffs") == "1"} for t in tours],
                 "matches": matches, "standings": stand, "teams": teams}
        except Exception as e:  # noqa: BLE001
            log.warning("schedule %s refresh failed: %s", league, e)
            with _LOCK:
                DATA = {**DATA, league: {**DATA.get(league, {}), "error": str(e)[:200]}}
            return False
        with _LOCK:
            DATA = {**DATA, league: d}                 # 통째로 바꿔 끼움(읽는 쪽은 잠금 없이 써도 안전)
        try:
            with open(_path(league), "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
        except OSError as e:
            log.warning("schedule %s save failed: %s", league, e)
        log.info("schedule %s %s: %d matches, standings %d", league, season, len(matches),
                 sum(len(g["table"]) for g in stand.get("groups") or []))
    if league != "lck":                                # 해외 팀 로고(없는 것만 받음)
        try:
            teamlogos.ensure({k: t["image"] for k, t in teams.items() if t.get("image")})
        except Exception as e:  # noqa: BLE001
            log.warning("schedule %s logos failed: %s", league, e)
    return True


def busy(league: str) -> bool:
    """경기 시작 3시간 전 ~ 시작 후 LIVE_HOURS 시간 사이면 자주 새로 받음."""
    now = datetime.now(timezone.utc)
    for m in get(league).get("matches") or []:
        at = _dt(m["at"])
        if at and at - timedelta(hours=3) <= now <= at + timedelta(hours=LIVE_HOURS):
            return True
    return False


def start():
    """켜자마자 저장해 둔 내용을 읽고, 1분 뒤부터 리그마다 정해진 간격으로 새로 받음(LCK 먼저)."""
    _load()
    teamlogos.load()

    def loop():
        time.sleep(60)
        due = {lg: 0.0 for lg in leagues()}
        while True:
            for lg in leagues():
                if time.time() >= due[lg]:
                    ok = refresh(lg)
                    due[lg] = time.time() + (FAST_SEC if (ok and busy(lg)) else SLOW_SEC if ok else RETRY_SEC)
            time.sleep(30)
    threading.Thread(target=loop, daemon=True).start()
