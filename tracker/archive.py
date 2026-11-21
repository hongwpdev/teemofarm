"""지난 시즌 기록(아카이브): 리그피디아에서 한 번 모아 data/archive_lck_<연도>.json 으로 저장해 두고 그 파일만 읽음.
지난 시즌은 바뀌지 않으므로 다시 받지 않음(일부를 못 받았으면 30분 뒤 그 부분만 다시 시도).

담는 것
- stages : 그 해 정규 대회(컵·라운드)별 최종 순위표
- champion: 시즌 플레이오프 결승 결과
- roster : 그 해 마지막 정규 대회에 등록된 팀별 로스터(선수·코치)
- moves  : 그 시즌을 앞둔 스토브리그(전년 11월~그해 1월) 이동 기록"""
import json
import os
import re
import threading
import time
from datetime import date, datetime

from .cargo import _cq, cargo
from .config import DB_PATH, KST, TEAMS, log

def archive_years():
    """고를 수 있는 지난 시즌: 지금 시즌 바로 앞부터 2012년(OGN 챔피언스 첫 시즌)까지, 최근 것부터. 해가 바뀌면 알아서 늘어남."""
    cs = current_season()
    return tuple(range(cs - 1, FIRST_YEAR - 1, -1))


def recent_years():
    """로스터 짜기의 '지난 로스터 불러오기'처럼 최근 두 시즌만 쓰는 곳."""
    return archive_years()[:2]


FIRST_YEAR = 2012
# 2015년까지는 리그피디아 문서가 'Champions/…'(OGN 챔피언스), 2016년부터 'LCK/…'
def prefix(year: int) -> str:
    return "Champions" if year <= 2015 else "LCK"


# 시즌 기록에서 빼는 대회(승강전·선발전·예선). 순위표는 정규 대회만, 우승은 우승컵이 걸린 대회만
_SKIP = re.compile(r"Qualifier|Promotion|Regional Finals|Play-In|Road to MSI")


def titles(tours, year: int) -> list:
    """우승컵이 걸린 대회: 2014년까지는 스플릿 대회 자체(본선 안에 결승), 2015~2024 스프링·서머 플레이오프,
    2025년부터 LCK 컵 + 시즌 플레이오프."""
    out = []
    for t in tours:
        p = t["OverviewPage"]
        if _SKIP.search(p):
            continue
        if year <= 2014 or t.get("IsPlayoffs") == "1" or p.endswith("/Cup"):
            out.append(t)
    return out
_DIR = os.path.dirname(DB_PATH) or "."
_LOCK = threading.Lock()
_CACHE = {}                          # 연도 -> dict
_BUSY = set()
ROLE = {"top": "Top", "jungle": "Jungle", "mid": "Mid", "bot": "Bot", "adc": "Bot", "support": "Support",
        "coach": "Coach", "head coach": "Head Coach"}
# 예전 팀 이름 → 지금 팀 키(로고·색)
_TEAM_RX = [(re.compile(rx, re.I), k) for rx, k in (
    (r"hanwha", "hle"), (r"^t1\b|sk ?telecom", "t1"), (r"gen\.?g|samsung|\bksv\b", "geng"),
    (r"dplus|damwon|\bdwg\b|\bdk\b", "dk"), (r"\bkt\b", "kt"),
    (r"nongshim|\bns\b|team dynamics", "ns"), (r"fearx|liiv sandbox|sandbox", "bfx"),
    (r"\bdrx\b|dragonx|kingzone|longzhu|incredible miracle", "drx"),
    (r"freecs|soopers|kwangdong|afreeca|rebels anarchy", "dns"), (r"brion", "bro"))]


def current_season(today=None) -> int:
    """지금 시즌: 11월부터는 다음 해 시즌(스토브리그)."""
    today = today or datetime.now(KST).date()
    return today.year + 1 if today.month >= 11 else today.year


def team_key(name: str) -> str:
    for rx, k in _TEAM_RX:
        if rx.search(name or "") and k in TEAMS:
            return k
    return ""


