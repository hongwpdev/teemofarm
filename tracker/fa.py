"""수집: FA 현황·로스터·선수 프로필(Leaguepedia Cargo: RosterChanges·Players·Tenures)."""
import hashlib
import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

from .cargo import RATE_MSG, _cq, _real_name, cargo, is_rate_limit
from .config import KST, PROFILE_MAX_AGE, TEAMS, WIKI_BASE, log
from .core import db, fmt_kst, norm_title, set_status

FA_ROLES = ("Top", "Jungle", "Mid", "Bot", "Support")
PLAYER_FIELDS = "ID,OverviewPage=P,Country,Birthdate,Team,Role,Contract,NameFull=N"
PLAYER_CACHE = {}          # page -> (가져온 시각, 정보)
PLAYER_CACHE_SEC = 1800
PROFILE_RETRY = {}         # 프로필 받기가 실패했을 때 다시 받을 목록
COUNTRY_KO = {"South Korea": "대한민국", "China": "중국", "Taiwan": "대만", "Vietnam": "베트남",
              "Japan": "일본", "United States": "미국", "Canada": "캐나다", "Denmark": "덴마크",
              "France": "프랑스", "Germany": "독일", "Spain": "스페인", "Poland": "폴란드",
              "Sweden": "스웨덴", "Brazil": "브라질", "Australia": "호주", "Hong Kong": "홍콩"}


def fa_since() -> str:
    """이번 스토브리그 시작일(기본: 11월 1일). FA_SINCE 환경변수로 바꿀 수 있음."""
    v = os.getenv("FA_SINCE", "")
    if v:
        return v
    t = datetime.now(KST).date()
    return f"{t.year if t.month >= 11 else t.year - 1}-11-01"


def fa_role(r: str) -> str:
    """리그피디아 역할 → Top/Jungle/Mid/Bot/Support/Head Coach/Coach/Analyst, 그 밖(스트리머·단장 등)은 ''."""
    r = (r or "").strip()
    low = r.lower()
    if r in FA_ROLES:
        return r
    if "head coach" in low:
        return "Head Coach"
    if "coach" in low:
        return "Coach"
    if "analyst" in low:
        return "Analyst"
    return ""


def classify_fa(rc, exp, players, today: str):
    """로스터 변동·계약 만료·현재 소속으로 FA 목록을 만든다(네트워크 없음, 시험하기 쉽게 분리).
    상태: move=이적 확정, stay=잔류(재계약·보직 변경), fa=미정."""
    lck = {t["wiki"].lower(): k for k, t in TEAMS.items() if t.get("wiki")}
    info = {r["P"]: r for r in list(exp) + list(players)}
    joins = {}
    for r in rc:
        if r["Direction"] == "Join":
            joins.setdefault(r["Player"], []).append(r)
    out = {}

    def nick(page):
        return (info.get(page, {}).get("ID") or page.split(" (")[0]).strip()

    for r in sorted((x for x in rc if x["Direction"] == "Leave"), key=lambda x: x["D"]):
        page, frm = r["Player"], lck.get(r["Team"].lower())
        role = fa_role(r["Role"])
        if not frm or not role:
            continue
        d = r["D"][:10]
        later = [j for j in joins.get(page, []) if j["D"][:10] >= d]
        same = [j for j in later if j["Team"].lower() == r["Team"].lower()]
        other = [j for j in later if j["Team"].lower() != r["Team"].lower()]
        cur = info.get(page, {})
        cur_team = (cur.get("Team") or "").strip()
        cur_until = (cur.get("Contract") or "")[:10]
        st, to, to_name, until, memo, show_role = "fa", "", "", "", "", role
        if other:
            st, to_name = "move", other[-1]["Team"]
        elif same:
            st, to_name = "stay", r["Team"]
            new_role = fa_role(same[-1]["Role"])
            if not new_role:
                memo = "보직 변경"
            elif "interim" in r["Role"].lower() and new_role == "Head Coach":
                memo, show_role = "정식 감독", new_role
            elif new_role == "Head Coach" and role != "Head Coach":
                memo, show_role = "감독 승격", new_role
            else:
                memo, show_role = "재계약", new_role
        elif cur_team and cur_team.lower() != r["Team"].lower():
            st, to_name = "move", cur_team
        elif cur_team and cur_until > today:
            st, to_name, memo = "stay", r["Team"], "재계약"
        if st != "fa":
            to = lck.get(to_name.lower(), "")
            if cur_team.lower() == to_name.lower() and cur_until > today:
                until = cur_until
        out[page] = (page, nick(page), _real_name(cur.get("N", "")), frm, show_role,
                     st, to, "" if to else to_name, until, d, memo)

    for r in exp:   # 계약은 끝났지만 아직 결별·재계약 기록이 없는 사람
        page, frm, role = r["P"], lck.get((r["Team"] or "").lower()), fa_role(r["Role"])
        if page in out or not frm or not role:
            continue
        out[page] = (page, nick(page), _real_name(r.get("N", "")), frm, role,
                     "fa", "", "", "", (r["Contract"] or "")[:10], "계약 만료")
    return list(out.values())


