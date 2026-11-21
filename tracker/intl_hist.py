"""국제전 지난 기록(월즈 2011~ · MSI 2015~ · EWC 2024~ · FST 2025~): 리그피디아에서 대회 하나씩 받아
data/intl_hist_<대회>_<연도>.json 으로 저장해 두고, 국제전 메뉴(web/intl.py)가 지금 수집(schedule 'intl')과 합쳐서 씀.

지금 수집은 지난해·올해만 받음. 그보다 앞선 해는 바뀌지 않으므로 여기서 한 번만 받음(실패한 대회는 30분 뒤 다시).
리그피디아 요청 한도 때문에 한 번에 한 대회씩, 사이사이 쉬면서 받음(모든 요청은 cargo의 공통 간격을 따름)."""
import json
import os
import threading
import time

from . import schedule, teamlogos
from .cargo import _cq, cargo
from .config import DB_PATH, log

_DIR = os.path.dirname(DB_PATH) or "."
_LOCK = threading.Lock()
_MEM = {"at": 0.0, "files": {}, "merged": None}     # 읽어 둔 파일(대회-연도 → dict)과 합친 결과
_STATE = {"index": None, "index_at": 0.0, "on": False}
GAP_BETWEEN = 20                 # 대회 하나를 받고 다음까지 쉬는 시간(초)
RETRY_SEC = 1800                 # 실패한 대회는 30분 뒤 다시
INDEX_SEC = 86400                # 대회 목록은 하루에 한 번


def _path(ev: str, year: str) -> str:
    return os.path.join(_DIR, f"intl_hist_{ev}_{year}.json")


def _index_path() -> str:
    return os.path.join(_DIR, "intl_hist_index.json")


def index(gap=None) -> dict:
    """{(대회, 연도): [문서, …]} — 리그피디아 국제전 대회 목록 전체(하루에 한 번 받음)."""
    if _STATE["index"] is not None and time.time() - _STATE["index_at"] < INDEX_SEC:
        return _STATE["index"]
    rows = None
    try:
        with open(_index_path(), encoding="utf-8") as f:
            saved = json.load(f)
        if time.time() - saved.get("at", 0) < INDEX_SEC:
            rows = saved["rows"]
    except (OSError, ValueError, KeyError):
        pass
    if rows is None:
        leagues_in = ",".join(_cq(x) for x in schedule.INTL_LEAGUES)
        rows = cargo(gap, tables="Tournaments", fields="OverviewPage,Name,DateStart,Date,IsPlayoffs",
                     where=f'Region="International" AND League IN ({leagues_in}) AND TournamentLevel="Primary"',
                     order_by="DateStart")
        try:
            with open(_index_path(), "w", encoding="utf-8") as f:
                json.dump({"at": time.time(), "rows": rows}, f, ensure_ascii=False)
        except OSError as e:
            log.warning("intl hist index save failed: %s", e)
    out = {}
    for t in rows:
        ev, y = schedule.intl_event(t["OverviewPage"])
        if ev:
            out.setdefault((ev, y), []).append(t)
    _STATE.update(index=out, index_at=time.time())
    return out


def _live_years() -> set:
    """지금 수집(schedule 'intl')에 이미 있는 (대회, 연도): 여기서 따로 받지 않음."""
    d = schedule.get(schedule.INTL)
    return {schedule.intl_event(p)[0:2] for p in [t.get("page", "") for t in d.get("tours") or []]
            + [m.get("page", "") for m in d.get("matches") or []]} - {(None, "")}


