"""국제전 메뉴(FST · MSI · EWC · WORLDS): 소식 · 대회 일정(일정 / 결과·순위) · 진출팀 — 네 대회가 화면 틀 하나를 같이 씀.

데이터는 모두 리그피디아 국제전 수집(schedule 'intl': 대회 목록·경기·팀·로스터)에서 그 대회 문서만 골라 씀.
대회마다 형식이 달라서(그룹 → 녹아웃, 플레이-인 → 더블 엘리미네이션 브래킷, 스위스 …) 스테이지를 미리 정해 두지 않고
경기 탭 이름(리그피디아 'Tab')으로 단계를 나눠 계산함. 새 해 대회가 리그피디아에 올라오면 코드 수정 없이 저절로 보임."""
import re
from datetime import datetime, timedelta, timezone

from .. import schedule
from ..config import KST
from ..core import db
from ..filters import is_lol_news

# 메뉴(리그 고르기의 '국제전' 묶음). 대회 문서 규칙은 schedule.INTL_EVENTS
EVENTS = {
    "fst": {"name": "FST", "sub": "퍼스트 스탠드", "full": "퍼스트 스탠드", "news": ("퍼스트 스탠드", "First Stand", "FST")},
    "msi": {"name": "MSI", "sub": "미드 시즌 인비테이셔널", "full": "MSI", "news": ("MSI", "미드 시즌 인비테이셔널", "Mid-Season Invitational")},
    "ewc": {"name": "EWC", "sub": "e스포츠 월드컵", "full": "e스포츠 월드컵", "news": ("EWC", "e스포츠 월드컵", "E스포츠 월드컵", "이스포츠 월드컵", "Esports World Cup")},
    "worlds": {"name": "WORLDS", "sub": "월드 챔피언십", "full": "월드 챔피언십", "news": ("롤드컵", "월즈", "Worlds", "월드 챔피언십", "World Championship")},
}
STAGE_NAME = {"playin": "플레이-인 스테이지", "group": "그룹 스테이지", "swiss": "스위스 스테이지",
              "bracket": "브래킷 스테이지", "ko": "녹아웃 스테이지", "main": "본선"}
ROUND_NAME = {"Finals": "결승", "Final": "결승", "Third-Place Match": "3·4위전", "Semifinals": "4강", "Quarterfinals": "8강"}
KO_TABS = ("Finals", "Final", "Third-Place Match", "Semifinals", "Quarterfinals")
# 리그피디아 TournamentRosters의 권역 → 화면 이름(모르는 값은 그대로, 대소문자 무시)
REGION = {"KR": "LCK", "CN": "LPL", "EMEA": "LEC", "EUW": "LEC", "EU": "LEC", "NA": "LCS", "APAC": "LCP", "PCS": "LCP",
          "VN": "LCP", "JP": "LCP", "OCE": "LCP", "BR": "CBLOL", "BRAZIL": "CBLOL", "LAT": "LLA", "LTA": "LTA"}
REGION_ORDER = ("LCK", "LPL", "LEC", "LCS", "LCP", "CBLOL", "LTA", "LLA")
ROLE_KO = {"Top": "탑", "Jungle": "정글", "Mid": "미드", "Bot": "원딜", "Support": "서폿"}
SPOIL = 'title="스포 방지 중이면 눌러서 보기"'


def data() -> dict:
    return schedule.get(schedule.INTL)


def _ev(page: str):
    return schedule.intl_event(page)


def years(ev: str, d=None) -> list:
    """그 대회 자료가 있는 해(최신순)."""
    d = data() if d is None else d
    ys = {y for p in [t.get("page", "") for t in d.get("tours") or []] + [m.get("page", "") for m in d.get("matches") or []]
          for k, y in [_ev(p)] if k == ev}
    return sorted(ys, reverse=True)


