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
    """고를 수 있는 지난 시즌: 지금 시즌 바로 앞 두 시즌(최근 것부터). 해가 바뀌면 알아서 늘어남."""
    cs = current_season()
    return (cs - 1, cs - 2)
_DIR = os.path.dirname(DB_PATH) or "."
_LOCK = threading.Lock()
_CACHE = {}                          # 연도 -> dict
_BUSY = set()
ROLE = {"top": "Top", "jungle": "Jungle", "mid": "Mid", "bot": "Bot", "adc": "Bot", "support": "Support",
        "coach": "Coach", "head coach": "Head Coach"}
# 예전 팀 이름 → 지금 팀 키(로고·색)
_TEAM_RX = [(re.compile(rx, re.I), k) for rx, k in (
    (r"hanwha", "hle"), (r"^t1\b", "t1"), (r"gen\.?g", "geng"), (r"dplus|damwon|\bdk\b", "dk"), (r"\bkt\b", "kt"),
    (r"nongshim|\bns\b", "ns"), (r"fearx|liiv sandbox|sandbox", "bfx"), (r"\bdrx\b", "drx"),
    (r"freecs|soopers|kwangdong|afreeca", "dns"), (r"brion", "bro"))]


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


def get(year: int):
    """저장된 기록(없으면 None, 그리고 뒤에서 모으기 시작)."""
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
    if d is None or "rosters" not in d or (d.get("missing") and (time.time() - d.get("at", 0) > 600 or "errors" not in d)):
        build_async(year)
    return d


def start():
    """켠 지 2분 뒤부터 10분마다: 지난 시즌 기록이 없거나 일부 빠졌으면 다시 받아 봄."""
    def loop():
        time.sleep(120)
        while True:
            for y in archive_years():
                get(y)
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


def build_async(year: int):
    with _LOCK:
        if year in _BUSY:
            return
        _BUSY.add(year)
    threading.Thread(target=_build, args=(year,), daemon=True).start()


def _nick(page: str) -> str:
    return (page or "").split(" (")[0]


def _build(year: int):
    old = _CACHE.get(year) or {}
    d = {"year": year, "stages": old.get("stages"), "champion": old.get("champion"), "roster": old.get("roster"),
         "moves": old.get("moves"), "rosters": old.get("rosters"), "missing": [], "errors": {}}
    try:
        tours = cargo(None, tables="Tournaments", fields="OverviewPage,Name,DateStart,IsPlayoffs,TournamentLevel",
                      where=f'OverviewPage LIKE "LCK/{year} Season/%" AND TournamentLevel="Primary"', order_by="DateStart")
    except Exception as e:  # noqa: BLE001
        log.warning("archive %s tournaments failed: %s", year, e)
        tours = []
    regular = [t for t in tours if t.get("IsPlayoffs") in ("0", "", None)]
    playoff = [t for t in tours if t.get("IsPlayoffs") == "1" and "Season Playoffs" in t["OverviewPage"]]

    def part(key, fn):
        if d.get(key):
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
            if table:
                out.append({"name": t["Name"], "page": t["OverviewPage"], "start": t.get("DateStart", ""), "table": table})
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

    part("stages", stages)
    part("champion", champion)
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