def _path(year: int) -> str:
    return os.path.join(_DIR, f"archive_lck_{year}.json")


def get(year: int, first: bool = True):
    """저장된 기록(없으면 None, 그리고 뒤에서 모으기 시작). first: 화면에서 연 해는 받을 목록 맨 앞으로."""
    if year not in archive_years():
        return None
    with _LOCK:
        d = _CACHE.get(year)
        if d is None and os.path.exists(_path(year)):
            try:
                with open(_path(year), encoding="utf-8") as f:
                    d = _CACHE[year] = json.load(f)
            except (OSError, ValueError):
                d = None
    if d is None or "rosters" not in d or (_old_format(d) and time.time() - d.get("at", 0) > 600) or (d.get("missing") and (time.time() - d.get("at", 0) > 600 or "errors" not in d)):
        build_async(year, first)
    return d


def _no_groups(d) -> bool:
    """예전에 받아 둔 순위표엔 그룹(레전드/라이즈) 정보가 없어서 1위가 둘로 보였음 → 순위표만 다시 받음."""
    return any("groups" not in s for s in d.get("stages") or [])


def _old_format(d) -> bool:
    """예전 저장본: 그룹 없는 순위표, 대회 일정(tours) 없음 → 빠진 부분만 다시 받음(10분 간격)."""
    return _no_groups(d) or "tours" not in d or "champions" not in d


def status() -> list:
    """/api/history: 해마다 받아 둔 정도(리그피디아에 묻지 않고 저장본만 봄)."""
    out = []
    for y in archive_years():
        with _LOCK:
            d = _CACHE.get(y)
            busy = y in _BUSY
            pos = _QUEUE.index(y) + 1 if y in _QUEUE else 0
        if d is None and os.path.exists(_path(y)):
            try:
                with open(_path(y), encoding="utf-8") as f:
                    d = json.load(f)
            except (OSError, ValueError):
                d = None
        d = d or {}
        ready = bool(d.get("stages") or d.get("champions") or d.get("tours"))
        out.append({"year": y, "ready": ready, "champions": len(d.get("champions") or []),
                    "stages": len(d.get("stages") or []), "tours": len(d.get("tours") or []),
                    "rosters": len(d.get("rosters") or []), "moves": len(d.get("moves") or []),
                    "missing": d.get("missing") or [], "errors": d.get("errors") or {},
                    "at": d.get("at") or 0, "queued": pos, "busy": busy})
    return out


def start():
    """켠 지 2분 뒤부터 10분마다: 지난 시즌 기록이 없거나 일부 빠졌으면 다시 받아 봄."""
    def loop():
        time.sleep(120)
        while True:
            for y in archive_years():          # 최근 시즌부터 차례로(한 번에 한 해)
                get(y, False)
            time.sleep(600)
    threading.Thread(target=loop, daemon=True).start()


def _roster_rows(rows):
    """TournamentRosters 행 → [{team(지금 팀 키), team_name(그 당시 이름), role, page, nick}]. 첫 코치를 감독 칸에."""
    out = []
    for r in rows:
        links = [x for x in (r.get("RosterLinks") or "").split(";;")]
        roles = [x for x in (r.get("Roles") or "").split(";;")]
        k = team_key(r["Team"])
        coach = False
        for i, page in enumerate(links):
            page = page.strip()
            if not page:
                continue
            role_raw = (roles[i] if i < len(roles) else "").split(",")[0].strip().lower()
            role = ROLE.get(role_raw, "")
            if role == "Coach" and not coach:
                role, coach = "Head Coach", True          # 첫 코치를 감독 칸에
            elif role == "Head Coach":
                coach = True
            if not role:
                continue
            out.append({"team": k, "team_name": r["Team"], "role": role, "page": page, "nick": _nick(page)})
    return out