def year_of(ev: str, pick, d=None) -> str:
    ys = years(ev, d)
    if pick and str(pick) in ys:
        return str(pick)
    return ys[0] if ys else ""


def _sq(ev, year) -> str:
    return f"?season={year}" if year and year != year_of(ev, None) else ""


def _at(m):
    try:
        return datetime.strptime(m["at"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return None


def matches(d, ev, year) -> list:
    keys = ("id", "tab", "bo", "t1", "k1", "t2", "k2", "s1", "s2", "win", "ff")
    return sorted(({**{k: "" for k in keys}, **m} for m in d.get("matches") or [] if _ev(m.get("page")) == (ev, year) and _at(m)),
                  key=lambda m: m["at"])


def kind(m) -> str:
    """경기 탭 이름 → 단계: playin · group · swiss · bracket(더블 엘리미네이션) · ko(단판 토너먼트) · main."""
    tab, page = m.get("tab") or "", m.get("page") or ""
    if page.endswith("/Play-In") or tab.startswith("Play-In"):
        return "playin"
    if tab.startswith("Group"):
        return "group"
    if tab.startswith("Bracket") or tab.startswith("Upper") or tab.startswith("Lower"):
        return "bracket"
    if tab in KO_TABS or tab.startswith("Playoffs") or tab.startswith("Knockout"):
        return "ko"
    if re.fullmatch(r"Round \d+", tab):
        return "swiss"
    return "main"


def _stage_key(ms):
    """결승이 더블 엘리미네이션 브래킷 끝에 붙어 있으면(MSI) 결승도 브래킷 단계로."""
    has_bracket = any(kind(m) == "bracket" for m in ms)
    return lambda m: "bracket" if has_bracket and kind(m) == "ko" else kind(m)


def _winner(m):
    return (m["k1"], m["t1"]) if m.get("win") == "1" else (m["k2"], m["t2"]) if m.get("win") == "2" else None


def _loser(m):
    return (m["k2"], m["t2"]) if m.get("win") == "1" else (m["k1"], m["t1"]) if m.get("win") == "2" else None


def _over(m, now) -> bool:
    return bool(_winner(m)) or (_at(m) and now - _at(m) > timedelta(hours=schedule.LIVE_HOURS))


def stages(d, ev, year, today) -> list:
    """대회 일정 타임라인(경기 순서대로): [{"key", "name", "start", "end", "status", "badge", "ms"}]."""
    ms = matches(d, ev, year)
    key = _stage_key(ms)
    now = datetime.now(timezone.utc)
    order, by = [], {}
    for m in ms:
        k = key(m)
        if k not in by:
            by[k] = []
            order.append(k)
        by[k].append(m)
    out = []
    for k in order:
        days = sorted(_at(m).astimezone(KST).date().isoformat() for m in by[k])
        out.append({"key": k, "name": STAGE_NAME[k], "start": days[0], "end": days[-1], "ms": by[k]})
    if not out:                                   # 경기가 아직 안 올라옴: 리그피디아 대회 목록의 기간만
        for t in d.get("tours") or []:
            if _ev(t.get("page")) == (ev, year):
                sub = t["page"].split("/", 1)[1] if "/" in t["page"] else ""
                out.append({"key": "main", "name": {"Play-In": STAGE_NAME["playin"]}.get(sub, STAGE_NAME["main"]),
                            "start": t.get("start") or "", "end": t.get("end") or "", "ms": []})
    iso = today.isoformat()
    ended = event_over(d, ev, year, today, ms)
    for i, s in enumerate(out):
        # 경기가 다 끝나도 다음 경기가 아직 리그피디아에 안 올라왔을 수 있음(스위스는 라운드마다 추가):
        # 다음 단계 경기가 있거나 대회가 끝났을 때만 '종료'
        if s["ms"] and all(_over(m, now) for m in s["ms"]) and (any(x["ms"] for x in out[i + 1:]) or ended):
            s["status"], s["badge"] = "done", "종료"
        elif (s["start"] and s["start"] <= iso) or any(_winner(m) for m in s["ms"]):
            s["status"], s["badge"] = "now", "● 진행 중"
        else:
            try:
                left = (datetime.strptime(s["start"], "%Y-%m-%d").date() - today).days
                s["status"], s["badge"] = "up", (f"D-{left}" if left > 0 else "예정")
            except ValueError:
                s["status"], s["badge"] = "up", "예정"
    return out


def event_over(d, ev, year, today, ms=None) -> bool:
    """대회가 끝났는지: 결승 결과가 있거나, 리그피디아 대회 기간(끝나는 날)이 지났음."""
    ms = matches(d, ev, year) if ms is None else ms
    if champion(ms):
        return True
    ends = [t.get("end") or "" for t in d.get("tours") or [] if _ev(t.get("page")) == (ev, year)]
    if not ends or not all(ends):
        return False
    try:                                     # (리그피디아 날짜는 현지 기준이라 한국 날짜로는 하루 늦을 수 있어 하루 여유)
        return datetime.strptime(max(ends), "%Y-%m-%d").date() + timedelta(days=1) < today
    except ValueError:
        return False


def _later_teams(ss, i) -> set:
    return {k for s in ss[i + 1:] for m in s["ms"] for k in (m["k1"], m["k2"]) if k}


def _records(ms) -> dict:
    """{팀 키: [승, 패, 이름, 세트 득, 세트 실]} (시리즈 기준)."""
    rec = {}
    for m in ms:
        for i in (1, 2):
            if m[f"k{i}"]:
                rec.setdefault(m[f"k{i}"], [0, 0, m[f"t{i}"], 0, 0])
        w, lo = _winner(m), _loser(m)
        if w and lo:
            rec[w[0]][0] += 1
            rec[lo[0]][1] += 1
            ws, ls = (m["s1"], m["s2"]) if m["win"] == "1" else (m["s2"], m["s1"])
            try:
                rec[w[0]][3] += int(ws or 0); rec[w[0]][4] += int(ls or 0)
                rec[lo[0]][3] += int(ls or 0); rec[lo[0]][4] += int(ws or 0)
            except ValueError:
                pass
    return rec


def _pools(ms) -> list:
    """서로 맞붙은 팀끼리 한 조로(리그피디아 경기에는 조 이름이 없음): [[팀 키, …]] 처음 나온 순서."""
    link = {}
    for m in ms:
        a, b = m["k1"], m["k2"]
        if not a or not b:
            continue
        sa, sb = link.setdefault(a, {a}), link.setdefault(b, {b})
        if sa is not sb:
            sa |= sb
            for x in sb:
                link[x] = sa
    out = []
    for m in ms:
        for k in (m["k1"], m["k2"]):
            if k and not any(k in p for p in out):
                out.append([x for x in sorted(link[k], key=lambda x: next(i for i, mm in enumerate(ms) if x in (mm["k1"], mm["k2"])))])
    return out


def group_block(s, ss, i, d, ev, year, T, V) -> str:
    """group_records: 조별·플레이-인 순위(시리즈 승패), 스위스는 전적 묶음. 진출 = 다음 단계에 나온 팀."""
    later, done = _later_teams(ss, i), s["status"] == "done"
    rec = _records(s["ms"])

    def tone(k):
        return "advance" if k in later else "out" if done else "play"
    label = {"advance": "진출", "out": "탈락", "play": "진행 중"}
    if s["key"] == "swiss":                     # 스위스: 전적이 같은 팀끼리(3승 진출 · 3패 탈락)
        groups = {}
        for k, (w, lo, n, *_) in rec.items():
            t = "advance" if k in later or w >= 3 else "out" if lo >= 3 or done else "play"
            groups.setdefault((w, lo, t), []).append((k, n))
        order = sorted(groups, key=lambda g: ({"advance": 0, "play": 1, "out": 2}[g[2]], -g[0], g[1]))
        rows = "".join(
            f'<li class="wsw {t} twin" {SPOIL}><div class="wsw-h"><b>{w}승 {lo}패</b><span class="wbadge">{label[t]}</span></div><div class="wsw-t">'
            + "".join(f'<span class="wchip">{T.logo(k, n)}{T.short(k, n)}<small>{region_of(d, ev, year, n)}</small></span>' for k, n in groups[(w, lo, t)])
            + "</div></li>" for w, lo, t in order)
        return f'<ul class="wswiss">{rows}</ul>'
    pools = _pools(s["ms"])
    out = ""
    for j, p in enumerate(pools):
        p = sorted(p, key=lambda k: (-rec[k][0], rec[k][1], -(rec[k][3] - rec[k][4])))
        trs = "".join(
            f'<tr class="{tone(k)}"><td class="pl">{n + 1}</td><td>{T.tname(k, rec[k][2])}<small class="wrg">{region_of(d, ev, year, rec[k][2])}</small></td>'
            f'<td class="twin" {SPOIL}>{rec[k][0]}승 {rec[k][1]}패</td><td class="twin" {SPOIL}><span class="wbadge">{label[tone(k)]}</span></td></tr>'
            for n, k in enumerate(p))
        head = f'<h4 class="wround">{chr(65 + j)}조</h4>' if len(pools) > 1 else ""
        out += f'{head}<table class="wgt"><thead><tr><th>순위</th><th>팀</th><th>경기</th><th></th></tr></thead><tbody>{trs}</tbody></table>'
    return out


def _round_order(tab: str):
    if tab in ROUND_NAME:
        return (0, KO_TABS.index(tab) if tab in KO_TABS else 9)
    m = re.search(r"(\d+)$", tab)
    return (1, -int(m.group(1)) if m else 0)


def bracket_block(s, now, T, V) -> str:
    """bracket_rounds: 결승부터 라운드별(더블 엘리미네이션은 마지막 라운드부터) 경기 카드."""
    rounds = {}
    for m in s["ms"]:
        rounds.setdefault(m.get("tab") or "", []).append(m)
    out = ""
    for tab in sorted(rounds, key=_round_order):
        name = ROUND_NAME.get(tab) or V.tab_ko(tab).replace("Bracket ", "브래킷 ")
        out += f'<h4 class="wround">{V.esc(name)}</h4>{V.match_days(rounds[tab], now, T, "", True)}'
    return out


def champion(ms):
    fin = [m for m in ms if m.get("tab") in ("Finals", "Final") and _winner(m)]
    return _winner(fin[-1]) if fin else None


def finish(d, ev, year, today) -> dict:
    """팀 키 → 그 대회 성적(우승·준우승·3위·4강·8강·브래킷 N라운드 탈락·○○ 스테이지 탈락)."""
    ss = stages(d, ev, year, today)
    last, out = {}, {}
    for m in matches(d, ev, year):
        for k in (m["k1"], m["k2"]):
            if k:
                last[k] = m
    for i, s in enumerate(ss):
        later = _later_teams(ss, i)
        for k, m in last.items():
            if m not in s["ms"]:
                continue
            w, lo = _winner(m), _loser(m)
            tab = m.get("tab") or ""
            if tab in ("Finals", "Final") and w:
                out[k] = "우승" if k == w[0] else "준우승"
            elif tab == "Third-Place Match" and w:
                out[k] = "3위" if k == w[0] else "4위"
            elif s["key"] == "ko" and lo and k == lo[0]:                 # 단판 토너먼트: 지면 탈락
                out[k] = {"Semifinals": "4강", "Quarterfinals": "8강"}.get(tab) or V_tab(tab) + " 탈락"
            elif s["key"] == "bracket" and lo and k == lo[0] and s["status"] == "done":   # 더블 엘리미네이션: 끝난 뒤 마지막 패배
                out[k] = V_tab(tab) + " 탈락"
            elif s["key"] in ("playin", "group", "swiss", "main") and s["status"] == "done" and k not in later:
                out[k] = {"playin": "플레이-인 탈락", "group": "그룹 스테이지 탈락", "swiss": "스위스 탈락"}.get(s["key"], "탈락")
    return out


def V_tab(tab: str) -> str:
    from . import views as V
    return V.tab_ko(tab).replace("Bracket ", "브래킷 ")


def timeline(d, ev, year, today, T) -> str:
    ss = stages(d, ev, year, today)
    if not ss:
        return ""
    lis = ""
    for i, s in enumerate(ss):
        summary = ""
        if s["key"] in ("ko", "bracket") and champion(s["ms"]):
            c = champion(s["ms"])
            summary = f'<small class="twin" {SPOIL}>{T.logo(*c)}{T.short(*c)} 우승</small>'
        elif s["key"] in ("playin", "group", "swiss") and s["status"] == "done":
            up = sorted(_later_teams(ss, i) & {k for m in s["ms"] for k in (m["k1"], m["k2"])})
            names = {m[f"k{j}"]: m[f"t{j}"] for m in s["ms"] for j in (1, 2)}
            if up:
                txt = "·".join(T.short(k, names[k]) for k in up) if len(up) <= 4 else f"{len(up)}팀"
                summary = f'<small class="twin" {SPOIL}>다음 단계 진출 {txt}</small>'
        elif s["ms"]:
            bo = sorted({m.get("bo") for m in s["ms"] if m.get("bo")})
            summary = f'<small>{"경기 " + str(len(s["ms"])) + "개"}{" · Bo" + "/".join(bo) if bo else ""}</small>'
        inner = (f'<i class="tdot" aria-hidden="true"></i><span class="tnm"><b>{s["name"]}</b>{summary}</span>'
                 f'<time>{_md(s["start"])} ~ {_md(s["end"])}</time><span class="tst">{s["badge"]}</span>')
        if any(_winner(m) for m in s["ms"]):          # 끝난 경기가 있으면 결과·순위의 그 단계로
            inner = (f'<a class="trow" href="/{ev}/results{_sq(ev, year)}#w-{s["key"]}" title="이 단계 결과 보기">{inner}'
                     f'<i class="tgo" aria-hidden="true">›</i></a>')
        else:
            inner = f'<div class="trow">{inner}<i class="tgo" aria-hidden="true"></i></div>'
        lis += f'<li class="{s["status"]}{" major" if i == len(ss) - 1 else ""}">{inner}</li>'
    return f'<section class="card tours"><h3>{year} {EVENTS[ev]["full"]} 대회 일정</h3><ul>{lis}</ul></section>'


def _md(x: str) -> str:
    return f"{x[5:7]}.{x[8:10]}" if len(x or "") >= 10 else "미정"


def toggle(ev: str, on: str, year: str) -> str:
    sq = _sq(ev, year)

    def a(k, label):
        return f'<a class="{"on" if k == on else ""}" href="/{ev}/{k}{sq}" data-sec="{k}"{" aria-current=page" if k == on else ""}>{label}</a>'
    return f'<nav class="view_tab squad" aria-label="대회 일정 보기">{a("schedule", "일정")}{a("results", "결과·순위")}</nav>'


def _empty(msg: str, btn: str = "") -> str:
    return f'<section class="card sblock st-card"><p class="st-msg">{msg}</p>{f"<div class=st-acts>{btn}</div>" if btn else ""}</section>'


def _foot(d) -> str:
    upd = ""
    try:
        u = datetime.fromisoformat(d["at"]).astimezone(KST)
        upd = f" · {u.month}/{u.day} {u:%H:%M} 갱신"
    except (KeyError, ValueError):
        pass
    return f'<p class="note">일정·결과·로스터 출처 리그피디아{upd} · 경기 앞뒤엔 5분마다, 경기가 없는 기간엔 몇 시간마다 새로 받아요 · 시간은 한국 시간</p>'


def render(ev: str, sec: str, pick=None) -> str:
    """ev: fst · msi · ewc · worlds, sec: '' 소식 · 'schedule' 일정 · 'results' 결과·순위 · 'teams' 진출팀."""
    from . import views as V                     # (views가 메뉴를 그릴 때 이 파일을 불러서 여기서)
    today = datetime.now(KST).date()
    now = datetime.now(timezone.utc)
    d = data()
    E = EVENTS[ev]
    year = year_of(ev, pick, d)
    if not (pick and str(pick) in years(ev, d)) and sec in ("results", "teams"):
        # 다음 해 대회 문서만 먼저 올라온 때: 결과·진출팀은 결과(로스터)가 있는 가장 최근 해
        for y in years(ev, d):
            has = (any(_winner(m) for m in matches(d, ev, y)) if sec == "results"
                   else any(_ev(p) == (ev, y) for p in d.get("rosters") or {}))
            if has:
                year = y
                break
    T = V.SchTeams(d)
    ms = matches(d, ev, year) if year else []
    active = sec or "news"
    title = f'{E["name"]} ' + {"news": "소식", "schedule": "일정", "results": "결과·순위", "teams": "진출팀"}[active]

    def page(main, scripts=()):
        return V.shell(ev, active, title, main, scripts, today, season=year or None)

    if not year:
        msg = ("리그피디아에서 국제전 자료를 받아 오지 못했어요. 잠시 뒤 다시 들어와 주세요." if d.get("error")
               else f'{E["full"]} 대회 일정이 아직 공개되지 않았어요. 리그피디아에 올라오면 바로 보여요.')
        return page((toggle(ev, active, year) if active in ("schedule", "results") else "") + _empty(msg))
    if active == "news":
        return page(news(ev, year, d, V) + _foot(d))
    if active == "teams":
        return page(teams(ev, year, d, T, V, today) + _foot(d))

    if active == "schedule":
        live = [m for m in ms if V._sch_state(m, now) == "live"]
        up = [m for m in ms if V._sch_state(m, now) == "up"]
        blocks = ""
        if live:
            blocks += f'<section class="card sblock live-b"><h3><i class="live-dot" aria-hidden="true"></i>지금 경기 중</h3>{V.match_days(live, now, T, "")}</section>'
        if up:
            blocks += f'<section class="card sblock"><h3>다가오는 경기</h3>{V.match_days(up, now, T, "")}</section>'
        if not blocks:
            done = any(V._sch_state(m, now) == "done" for m in ms)
            if done and event_over(d, ev, year, today, ms):
                msg = f'{year} {E["full"]} 경기가 모두 종료됐어요.'
            elif done:                                 # 대회 중: 다음 라운드 대진이 아직 안 올라옴
                msg = f'다음 경기 대진이 아직 리그피디아에 올라오지 않았어요. 올라오면 바로 보여요.'
            else:
                msg = f'{E["full"]} 경기 일정이 아직 공개되지 않았어요. 리그피디아에 올라오면 바로 보여요.'
            blocks = _empty(msg, f'<a class="btn st-go" href="/{ev}/results{_sq(ev, year)}">결과·순위 보기 →</a>' if done else "")
        return page(toggle(ev, "schedule", year) + timeline(d, ev, year, today, T) + blocks + V.POPUP + _foot(d), ("player.js", "schedule.js"))

    # ── 결과·순위: 우승 → 마지막 단계부터 거꾸로(토너먼트는 bracket_rounds, 조별·스위스·플레이-인은 group_records) ──
    if not any(V._sch_state(m, now) == "done" for m in ms):
        return page(toggle(ev, "results", year) + _empty(f'아직 {year} {E["full"]}에 끝난 경기가 없어요. 경기가 끝나면 여기에 결과가 쌓여요.'))
    out = ""
    c = champion(ms)
    if c:
        fin = [m for m in ms if m.get("tab") in ("Finals", "Final") and _winner(m)][-1]
        lo = _loser(fin)
        ws, ls = (fin["s1"], fin["s2"]) if fin["win"] == "1" else (fin["s2"], fin["s1"])
        out += (f'<section class="card champ sch-champ"><div><small>{year} {E["full"]} 우승</small><b>{T.tname(*c)}</b>'
                f'<p class="sc-hide">결승 {ws}:{ls} · 상대 {T.tname(*lo)} · {_at(fin).astimezone(KST):%Y.%m.%d}</p></div></section>')
    ss = stages(d, ev, year, today)
    for i in range(len(ss) - 1, -1, -1):
        s = ss[i]
        played = [m for m in s["ms"] if V._sch_state(m, now) == "done"]
        if not played:
            continue
        if s["key"] in ("ko", "bracket"):
            body, note = bracket_block({**s, "ms": played}, now, T, V), "마지막 라운드부터 · 경기를 누르면 밴픽·선수 기록이 보여요"
        else:
            body = group_block(s, ss, i, d, ev, year, T, V)
            note = ("시리즈 승패 기준 · 다음 단계에 나온 팀이 진출" if s["key"] != "swiss" else "시리즈 승패 기준 · 3승이면 진출, 3패면 탈락")
            body += f'<details class="smore"><summary>경기 결과 <b class="n">{len(played)}</b>경기 보기</summary>{V.match_days(played, now, T, "", True)}</details>'
        out += f'<section class="card sblock wsec" id="w-{s["key"]}"><h3>{s["name"]}<small>{note}</small></h3><div class="wbody">{body}</div></section>'
    return page(toggle(ev, "results", year) + f'<h2 class="res-title">{year} {E["full"]} 결과</h2>' + out + V.POPUP + _foot(d),
                ("player.js", "schedule.js"))


def rosters(d, ev, year) -> list:
    """그 대회 참가팀(본선 문서 우선, 앞 단계에서 떨어진 팀도 한 번씩): [{"team", "region", "players"}]."""
    rs = d.get("rosters") or {}
    pages = sorted((p for p in rs if _ev(p) == (ev, year)), key=lambda p: p.endswith("/Play-In"))
    seen, out = set(), []
    for p in pages:
        for r in rs[p]:
            if r["team"] not in seen:
                seen.add(r["team"])
                out.append(r)
    return out


def region_of(d, ev, year, name) -> str:
    for r in rosters(d, ev, year):
        if r["team"] == name:
            return _region(r["region"])
    return ""


def _region(code: str) -> str:
    return REGION.get((code or "").upper(), code or "")


def _pname(link: str) -> str:
    """'Doran (Choi Hyeon-jun)' → 'Doran'."""
    return re.sub(r"\s*\(.*\)$", "", link or "").strip()


def teams(ev, year, d, T, V, today) -> str:
    rs = rosters(d, ev, year)
    E = EVENTS[ev]
    if not rs:
        return _empty(f'{E["full"]} 진출팀 로스터가 아직 리그피디아에 올라오지 않았어요. 올라오면 바로 보여요.')
    fin = finish(d, ev, year, today)
    by = {}
    for r in rs:
        by.setdefault(_region(r["region"]), []).append(r)
    regions = sorted(by, key=lambda x: (REGION_ORDER.index(x) if x in REGION_ORDER else 99, x))
    out = f'<h2 class="res-title">{year} {E["full"]} 진출팀 <small>{len(rs)}팀</small></h2>'
    for rg in regions:
        cards = ""
        for r in by[rg]:
            k = schedule.team_id(schedule.INTL, r["team"])
            res = fin.get(k, "")
            cells = "".join(f'<li><span class="pk">{ROLE_KO.get(role, role)}</span><span class="pn">{V.esc(_pname(link))}</span></li>'
                            for role, link in r["players"] if role in ROLE_KO)
            coach = ", ".join(_pname(link) for role, link in r["players"] if role not in ROLE_KO)
            tc = V.team_color(k) if k in V.TEAMS else "var(--line)"
            badge = f'<span class="fill wres twin" {SPOIL}>{res}</span>' if res else ""
            coach_p = f'<p class="wcoach">코치 {V.esc(coach)}</p>' if coach else ""
            cards += (f'<article class="rc wteam" style="--tc:{tc}"><header>{T.logo(k, r["team"])}'
                      f'<div><b>{V.esc(T.short(k, r["team"]))}</b><small>{V.esc(T.full(k, r["team"]))}</small></div>{badge}</header>'
                      f'<ul>{cells}</ul>{coach_p}</article>')
        out += f'<section class="wreg"><h3 class="wreg-h">{V.esc(rg)} <small>{len(by[rg])}팀</small></h3><div class="rgrid wgrid">{cards}</div></section>'
    return out + '<p class="src">로스터는 리그피디아 대회 로스터 기준(교체 선수 포함) · 시드는 리그피디아에 따로 없어 권역만 표시 · 성적은 스포 방지 중이면 흐리게</p>'


def news(ev, year, d, V) -> str:
    """그 대회 기간(앞뒤 2주) 소식 중 그 대회 이야기."""
    E = EVENTS[ev]
    tours = [t for t in d.get("tours") or [] if _ev(t.get("page")) == (ev, year)]
    starts = sorted(t["start"] for t in tours if t.get("start"))
    ends = sorted(t["end"] for t in tours if t.get("end"))
    try:
        a = (datetime.strptime(starts[0], "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")
        b = (datetime.strptime(ends[-1], "%Y-%m-%d") + timedelta(days=14)).strftime("%Y-%m-%d")
    except (IndexError, ValueError):
        a, b = f"{year}-01-01", f"{year}-12-31"
    words = E["news"]
    sql = ("SELECT title, url, outlet, published FROM items WHERE source='news' AND published >= ? AND published < ? AND ("
           + " OR ".join("title LIKE ?" for _ in words) + ") ORDER BY published DESC LIMIT 400")
    with db() as c:
        rows = c.execute(sql, [a, b + "T23:59:59"] + [f"%{w}%" for w in words]).fetchall()
    seen, lis, last = set(), [], None
    for r in rows:
        t = r["title"]
        key = re.sub(r"\W+", "", t)[:40]
        # 짧은 영문 약칭(MSI·EWC·FST)은 단어로 있을 때만
        if key in seen or not is_lol_news(t) or not any(re.search(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", t) for w in words):
            continue
        seen.add(key)
        pub = datetime.fromisoformat(r["published"])
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        day = pub.astimezone(KST).date()
        if day != last:
            lis.append(f'<li class="wday">{day.month}월 {day.day}일 ({V.WEEKDAYS[day.weekday()]})</li>')
            last = day
        lis.append(f'<li><a href="{V.esc(r["url"])}" target="_blank" rel="noopener">{V.esc(t)}</a>'
                   f'<small>{V.esc(r["outlet"] or "")} · {pub.astimezone(KST):%H:%M}</small></li>')
        if len(seen) >= 120:
            break
    if not lis:
        return _empty(f'{year} {E["full"]} 소식이 아직 없어요. 대회가 다가오면 여기에 모여요.',
                      f'<a class="btn st-go" href="/{ev}/schedule{_sq(ev, year)}">대회 일정 보기 →</a>')
    return (f'<section class="card sblock wnews"><h3>{year} {E["full"]} 소식<small>{" · ".join(words[:2])} 기사 · 대회 앞뒤 2주</small></h3>'
            f'<ul>{"".join(lis)}</ul></section>')