FA_FULL_SEC = 3 * 3600      # 이적 기록이 그대로여도 이 시간마다 한 번은 계약·로스터를 전부 새로 받음


def _meta_get(k):
    with db() as c:
        r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else ""


def poll_fa(gap=None, max_age=FA_FULL_SEC):
    """FA·로스터·프로필. 요청을 줄이려고 이적 기록(RosterChanges, 요청 1번)이 지난번과 같고
    마지막 전체 갱신이 max_age초 안이면 나머지(계약·로스터·프로필, 5번 안팎)를 건너뜀."""
    try:
        since = fa_since()
        today = datetime.now(KST).date().isoformat()
        names = ",".join(_cq(t["wiki"]) for t in TEAMS.values() if t.get("wiki"))
        rc = cargo(gap, tables="RosterChanges", fields="Date_Sort=D,Player,Direction,Team,Role",
                   where=f'Date_Sort>="{since}" AND Team IN ({names})', order_by="Date_Sort")
        sig = hashlib.sha1(json.dumps([today, rc], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        try:
            full_at = float(_meta_get("fa_full_at") or 0)
        except ValueError:
            full_at = 0
        if sig == _meta_get("fa_sig") and time.time() - full_at < max_age:
            with db() as c:
                if c.execute("SELECT COUNT(*) FROM fa").fetchone()[0]:
                    c.execute("INSERT OR REPLACE INTO meta VALUES('fa_updated', ?)", (datetime.now(timezone.utc).isoformat(),))
                    log.info("fa: no roster changes, skipped")
                    set_status("fa", "fa", True, "변동 없음")
                    return
        exp = cargo(gap, tables="Players", fields=PLAYER_FIELDS,
                    where=f'Team IN ({names}) AND Contract>="{since}" AND Contract<"{today}"')
        pages = sorted({r["Player"] for r in rc})
        players = []
        for i in range(0, len(pages), 40):   # 주소가 너무 길어지지 않게 나눠서
            chunk = ",".join(_cq(x) for x in pages[i:i + 40])
            players += cargo(gap, tables="Players", fields=PLAYER_FIELDS,
                             where=f"OverviewPage IN ({chunk})")
        rows = classify_fa(rc, exp, players, today)
        with db() as c:
            if not rows and c.execute("SELECT COUNT(*) FROM fa").fetchone()[0]:
                raise RuntimeError("빈 결과라 기존 FA 목록을 유지함")
            c.execute("DELETE FROM fa")
            c.executemany("INSERT INTO fa(page,nick,real,team_from,role,status,team_to,team_to_name,until,date,memo) VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
            c.execute("INSERT OR REPLACE INTO meta VALUES('fa_updated', ?)",
                      (datetime.now(timezone.utc).isoformat(),))
        log.info("fa: %d rows", len(rows))
        note = ""
        try:
            roster, roster_players = poll_roster(gap, names, today, rows, rc)
            log.info("roster: %d", roster)
            with db() as c:                       # 로스터까지 받았으면 다음엔 이적 기록이 그대로일 때 건너뜀
                c.executemany("INSERT OR REPLACE INTO meta VALUES(?,?)", [("fa_sig", sig), ("fa_full_at", str(time.time()))])
        except Exception as e:  # noqa: BLE001  (로스터 실패해도 FA 목록은 그대로)
            roster_players = []
            note = " · 로스터는 이전 것 유지"
            log.warning("roster failed: %s", e)
        try:
            pages = [r[0] for r in rows] + [p["P"] for p in roster_players]
            n = save_profiles(list(dict.fromkeys(pages)), list(exp) + list(players) + list(roster_players), gap)
            log.info("fa: %d profiles", n)
            PROFILE_RETRY.clear()
        except Exception as e:  # noqa: BLE001  (프로필 실패해도 FA 목록은 그대로)
            note = " · 프로필은 이전 것 유지"
            PROFILE_RETRY.update(pages=list(dict.fromkeys(pages)), players=list(exp) + list(players) + list(roster_players))
            log.warning("fa profiles failed: %s", e)
        set_status("fa", "fa", True, f"FA {len(rows)}명{note}")
    except Exception as e:  # noqa: BLE001
        set_status("fa", "fa", False, RATE_MSG if is_rate_limit(e) else str(e)[:120])
        log.warning("fa failed: %s", e)


def poll_roster(gap, names, today, fa_rows, rc=None):
    """리그피디아 계약 기준 현재 로스터(선수 5포지션 + 감독)를 roster 표에 저장. → (줄 수, Players 행 목록)"""
    lck = {t["wiki"].lower(): k for k, t in TEAMS.items() if t.get("wiki")}
    players = cargo(gap, tables="Players", fields=PLAYER_FIELDS, where=f"Team IN ({names})")
    keep = []
    for p in players:
        team = lck.get((p.get("Team") or "").lower())
        role = fa_role(p.get("Role") or "")
        until = (p.get("Contract") or "")[:10]
        if not team or role not in FA_ROLES + ("Head Coach",) or (until and until < today):
            continue
        keep.append(p)
    joined = {(r[6], r[0]) for r in fa_rows if r[5] == "move" and r[6]}   # (새 팀, page)
    stay = {(r[3], r[0]) for r in fa_rows if r[5] == "stay"}
    for r in rc or []:   # LCK 밖(2군·해외 등)에서 이번 스토브리그에 들어온 선수도 '영입'으로 표시
        t = lck.get((r.get("Team") or "").lower())
        if t and (r.get("Direction") or "").lower() == "join" and (t, r.get("Player")) not in stay:
            joined.add((t, r.get("Player")))
    rows = [("lck", lck[p["Team"].lower()], fa_role(p["Role"]), p["P"], (p.get("ID") or p["P"].split(" (")[0]),
             _real_name(p.get("N", "")), (p.get("Contract") or "")[:10],
             1 if (lck[p["Team"].lower()], p["P"]) in joined else 0) for p in keep]
    # 감독: Players에 Head Coach가 없으면 이번 스토브리그 기록(잔류·이적)의 감독으로 채움
    has_coach = {r[1] for r in rows if r[2] == "Head Coach"}
    for r in fa_rows:
        team = r[6] or (r[3] if r[5] == "stay" else "")
        if r[4] == "Head Coach" and r[5] in ("stay", "move") and r[10] != "보직 변경" and team and team not in has_coach:
            rows.append(("lck", team, "Head Coach", r[0], r[1], r[2], r[8], 1 if r[5] == "move" else 0))
            has_coach.add(team)
    with db() as c:
        c.execute("DELETE FROM roster WHERE league='lck'")
        c.executemany("INSERT OR REPLACE INTO roster(league,team,role,page,nick,real,until,joined) VALUES(?,?,?,?,?,?,?,?)", rows)
    return len(rows), keep


def save_profiles(pages, players, gap) -> int:
    """FA 선수들의 커리어(Tenures)를 묶어서 받아 프로필 표에 저장.
    요청을 줄이려고 프로필이 없거나 PROFILE_MAX_AGE보다 오래된 선수만 받음."""
    me = {}
    for r in players:
        me.setdefault(r["P"], r)   # 같은 선수가 여러 번 있으면 먼저 받은 것(FA 쪽) 사용
    cut = (datetime.now(timezone.utc) - timedelta(seconds=PROFILE_MAX_AGE)).isoformat()
    with db() as c:
        fresh = {r["page"] for r in c.execute("SELECT page FROM profile WHERE at >= ?", (cut,))}
    pages = [pg for pg in pages if pg not in fresh]
    if not pages:
        return 0
    for i in range(0, len(pages), 20):    # 20명씩(한 번에 최대 500줄), 받는 대로 저장해서 중간에 막혀도 받은 만큼은 남김
        part = pages[i:i + 20]
        ten = {}
        chunk = ",".join(_cq(x) for x in part)
        for t in cargo(gap, tables="Tenures", fields="Player,Team,DateJoin,DateLeave",
                       where=f"Player IN ({chunk})", order_by="Player,DateJoin"):
            ten.setdefault(t["Player"], []).append(t)
        now = datetime.now(timezone.utc).isoformat()
        with db() as c:
            c.executemany("INSERT OR REPLACE INTO profile VALUES(?,?,?)",
                          [(pg, json.dumps(build_profile(pg, me.get(pg, {}), ten.get(pg, [])), ensure_ascii=False), now)
                           for pg in part])
    return len(pages)


def retry_profiles(gap=None):
    """FA 수집 때 프로필 받기가 막혔으면(요청 한도 등) 30분을 기다리지 않고 몇 분 뒤 남은 선수만 다시 받음."""
    if not PROFILE_RETRY:
        return
    try:
        n = save_profiles(PROFILE_RETRY["pages"], PROFILE_RETRY["players"], gap)
        PROFILE_RETRY.clear()
        log.info("fa: %d profiles (retry)", n)
    except Exception as e:  # noqa: BLE001
        log.warning("fa profiles retry failed: %s", e)


def _ym(d: str) -> str:
    return d[:7].replace("-", ".") if d else ""


def build_profile(page: str, me: dict, ten: list) -> dict:
    """Players 한 줄 + Tenures 목록 → 팝업용 프로필."""
    lck = {t["wiki"].lower(): k for k, t in TEAMS.items() if t.get("wiki")}
    career = []
    for t in sorted(ten, key=lambda x: x.get("DateJoin") or ""):   # 같은 팀에 이어서 재계약한 기간은 한 줄로
        team, j, lv = (t.get("Team") or "").strip(), (t.get("DateJoin") or "")[:10], (t.get("DateLeave") or "")[:10]
        if not team:
            continue
        if career and career[-1]["team"].lower() == team.lower() and career[-1]["leave"] and j <= career[-1]["leave"][:8] + "31":
            career[-1]["leave"] = lv
            continue
        career.append({"team": team, "join": j, "leave": lv})
    born = (me.get("Birthdate") or "")[:4]
    return {
        "page": page, "nick": (me.get("ID") or page.split(" (")[0]), "real": _real_name(me.get("N", "")),
        "country": COUNTRY_KO.get(me.get("Country") or "", me.get("Country") or ""),
        "born": born if born.isdigit() else "",
        "career": [{"from": _ym(c["join"]), "to": _ym(c["leave"]), "team": c["team"],
                    "key": lck.get(c["team"].lower(), "")} for c in reversed(career)],
        "wiki": WIKI_BASE + urllib.parse.quote(page.replace(" ", "_")),
    }


def player_info(page: str) -> dict:
    """선수 한 명의 프로필·커리어(리그피디아)와 관련 소식(우리 DB)."""
    page = (page or "").strip()[:120]
    if not page:
        raise ValueError("선수 이름이 없어요")
    hit = PLAYER_CACHE.get(page)
    if hit and time.time() - hit[0] < PLAYER_CACHE_SEC:
        info = hit[1]
    else:
        with db() as c:
            row = c.execute("SELECT data FROM profile WHERE page=?", (page,)).fetchone()
        if row:
            info = json.loads(row["data"])
        else:   # FA 수집 때 못 받은 선수만 그 자리에서(한도 초과면 기다리지 않고 바로 안내)
            pq = _cq(page)
            pl = cargo(0, retry=False, tables="Players", fields=PLAYER_FIELDS, where=f"OverviewPage={pq}", limit=1)
            ten = cargo(0, retry=False, tables="Tenures", fields="Player,Team,DateJoin,DateLeave",
                        where=f"Player={pq}", order_by="DateJoin", limit=100)
            info = build_profile(page, pl[0] if pl else {}, ten)
        PLAYER_CACHE[page] = (time.time(), info)
    # 관련 소식: 제목에 본명이나 닉네임이 들어간 기사(최근 5건)
    from .filters import is_lol_news, ko_nicks    # 동명이인(배우·야구 선수 등) 기사는 빼고 LoL 기사만
    names = [n for n in (info["real"], info["nick"], ko_nicks().get(info["nick"], "")) if n]
    news = []
    if names:
        rx = re.compile("|".join(rf"(?<![A-Za-z0-9]){re.escape(n)}(?![A-Za-z0-9])" for n in names), re.I)
        seen = set()
        with db() as c:
            for r in c.execute("SELECT title,url,outlet,published,source FROM items WHERE source != 'news_en' "
                               "ORDER BY published DESC LIMIT 3000"):
                k = norm_title(r["title"])
                if k in seen or not rx.search(r["title"]) or not is_lol_news(r["title"]):
                    continue
                seen.add(k)
                news.append({"title": r["title"], "url": r["url"],
                             "outlet": r["outlet"] if r["source"] == "news" else "리그피디아",
                             "when": fmt_kst(r["published"])})
                if len(news) >= 5:
                    break
    return {**info, "news": news}