_QUEUE = []                          # 받을 연도(앞에서부터). 한 번에 한 해씩만 받음(리그피디아 요청 한도 · 지금 시즌 수집과 나눠 씀)
_WORKER = {"on": False}
GAP_BETWEEN = 20                     # 한 해를 다 받고 다음 해까지 쉬는 시간(초)


def build_async(year: int, first: bool = False):
    """그 해를 받을 목록에 넣음. first=True(누가 그 해 화면을 열었음)면 맨 앞으로."""
    with _LOCK:
        if year in _BUSY:
            if first and year in _QUEUE and _QUEUE[0] != year:
                _QUEUE.remove(year)
                _QUEUE.insert(0, year)
            return
        _BUSY.add(year)
        _QUEUE.insert(0, year) if first else _QUEUE.append(year)
        if _WORKER["on"]:
            return
        _WORKER["on"] = True
    threading.Thread(target=_work, daemon=True).start()


def _work():
    while True:
        with _LOCK:
            if not _QUEUE:
                _WORKER["on"] = False
                return
            year = _QUEUE.pop(0)
        try:
            _build(year)
        except Exception as e:  # noqa: BLE001
            log.warning("archive %s build failed: %s", year, e)
            with _LOCK:
                _BUSY.discard(year)
        time.sleep(GAP_BETWEEN)


def _nick(page: str) -> str:
    return (page or "").split(" (")[0]


