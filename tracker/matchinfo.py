"""경기 상세(세트별 밴픽·출전 선수·챔피언·KDA): 리그피디아 ScoreboardGames·ScoreboardPlayers.
화면에서 경기를 눌렀을 때만 받고(요청 부담 줄이기), DB에 저장해 둠.
- 경기가 끝나고 하루가 지났고 세트마다 선수 10명이 다 있으면 다시 받지 않음
- 그 전(막 끝난 경기: 리그피디아가 채우는 중)이면 20분 지난 저장본은 새로 받음"""
import json
import threading
import time
from datetime import datetime, timezone

from . import champs
from .cargo import _cq, cargo
from .core import db

ROLE_ORDER = {"Top": 0, "Jungle": 1, "Mid": 2, "Bot": 3, "Support": 4}
STALE_SEC = 1200
_LOCKS, _LOCKS_LOCK = {}, threading.Lock()


def init():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS match_detail(id TEXT PRIMARY KEY, data TEXT, at REAL, final INTEGER)")


def _lock(mid):
    with _LOCKS_LOCK:
        return _LOCKS.setdefault(mid, threading.Lock())


def _champ_list(s):
    return [champs.info(x.strip()) for x in (s or "").split(",") if x.strip()]


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def fetch(mid: str) -> dict:
    games = cargo(0, tables="ScoreboardGames",
                  fields="GameId,N_GameInMatch=N,Team1,Team2,Winner,Gamelength,Patch,VOD,Team1Picks,Team2Picks,Team1Bans,Team2Bans,"
                         "Team1Kills,Team2Kills,Team1Gold,Team2Gold,Team1Towers,Team2Towers,Team1Dragons,Team2Dragons,Team1Barons,Team2Barons,DateTime_UTC=DT",
                  where=f"MatchId={_cq(mid)}", order_by="N_GameInMatch")
    players = []
    if games:
        players = cargo(0, tables="ScoreboardPlayers",
                        fields="GameId,Link,Team,Role,Champion,Kills,Deaths,Assists,CS,Gold,DamageToChampions,Side",
                        where=f"MatchId={_cq(mid)}")
    by_game = {}
    for p in players:
        by_game.setdefault(p["GameId"], []).append(p)
    out = []
    for g in games:
        sides = {}
        for side, n in (("blue", "1"), ("red", "2")):
            team = g[f"Team{n}"]
            ps = [p for p in by_game.get(g["GameId"], []) if p.get("Team") == team]
            ps.sort(key=lambda p: ROLE_ORDER.get(p.get("Role"), 9))
            sides[side] = {
                "team": team, "picks": _champ_list(g[f"Team{n}Picks"]), "bans": _champ_list(g[f"Team{n}Bans"]),
                "kills": _int(g.get(f"Team{n}Kills")), "gold": _int(g.get(f"Team{n}Gold")),
                "towers": _int(g.get(f"Team{n}Towers")), "dragons": _int(g.get(f"Team{n}Dragons")),
                "barons": _int(g.get(f"Team{n}Barons")),
                "players": [{"name": (p.get("Link") or "").split(" (")[0], "page": p.get("Link") or "", "role": p.get("Role") or "", "champ": champs.info(p.get("Champion") or ""),
                             "k": _int(p.get("Kills")), "d": _int(p.get("Deaths")), "a": _int(p.get("Assists")),
                             "cs": _int(p.get("CS")), "gold": _int(p.get("Gold")), "dmg": _int(p.get("DamageToChampions"))}
                            for p in ps]}
        out.append({"n": _int(g.get("N")) or len(out) + 1, "win": {"1": "blue", "2": "red"}.get(g.get("Winner"), ""),
                    "len": g.get("Gamelength") or "", "patch": g.get("Patch") or "", "vod": g.get("VOD") or "",
                    "at": g.get("DT") or "", **sides})
    return {"id": mid, "games": out}


def _is_final(d: dict) -> bool:
    gs = d.get("games") or []
    if not gs or any(len(g["blue"]["players"]) < 5 or len(g["red"]["players"]) < 5 for g in gs):
        return False
    try:
        last = datetime.strptime(gs[-1]["at"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - last).total_seconds() > 86400


def get(mid: str) -> dict:
    """저장본이 있으면 그것, 없거나 오래됐으면(막 끝난 경기) 리그피디아에서 새로."""
    with db() as c:
        r = c.execute("SELECT data, at, final FROM match_detail WHERE id=?", (mid,)).fetchone()
    if r and (r["final"] or time.time() - r["at"] < STALE_SEC):
        return json.loads(r["data"])
    with _lock(mid):                                   # 여러 명이 동시에 눌러도 한 번만 받음
        with db() as c:
            r2 = c.execute("SELECT data, at FROM match_detail WHERE id=?", (mid,)).fetchone()
        if r2 and r2["at"] > (r["at"] if r else 0):
            return json.loads(r2["data"])
        d = fetch(mid)
        with db() as c:
            c.execute("INSERT OR REPLACE INTO match_detail VALUES(?,?,?,?)",
                      (mid, json.dumps(d, ensure_ascii=False), time.time(), 1 if _is_final(d) else 0))
        return d