def load(ev: str, year: str):
    with _LOCK:
        if (ev, year) in _MEM["files"]:
            return _MEM["files"][(ev, year)]
    try:
        with open(_path(ev, year), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = None
    with _LOCK:
        _MEM["files"][(ev, year)] = d
        _MEM["merged"] = None
    return d


def build(ev: str, year: str, tours: list, gap=None) -> dict:
    """그 대회(연도) 하나: 경기 · 팀(약칭·로고 파일) · 참가팀 로스터 → 국제전 수집과 같은 모양."""
    by_page = {t["OverviewPage"]: t for t in tours}
    pages = list(by_page)
    matches = []
    for off in range(0, 5000, 500):
        rows = cargo(gap, tables="MatchSchedule",
                     fields="Team1,Team2,Winner,Team1Score,Team2Score,DateTime_UTC=DT,BestOf,Tab,MatchId,OverviewPage,FF,IsNullified",
                     where=f'OverviewPage IN ({",".join(_cq(p) for p in pages)})', order_by="DateTime_UTC", offset=off)
        matches += [schedule._match(schedule.INTL, r, by_page[r["OverviewPage"]]) for r in rows
                    if r.get("OverviewPage") in by_page and r.get("IsNullified") != "1" and r.get("DT")]
        if len(rows) < 500:
            break
    matches.sort(key=lambda m: m["at"])
    for m in matches:                                   # 그 당시 이름이 지금과 다른 LCK 팀(SK Telecom T1 · Samsung White …)은 그 당시 팀으로
        m["k1"], m["k2"] = _hkey(m["t1"]), _hkey(m["t2"])
    names = {m[s] for m in matches for s in ("t1", "t2")} - {"", "TBD"}
    ours = {n for n in names if _hkey(n) in schedule.LCK_KEYS}
    rows = teamlogos.team_rows(names - ours, gap) if names - ours else {}
    teams = {}
    for n in names:
        k = _hkey(n)
        if n in ours:
            teams[k] = {"name": n, "short": schedule.LEAGUES["lck"]["teams"][k].get("short") or n, "image": ""}
        elif k:
            teams[k] = {"name": n, "short": (rows.get(n) or {}).get("Short") or n, "image": (rows.get(n) or {}).get("Image") or ""}
    rosters = schedule._rosters(pages, gap)
    d = {"ev": ev, "year": year, "at": time.time(), "complete": bool(matches),
         "tours": [{"page": t["OverviewPage"], "name": t["Name"], "start": t.get("DateStart") or "",
                    "end": t.get("Date") or "", "playoff": t.get("IsPlayoffs") == "1"} for t in tours],
         "matches": matches, "teams": teams, "rosters": rosters}
    try:
        teamlogos.ensure({k: t["image"] for k, t in teams.items() if t.get("image")})
    except Exception as e:  # noqa: BLE001
        log.warning("intl hist %s %s logos failed: %s", ev, year, e)
    return d


def _hkey(name: str) -> str:
    """팀 키: 지금 LCK 팀 이름 그대로면 그 팀 키(로고·약칭), 그 당시 이름이 다르면 그 이름의 키(그 당시 로고·약칭)."""
    k = schedule.team_id(schedule.INTL, name)
    if k in schedule.LCK_KEYS and (name or "").lower() != (schedule.LEAGUES["lck"]["teams"][k].get("wiki") or "").lower():
        return schedule.slug(name)
    return k


def todo() -> list:
    """아직 없거나(또는 실패해서 30분이 지난) 지난 대회, 최근 것부터."""
    live = _live_years()
    out = []
    for (ev, y), tours in sorted(index().items(), key=lambda x: x[0][1], reverse=True):
        if (ev, y) in live or not any(t.get("DateStart") for t in tours):
            continue                                   # 지금 수집에 있거나 아직 열리지 않은(날짜 없는) 대회
        d = load(ev, y)
        if d is None or (not d.get("complete") and time.time() - d.get("at", 0) > RETRY_SEC):
            out.append((ev, y, tours))
    return out


def _run_once():
    for ev, y, tours in todo():
        try:
            d = build(ev, y, tours)
        except Exception as e:  # noqa: BLE001
            log.warning("intl hist %s %s failed: %s", ev, y, e)
            d = {"ev": ev, "year": y, "at": time.time(), "complete": False, "tours": [], "matches": [], "teams": {}, "rosters": {}}
        try:
            with open(_path(ev, y), "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
        except OSError as e:
            log.warning("intl hist %s %s save failed: %s", ev, y, e)
        with _LOCK:
            _MEM["files"][(ev, y)] = d
            _MEM["merged"] = None
        log.info("intl hist %s %s: %d matches", ev, y, len(d["matches"]))
        time.sleep(GAP_BETWEEN)


def status() -> list:
    """/api/history: 지난 국제전마다 받아 둔 정도(대회 목록은 저장본만 봄 — 리그피디아에 묻지 않음)."""
    idx = _STATE["index"]
    if idx is None:
        try:
            with open(_index_path(), encoding="utf-8") as f:
                rows = json.load(f)["rows"]
            idx = {}
            for t in rows:
                ev, y = schedule.intl_event(t["OverviewPage"])
                if ev:
                    idx.setdefault((ev, y), []).append(t)
        except (OSError, ValueError, KeyError):
            idx = {}
    live = _live_years()
    out = []
    for (ev, y), tours in sorted(idx.items(), key=lambda x: (x[0][1], x[0][0]), reverse=True):
        if not any(t.get("DateStart") for t in tours):
            continue
        d = load(ev, y) or {}
        out.append({"ev": ev, "year": y, "live": (ev, y) in live, "complete": bool(d.get("complete")) or (ev, y) in live,
                    "matches": len(d.get("matches") or []), "rosters": len(d.get("rosters") or {}), "at": d.get("at") or 0})
    return out


def start():
    """켠 지 4분 뒤부터(지금 시즌 수집이 먼저) 30분마다: 빠진 지난 국제전을 한 대회씩 받음."""
    def loop():
        time.sleep(240)
        while True:
            try:
                _run_once()
            except Exception as e:  # noqa: BLE001
                log.warning("intl hist loop: %s", e)
            time.sleep(RETRY_SEC)
    threading.Thread(target=loop, daemon=True).start()


def merged(live: dict) -> dict:
    """지금 수집(live) + 저장해 둔 지난 대회들 → 국제전 화면이 쓰는 한 덩어리(같은 대회-연도는 지금 수집이 우선)."""
    with _LOCK:
        cache = _MEM["merged"]
        if cache and cache[0] is live:
            return cache[1]
    have = {schedule.intl_event(p)[0:2] for p in [t.get("page", "") for t in live.get("tours") or []]
            + [m.get("page", "") for m in live.get("matches") or []]}
    files = []
    try:
        names = [n for n in os.listdir(_DIR) if n.startswith("intl_hist_") and n.endswith(".json") and n != "intl_hist_index.json"]
    except OSError:
        names = []
    for n in names:
        ev, y = n[len("intl_hist_"):-len(".json")].rsplit("_", 1)
        if (ev, y) in have:
            continue
        d = load(ev, y)
        if d and d.get("matches"):
            files.append(d)
    if not files:
        out = live
    else:
        out = {**live,
               "tours": list(live.get("tours") or []) + [t for d in files for t in d["tours"]],
               "matches": list(live.get("matches") or []) + [m for d in files for m in d["matches"]],
               "teams": {**{k: v for d in files for k, v in d["teams"].items()}, **(live.get("teams") or {})},
               "rosters": {**{k: v for d in files for k, v in d["rosters"].items()}, **(live.get("rosters") or {})}}
    with _LOCK:
        _MEM["merged"] = (live, out)
    return out