def _build(year: int):
    old = _CACHE.get(year) or {}
    d = {"year": year, "stages": old.get("stages"), "champion": old.get("champion"), "roster": old.get("roster"),
         "moves": old.get("moves"), "rosters": old.get("rosters"), "tours": old.get("tours"),
         "champions": old.get("champions"), "shorts": old.get("shorts"), "missing": [], "errors": {}}
    pre = prefix(year)
    try:
        tours = cargo(None, tables="Tournaments", fields="OverviewPage,Name,DateStart,Date,IsPlayoffs,TournamentLevel",
                      where=f'OverviewPage LIKE "{pre}/{year} Season/%" AND TournamentLevel="Primary"', order_by="DateStart")
    except Exception as e:  # noqa: BLE001
        log.warning("archive %s tournaments failed: %s", year, e)
        tours = []
    regular = [t for t in tours if t.get("IsPlayoffs") in ("0", "", None) and not _SKIP.search(t["OverviewPage"])]
    playoff = [t for t in tours if t.get("IsPlayoffs") == "1" and "Season Playoffs" in t["OverviewPage"]]
    tits = titles(tours, year)

    def part(key, fn, again=False):
        if d.get(key) and not again:
            return
        for attempt in (1, 2):
            try:
                d[key] = fn()
                return
            except Exception as e:  # noqa: BLE001
                log.warning("archive %s %s failed: %s", year, key, e)
                d["errors"][key] = str(e)[:200]
                if attempt == 1 and "rate limit" in str(e).lower():
                    time.sleep(60)                         # 한도에 걸렸으면 1분 쉬고 한 번 더
                    continue
                break
        d["missing"].append(key)

    def stages():
        out = []
        for t in regular:
            rows = cargo(None, tables="Standings", fields="Team,Place,WinSeries,LossSeries,WinGames,LossGames",
                         where=f'OverviewPage={_cq(t["OverviewPage"])}', order_by="Place")
            seen, table = set(), []
            for r in rows:
                if r["Team"] in seen:
                    continue
                seen.add(r["Team"])
                table.append({"team": r["Team"], "key": team_key(r["Team"]), "place": r.get("Place") or "",
                              "w": r.get("WinSeries") or "0", "l": r.get("LossSeries") or "0",
                              "gw": r.get("WinGames") or "0", "gl": r.get("LossGames") or "0"})
            # 그룹이 나뉜 대회(예: 2025 3~5라운드 레전드·라이즈): 순위가 그룹 안 순위라 1위가 둘 → 그룹별로 나눠 보여 줌
            grp = cargo(None, tables="TournamentGroups", fields="Team,GroupDisplay,GroupN",
                        where=f'OverviewPage={_cq(t["OverviewPage"])}', order_by="GroupN")
            gof = {g["Team"]: (g.get("GroupDisplay") or "", int(g.get("GroupN") or 0)) for g in grp}
            groups = [n for n, _ in sorted(set(gof.values()), key=lambda x: x[1]) if n]
            for row in table:
                row["group"] = gof.get(row["team"], ("", 0))[0] if len(groups) > 1 else ""
            if table:
                out.append({"name": t["Name"], "page": t["OverviewPage"], "start": t.get("DateStart", ""), "table": table,
                            "groups": groups if len(groups) > 1 else []})
        return out

    def champion():
        if not playoff:
            return {}
        rows = cargo(None, tables="MatchSchedule", fields="Team1,Team2,Winner,Team1Score,Team2Score,DateTime_UTC",
                     where=f'OverviewPage={_cq(playoff[-1]["OverviewPage"])}', order_by="DateTime_UTC DESC", limit=1)
        if not rows:
            return {}
        m = rows[0]
        win, lose = (m["Team1"], m["Team2"]) if m.get("Winner") == "1" else (m["Team2"], m["Team1"])
        ws, ls = (m.get("Team1Score"), m.get("Team2Score")) if m.get("Winner") == "1" else (m.get("Team2Score"), m.get("Team1Score"))
        return {"name": playoff[-1]["Name"], "winner": win, "wkey": team_key(win), "loser": lose, "lkey": team_key(lose),
                "score": f"{ws}:{ls}", "date": (m.get("DateTime_UTC") or m.get("DateTime UTC") or "")[:10]}

    def champions():
        """우승컵이 걸린 대회마다 결승(대회 순서대로): [{name, page, winner, wkey, loser, lkey, score, date}]."""
        if not tits:
            return []
        rows = cargo(None, tables="MatchSchedule", fields="Team1,Team2,Winner,Team1Score,Team2Score,DateTime_UTC=DT,OverviewPage",
                     where=f'OverviewPage IN ({",".join(_cq(t["OverviewPage"]) for t in tits)}) AND Tab IN ("Finals","Final")',
                     order_by="DateTime_UTC")
        last = {}
        for m in rows:
            if m.get("Winner") in ("1", "2"):
                last[m["OverviewPage"]] = m
        out = []
        for t in tits:
            m = last.get(t["OverviewPage"])
            if not m:
                continue
            one = m.get("Winner") == "1"
            win, lose = (m["Team1"], m["Team2"]) if one else (m["Team2"], m["Team1"])
            ws, ls = (m.get("Team1Score"), m.get("Team2Score")) if one else (m.get("Team2Score"), m.get("Team1Score"))
            out.append({"name": t["Name"], "page": t["OverviewPage"], "winner": win, "wkey": team_key(win), "loser": lose,
                        "lkey": team_key(lose), "score": f"{ws}:{ls}", "date": (m.get("DT") or "")[:10]})
        return out

    def shorts():
        """그 당시 팀 이름 → 약칭(리그피디아 Teams): 'SK Telecom T1' → 'SKT'."""
        names = set()
        for st in d.get("stages") or []:
            names |= {r["team"] for r in st["table"]}
        for c in d.get("champions") or []:
            names |= {c["winner"], c["loser"]}
        for t in d.get("tours") or []:
            names |= {w["team"] for w in t.get("winners") or []}
        names.discard("")
        out = {}
        names = sorted(names)
        for i in range(0, len(names), 40):
            for r in cargo(None, tables="Teams", fields="Name,Short",
                           where=f'Name IN ({",".join(_cq(n) for n in names[i:i + 40])})'):
                if r.get("Short"):
                    out[r["Name"]] = r["Short"]
        return out

    def tours_list():
        """그 시즌 대회 일정(일정 탭): 대회마다 기간과 1위 팀(그룹이 나뉜 대회는 그룹마다 1위라 여럿)."""
        if not tours:
            return []
        win = {}
        for r in cargo(None, tables="TournamentResults", fields="OverviewPage,Team",
                       where=f'OverviewPage LIKE "{pre}/{year} Season/%" AND Place_Number=1'):
            win.setdefault(r["OverviewPage"], []).append({"team": r["Team"], "key": team_key(r["Team"])})
        return [{"page": t["OverviewPage"], "name": t["Name"], "start": t.get("DateStart") or "", "end": t.get("Date") or "",
                 "playoff": t.get("IsPlayoffs") == "1", "title": t in tits, "winners": win.get(t["OverviewPage"], [])}
                for t in tours]

    def roster():
        if not regular:
            return []
        return _roster_rows(cargo(None, tables="TournamentRosters", fields="Team,RosterLinks,Roles",
                                  where=f'OverviewPage={_cq(regular[-1]["OverviewPage"])}'))

    def rosters():
        """대회별 등록 로스터(그 당시 팀 이름 그대로): [{name, page, playoff, roster: [...]}] — 대회 순서대로"""
        out = []
        for t in tours:
            rows = _roster_rows(cargo(None, tables="TournamentRosters", fields="Team,RosterLinks,Roles",
                                      where=f'OverviewPage={_cq(t["OverviewPage"])}'))
            if rows:
                out.append({"name": t["Name"], "page": t["OverviewPage"], "playoff": t.get("IsPlayoffs") == "1", "roster": rows})
        return out

    def moves():
        names = sorted({x["team_name"] for x in (d.get("roster") or [])})
        if not names:
            return []
        win = f'Date_Sort>="{year - 1}-11-01" AND Date_Sort<="{year}-01-31"'
        joins = cargo(None, tables="RosterChanges", fields="Date_Sort=D,Player,Direction,Team,Role",
                      where=f'{win} AND Direction="Join" AND Team IN ({",".join(_cq(n) for n in names)})', order_by="Date_Sort")
        players = sorted({r["Player"] for r in joins})
        leaves = []
        for i in range(0, len(players), 40):                 # 그 선수들이 어디서 떠났는지
            chunk = ",".join(_cq(x) for x in players[i:i + 40])
            leaves += cargo(None, tables="RosterChanges", fields="Date_Sort=D,Player,Direction,Team,Role",
                            where=f'{win} AND Direction="Leave" AND Player IN ({chunk})', order_by="Date_Sort")
        rc = sorted(joins + leaves, key=lambda r: (r["D"], 0 if r["Direction"] == "Leave" else 1))
        lck = set(names)
        last_leave, out = {}, []
        for r in rc:
            if r["Direction"] == "Leave":
                last_leave[r["Player"]] = r["Team"]
            elif r["Direction"] == "Join" and r["Team"] in lck:
                frm = last_leave.get(r["Player"], "")
                if frm == r["Team"]:
                    continue                                  # 같은 팀 재계약 표기
                out.append({"date": r["D"], "page": r["Player"], "nick": _nick(r["Player"]), "role": r.get("Role") or "",
                            "from": frm, "fkey": team_key(frm) if frm in lck or team_key(frm) else "",
                            "to": r["Team"], "tkey": team_key(r["Team"])})
        return out

    part("stages", stages, again=_no_groups(d))
    part("tours", tours_list)
    part("champion", champion)
    part("champions", champions)
    part("shorts", shorts)
    part("roster", roster)
    part("rosters", rosters)
    part("moves", moves)
    if not tours:
        d["missing"].append("tournaments")
    d["at"] = time.time()
    try:
        with open(_path(year), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except OSError as e:
        log.warning("archive %s save failed: %s", year, e)
    with _LOCK:
        _CACHE[year] = d
        _BUSY.discard(year)
    log.info("archive %s: stages %d, roster %d, moves %d, missing %s", year, len(d.get("stages") or []),
             len(d.get("roster") or []), len(d.get("moves") or []), d["missing"])
