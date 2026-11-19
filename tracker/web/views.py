"""화면 HTML 만들기: 공통 껍데기, 소식·로스터·이적(FA)·일정, 준비 중 리그."""
import html
import re
import json
import urllib.parse
from datetime import datetime, timedelta, timezone

from ..cargo import RATE_MSG, is_rate_limit
from ..classify import article_kind, is_minor_wiki, news_teams, wiki_ko
from ..cluster import group as cluster_group
from ..rumor import rumors
from ..config import (AUTO_MINUTES, DEFAULT_LEAGUE, KST, LEAGUES, NEW_HOURS, SITE_DESC, SITE_NAME, TEAM_COLORS,
                      TEAMS)
from ..core import STATUS, STATUS_LOCK, WEEKDAYS, db, kst_day_start_utc, norm_title, parse_day, rel_time
from ..fa import FA_ROLES, fa_since
from ..filters import is_lol_news, ko_nicks
from ..insight import is_spoiler, overseas_tag, search_terms, trust
from ..archive import archive_years, current_season
from .. import archive, schedule, teamlogos
from ..logos import TEAM_LOGOS

# 제목 옆 버섯: 그림 대신 기기 기본 버섯 이모지(🍄). '조회 중' 화면에서도 같은 이모지가 뛰어감
SHROOM_SVG = ('<button type="button" class="teemo" id="teemo" title="유독성 함정 배치 완료!" aria-label="버섯">'
              '<img class="mk" src="/img/shroom.png" alt="" width="34" height="34" '
              """onerror="this.parentNode.classList.add('noimg')">"""
              '<span class="mk emo" aria-hidden="true">🍄</span></button>')
# 메신저·SNS 링크 미리보기(카톡·디코·X 등). 그림은 tracker/og.jpg(1200×630)
OG_TITLE = "🍄 티모의 버섯농장 — LCK 스토브리그·로스터·이적 현황"
OG_DESC = "LoL 리그별 오피셜·루머·로스터·이동 보드·로스터 짜기를 한눈에 확인하세요!"
RIOT_NOTE = ("'티모의 버섯농장'은 Riot Games가 보증하지 않으며, Riot Games 또는 리그 오브 레전드 제작·관리에 공식적으로 관여하는 "
             "당사자의 견해나 의견을 반영하지 않습니다. 리그 오브 레전드 및 Riot Games는 Riot Games, Inc.의 상표 또는 등록 상표입니다.")
FONT_CSS = "https://cdn.jsdelivr.net/npm/pretendard-gov@1.3.9/dist/web/variable/pretendardvariable-gov-dynamic-subset.css"
STATIC_VER = "1"           # server가 정적 파일 내용으로 바꿔 넣음(캐시 무효화)
FA_POS = {"Top": "탑", "Jungle": "정글", "Mid": "미드", "Bot": "원딜", "Support": "서폿",
          "Head Coach": "감독", "Coach": "코치", "Analyst": "분석"}
FA_ST = {"move": ("이적 확정", "s-move"), "stay": ("잔류", "s-stay"), "fa": ("미정", "s-fa")}
KIND = {"official": ("오피셜", "k-official"), "rumor": ("단독·유력", "k-rumor"),
        "view": ("전망·분석", "k-view"), "edit": ("편집", "k-edit")}
SECTIONS = [("news", "", "소식"), ("roster", "/roster", "로스터"), ("fa", "/fa", "이적·FA"), ("builder", "/builder", "로스터 짜기"),
            ("schedule", "/schedule", "일정·결과"), ("game", "/game", "🍄 미니게임")]
esc = html.escape


# ── 작은 도우미 ─────────────────────────────────────────────────────────
def team_short(k: str) -> str:
    return TEAMS.get(k, {}).get("short") or k.upper()


def team_name(k: str) -> str:
    return TEAMS.get(k, {}).get("name", k)


def logo_src(k: str) -> str:
    return TEAMS.get(k, {}).get("logo") or (f"/logo/{k}.png?v={STATIC_VER}" if k in TEAM_LOGOS else "")


def team_logo(k: str, cls: str = "logo") -> str:
    src = logo_src(k)
    if src:
        return f'<img class="{cls}" src="{esc(src)}" alt="" width="20" height="20" loading="lazy">'
    return f'<span class="logo txt" aria-hidden="true">{esc(team_short(k)[:1])}</span>'


def team_color(k: str) -> str:
    return TEAMS.get(k, {}).get("color") or TEAM_COLORS.get(k, "#888888")


def team_keys():
    """실제 팀(공통 묶음 'lck' 제외) 순서."""
    return [k for k in TEAMS if k != "lck" and TEAMS[k].get("wiki")]


def in_season(today) -> bool:
    """스토브리그 기간(11~12월)에는 이적·FA 메뉴에 표시."""
    return today.month in (11, 12)


def friendly(msg: str) -> str:
    if msg.startswith("팀 "):          # 관리 작업이 남긴 안내(팀 이름 바뀜 등)는 그대로
        return msg.split(":")[0]
    low = msg.lower()
    if is_rate_limit(msg):
        return RATE_MSG
    if "429" in low:
        return "요청이 많아 잠시 막혔어요"
    if "timed out" in low or "timeout" in low:
        return "상대 서버가 응답하지 않았어요"
    if "http error 5" in low:
        return "상대 서버에 일시적인 문제가 있었어요"
    return "가져오지 못했어요"


def status_parts(today):
    """(머리줄 문구, 아래쪽 실패 안내)."""
    with STATUS_LOCK:
        sts = list(STATUS.items())
    if not sts:
        return '<span>첫 수집 중…</span>', ""
    last = max(st["at"] for _, st in sts).astimezone(KST)
    when = f"{last:%H:%M}" if last.date() == today else f"{last.month}/{last.day} {last:%H:%M}"
    head = f'<span><i class="dot" aria-hidden="true"></i>마지막 업데이트 {when}</span>'
    fails = [(k, s_, st) for (k, s_), st in sorted(sts) if not st["ok"]]
    if not fails:
        return head, ""
    lis = "".join(
        f'<li><b>{"FA 현황" if k == "fa" else "구글 뉴스" if k == "google" else esc(team_name(k))} · {"뉴스" if s_ == "news" else "팀 이름" if s_ == "team" else "리그피디아"}</b>'
        f' — {esc(friendly(st["msg"]))}<br><small>{esc(st["msg"])}</small></li>' for k, s_, st in fails)
    foot = (f'<details class="fail"><summary>일부 출처 시야가 잠시 가려졌어요 ({len(fails)}) · 잠시 후 다시 탐지합니다</summary>'
            f'<ul>{lis}</ul></details>')
    return head, foot


ACT = f"""<div class="act">
<button id="go" class="btn primary" type="button"><span class="spin" aria-hidden="true"></span><span class="lbl">조회</span></button>
<label class="chk auto"><input type="checkbox" id="auto"><span><i class="live" aria-hidden="true"></i>{AUTO_MINUTES}분마다 자동 갱신</span></label>
<span id="next" class="next" aria-live="off"></span>
</div>
<p id="msg" class="msg" role="status" aria-live="polite"></p>
"""

POPUP = """<div class="dim" id="dim" aria-hidden="true">
<div class="pop" role="dialog" aria-modal="true" aria-labelledby="pn">
<div class="grab" aria-hidden="true"></div>
<button class="x" type="button" aria-label="닫기"></button>
<div id="pbody"></div>
</div>
</div>
"""


SEC_PATH = {"news": "", "roster": "/roster", "fa": "/fa", "schedule": "/schedule", "builder": "/builder", "game": "/game"}


def shell(league: str, active: str, title: str, main: str, scripts, today, scope: str = "", extra_attr: str = "",
          season=None, og=None) -> str:
    """공통 껍데기: 머리줄(사이트 이름·업데이트), 리그 선택, 메뉴, 본문, 아래쪽 안내, 스크립트."""
    head, foot_fail = status_parts(today)
    # 1층: 리그 고르기(드롭다운) · 2층: 그 리그의 4개 탭. 미니게임은 오른쪽 위 도구 칸
    cur = LEAGUES.get(league, LEAGUES[DEFAULT_LEAGUE])
    lg_items = "".join(
        (f'<li><a class="{"on" if k == league else ""}" href="/{k}"{" aria-current=page" if k == league else ""}>'
         f'{esc(v["name"])}<small>{esc(v["sub"])}</small></a></li>' if v["enabled"] else
         f'<li><a class="soon{" on" if k == league else ""}" href="/{k}/schedule">{esc(v["name"])}<small>{esc(v["sub"])} · 일정·결과</small></a></li>' if v.get("wiki") else
         f'<li><a class="soon" href="/{k}">{esc(v["name"])}<small>{esc(v["sub"])} · 곧 추가</small></a></li>')
        for k, v in LEAGUES.items())
    lgsel = (f'<details class="lgsel"><summary aria-label="리그 고르기"><b>{esc(cur["name"])}</b><i aria-hidden="true">▾</i></summary>'
             f'<ul>{lg_items}</ul></details>')
    stove = in_season(today)
    squad = "fa" if stove else "roster"                       # 스토브리그엔 이적·FA부터
    news_t = ("news", "", "🏠 소식", ("news",))
    sched_t = ("schedule", "/schedule", "📅 일정·결과", ("schedule",))
    squad_t = (squad, "/" + squad, "👥 로스터·이적", ("roster", "fa"))
    build_t = ("builder", "/builder", "🛠️ 로스터 짜기", ("builder",))
    # 스토브리그(11~12월): 소식 → 로스터·이적 → 로스터 짜기 → 일정 / 정규 시즌: 소식 → 일정 → 로스터·이적 → 로스터 짜기
    tab_defs = [news_t, squad_t, build_t, sched_t] if stove else [news_t, sched_t, squad_t, build_t]
    hot = {"roster": stove, "fa": stove, "builder": stove} if not season else {}
    sq = f"?season={season}" if season else ""
    # 시즌 고르기: 지금 시즌 + 지난 시즌 기록
    now_y = current_season(today)
    now_label = f"{now_y} 스토브리그" if stove else f"{now_y} 시즌"
    here = SEC_PATH.get(active, "")
    s_items = (f'<li><a class="{"" if season else "on"}" href="/{league}{here}">{now_label}<small>지금</small></a></li>'
               + "".join(f'<li><a class="{"on" if season == y else ""}" href="/{league}{here}?season={y}">{y} 시즌<small>기록</small></a></li>'
                         for y in archive_years()))
    ssel = "" if not cur["enabled"] else (f'<details class="lgsel ssel"><summary aria-label="시즌 고르기"><b>{season or now_y}</b><i aria-hidden="true">▾</i></summary>'
            f'<ul>{s_items}</ul></details>')
    bar = (f'<div class="archive-bar">📜 지금 <b>{season} 시즌</b> 기록을 보고 있어요. '
           f'<a href="/{league}{here}">{now_label}(최신)으로 돌아가기 →</a></div>' if season else "")
    tabs = "".join(
        f'<a class="{"on" if active in keys else ""}" href="/{league}{path}{sq}" data-sec="{key}"'
        f'{" aria-current=page" if active in keys else ""}>{label}'
        f'{"<span class=season>HOT</span>" if hot.get(key) else ""}</a>'
        for key, path, label, keys in tab_defs)
    full_title = f"{title} · {SITE_NAME}" if title else SITE_NAME
    js = "".join(f'<script src="/static/{s}?v={STATIC_VER}"></script>' for s in ("common.js",) + tuple(scripts) + ("chat.js",))
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<script>try{{document.documentElement.dataset.theme=localStorage.getItem("theme")||"dark";if(localStorage.getItem("spoiler")==="1")document.documentElement.dataset.spoiler="on"}}catch(e){{document.documentElement.dataset.theme="dark"}}</script>
<title>{esc(full_title)}</title>
<meta name="description" content="{esc(SITE_DESC)}">
<meta name="theme-color" content="#5d2e8c">
<link rel="icon" href="/img/shroom.png">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{esc(SITE_NAME)}">
<meta property="og:title" content="{esc((og or {}).get("title") or OG_TITLE)}">
<meta property="og:description" content="{esc((og or {}).get("desc") or OG_DESC)}">
<meta property="og:image" content="{{{{ORIGIN}}}}/img/og.jpg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:url" content="{{{{ORIGIN}}}}{{{{PATH}}}}">
<meta property="og:locale" content="ko_KR">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="preload" as="style" href="{FONT_CSS}" onload="this.onload=null;this.rel='stylesheet'">
<noscript><link rel="stylesheet" href="{FONT_CSS}"></noscript>
<link rel="stylesheet" href="/static/base.css?v={STATIC_VER}">
{adsense_head()}</head><body data-league="{league}" data-sec="{active}" data-auto="{AUTO_MINUTES}" data-scope="{scope}"{extra_attr}>
<header class="header"><div class="in">
<h1 class="brand">{SHROOM_SVG}<a class="home" href="/{DEFAULT_LEAGUE}" title="메인 화면으로">{esc(SITE_NAME)}<small>협곡의 시야를 장악하듯, LoL 이스포츠 소식·로스터·이적을 한눈에</small></a></h1>
<div class="stat">{head}<span class="tools"><button type="button" class="tbtn" id="spo" aria-pressed="false" title="경기 결과·루머 핵심을 흐리게 가려요">🎯 스포 방지</button><button type="button" class="tbtn" id="thm" title="화면 밝기 바꾸기">🌙</button><a class="tbtn{" on" if active == "game" else ""}" href="/{league}/game">🍄 미니게임</a></span></div>
</div>
<div class="subnav">{lgsel}{ssel}<nav class="top_tab" aria-label="메뉴">{tabs}</nav></div>
</header>
{bar}
<main class="wide">
{main}
<div class="foot">{foot_fail}<p>시간은 모두 한국 시간(KST) · 팀 로고·로스터·FA 출처 Leaguepedia</p>{support_button()}{aff_note()}{policy_links()}<p class="riot">{esc(RIOT_NOTE)}</p></div>
</main>
{policy_dialogs() if active != "policy" else ""}
{js}
</body></html>"""


def fa_counts():
    with db() as c:
        rows = c.execute("SELECT status, COUNT(*) n FROM fa GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


def roster_rows():
    with db() as c:
        return c.execute("SELECT * FROM roster WHERE league='lck'").fetchall()


ROSTER_SLOTS = ("Top", "Jungle", "Mid", "Bot", "Support", "Head Coach")


def roster_card(k: str, rows, extra_cls: str = "") -> str:
    by = {}
    for r in rows:
        if r["team"] == k:
            by.setdefault(r["role"], []).append(r)
    filled = sum(1 for p in FA_ROLES if by.get(p))
    cells = []
    for p in ROSTER_SLOTS:
        rs = by.get(p, [])
        if not rs:
            cells.append(f'<li class="vac"><span class="pk">{FA_POS[p]}</span><span class="pn">미정</span></li>')
            continue
        def pn(r, cls="pn"):
            until = f'~{r["until"][:7].replace("-", ".")}' if r["until"] else ""
            return (f'<span class="{cls}" role="button" tabindex="0" title="선수 프로필 보기" data-page="{esc(r["page"])}" data-nick="{esc(r["nick"])}"'
                    f' data-real="{esc(r["real"] or "")}" data-pos="{FA_POS[p]}" data-team="{k}" data-until="{esc(until)}">{esc(r["nick"])}</span>')
        r = rs[0]
        IN_S = '<i class="in s">영입</i>'
        subs = "".join(f'<span class="subl">{pn(x, "pn sub")}{IN_S if x["joined"] else ""}</span>'
                       for x in rs[1:])      # 같은 포지션 선수가 더 있으면(후보 등) 이름을 모두 보여 줌
        cells.append(f'<li><span class="pk">{FA_POS[p]}</span>{pn(r)}{subs}'
                     f'{"<i class=in>영입</i>" if r["joined"] else ""}</li>')
    return (f'<article class="rc{extra_cls}" data-team="{k}" style="--tc:{team_color(k)}"><header>{team_logo(k, "logo big")}'
            f'<div><b>{esc(team_short(k))}</b><small>{esc(team_name(k))}</small></div><span class="fill">{filled}/5</span></header>'
            f'<ul>{"".join(cells)}</ul></article>')


def narrow_roster(league: str, team: str) -> str:
    """휴대폰처럼 좁은 화면: 오른쪽 요약이 없어서, 팀을 고르면 그 팀 로스터를 목록 위에 접어서 보여 줌."""
    if team not in team_keys():
        return ""
    return (f'<details class="card rs-narrow" open><summary><span>{team_logo(team)} {esc(team_short(team))} 로스터</span>'
            f'<a href="/{league}/roster">전체 로스터 →</a><i aria-hidden="true">▾</i></summary>{roster_card(team, roster_rows())}</details>')


def stove_strip(league: str) -> str:
    """소식 화면 맨 위(휴대폰): 스토브리그 진행 숫자. PC는 오른쪽 요약에 같은 숫자가 있음."""
    if not in_season(datetime.now(KST).date()):
        return ""
    cnt = fa_counts()
    return (f'<nav class="stove" aria-label="스토브리그 현황"><b>🍄 스토브리그</b>'
            f'<a class="m" href="/{league}/fa?s=move"><em>{cnt.get("move", 0)}</em>이적 확정</a>'
            f'<a href="/{league}/fa?s=stay"><em>{cnt.get("stay", 0)}</em>잔류</a>'
            f'<a href="/{league}/fa?s=fa"><em>{cnt.get("fa", 0)}</em>미정</a></nav>')


def rail(league: str, team: str) -> str:
    cnt = fa_counts()
    box = (f'<section class="card rail-stove"><h3>스토브리그 현황 <a href="/{league}/fa">이적·FA →</a></h3>'
           f'<div class="mini"><a class="m" href="/{league}/fa?s=move"><b>{cnt.get("move", 0)}</b>이적 확정</a>'
           f'<a href="/{league}/fa?s=stay"><b>{cnt.get("stay", 0)}</b>잔류</a>'
           f'<a href="/{league}/fa?s=fa"><b>{cnt.get("fa", 0)}</b>미정</a></div></section>')
    if team in team_keys():
        box += team_profile(team)
        card = roster_card(team, roster_rows())
        box += (f'<section class="card"><h3><span>{team_logo(team)} {esc(team_short(team))} 로스터</span>'
                f'<a href="/{league}/roster">전체 로스터 →</a></h3>{card}</section>')
    else:
        box += ('<section class="card"><h3>팀 로스터</h3>'
                '<p class="hint">위에서 팀 로고를 선택하면 최신 확정 로스터가 펼쳐집니다.</p></section>')
    box += affiliate_card()
    return f'<aside class="rail" aria-label="요약">{box}</aside>'


# ── 소식 ────────────────────────────────────────────────────────────────
def _pub(r):
    pub = datetime.fromisoformat(r["published"])
    return pub if pub.tzinfo else pub.replace(tzinfo=timezone.utc)


def _ts(r):
    return int(_pub(r).timestamp() * 1000)


def render_news(league: str, team: str, src: str, hot: int, frm: str = "", to: str = "", q: str = "") -> str:
    """hot: 0=전체(기본), 1=오피셜, 2=오피셜+루머. team: '' = 지정 없음(내 팀이 있으면 화면에서 그 팀으로)."""
    d_from, d_to = parse_day(frm), parse_day(to)
    if d_from and d_to and d_from > d_to:
        d_from, d_to = d_to, d_from          # 순서를 거꾸로 넣어도 동작
    frm = d_from.isoformat() if d_from else ""
    to = d_to.isoformat() if d_to else ""
    sql, args = "SELECT * FROM items WHERE 1=1", []
    if d_from:
        sql += " AND published >= ?"; args.append(kst_day_start_utc(d_from))
    if d_to:
        sql += " AND published < ?"; args.append(kst_day_start_utc(d_to + timedelta(days=1)))
    if team in TEAMS and team != "lck" and TEAMS[team].get("aliases"):
        sql += " AND (team=? OR source='news')"; args.append(team)   # 뉴스는 아래에서 제목으로 거름
    elif team in TEAMS:
        sql += " AND team=?"; args.append(team)
    if src in ("wiki", "news"):
        sql += " AND source=?"; args.append(src)
    q = " ".join((q or "").split())[:30]
    terms = search_terms(q)
    if terms:                                            # 검색: 선수 닉네임·한글 닉네임·본명을 함께 찾음
        sql += " AND (" + " OR ".join("title LIKE ?" for _ in terms) + ")"
        args += [f"%{t}%" for t in terms]
    sql += " ORDER BY published DESC LIMIT 1000"
    with db() as c:
        rows = c.execute(sql, args).fetchall()

    groups, order = {}, []   # 같은 기사 합치기: 중복 키 -> [대표 행, 팀 키 목록]
    for r in rows:
        # 같은 제목이면 한 줄로(언론사 이름 표기가 달라도: '엑스포츠뉴스' / 'www.xportsnews.com')
        key = ("news", norm_title(r["title"])) if r["source"] == "news" else ("wiki", r["id"])
        if key in groups:
            if r["team"] not in groups[key][1]:
                groups[key][1].append(r["team"])
            continue
        groups[key] = [r, [r["team"]]]
        order.append(key)

    items = []
    for key in order:
        r, teams = groups[key]
        if r["source"] == "wiki" and is_minor_wiki(r["title"]):
            continue                                    # 표 정리·오타 같은 사소한 편집은 숨김
        if r["source"] == "news":
            if not is_lol_news(r["title"]):
                continue                                # 다른 종목·다른 게임 기사(예전에 모인 것 포함)는 숨김
            teams = news_teams(r["title"], teams)       # 팀 표시는 제목 기준
            if team in TEAMS and team != "lck" and team not in teams:
                continue
        kind = article_kind(r["title"], r["source"])
        if hot == 1 and kind != "official":
            continue
        if hot == 2 and kind not in ("official", "rumor"):
            continue
        items.append((r, kind, teams))

    base = f"/{league}"

    def url(t=team, s=src, h=hot, f=frm, e=to, k=q):
        # 기본값(지정 없음·모든 출처·전체 보기·전체 기간)은 주소에서 뺌 → 짧은 주소
        q = {"q": k} if k else {}
        if t in TEAMS or t == "all":
            q["team"] = t
        if s in ("news", "wiki"):
            q["src"] = s
        if h:                                   # '전체'(0)가 기본
            q["hot"] = h
        if f:
            q["from"] = f
        if e:
            q["to"] = e
        return base + ("?" + urllib.parse.urlencode(q) if q else "")

    def opt(label, value, sel):
        return f'<option value="{esc(value)}"{" selected" if sel else ""}>{label}</option>'

    today = datetime.now(KST).date()
    yday = today - timedelta(days=1)
    presets = [("전체 기간", "", ""),
               ("오늘", today.isoformat(), today.isoformat()),
               ("어제", yday.isoformat(), yday.isoformat()),
               ("최근 3일", (today - timedelta(days=2)).isoformat(), today.isoformat()),
               ("최근 7일", (today - timedelta(days=6)).isoformat(), today.isoformat())]
    custom = not any((frm, to) == (f, e) for _, f, e in presets)
    period = "".join(opt(lbl, url(f=f, e=e), (frm, to) == (f, e)) for lbl, f, e in presets)
    period += opt("직접 선택…", "custom", custom)
    hidden = "".join(f'<input type="hidden" name="{k}" value="{esc(str(v))}">'
                     for k, v in (("team", team if (team in TEAMS or team == "all") else ""),
                                  ("src", src if src in ("news", "wiki") else ""),
                                  ("hot", hot or "")) if v != "")
    period_form = (f'<form id="dates" class="dates{" show" if custom else ""}" method="get" action="{base}">{hidden}'
                   f'<input type="date" name="from" value="{frm}" max="{today}" aria-label="시작일">'
                   f'<span>~</span><input type="date" name="to" value="{to}" max="{today}" aria-label="종료일">'
                   f'<button class="btn" type="submit">적용</button></form>')
    src_on = src if src in ("news", "wiki") else "all"
    srcs = (opt("모든 출처", url(s="all"), src_on == "all") + opt("뉴스만", url(s="news"), src_on == "news")
            + opt("리그피디아만", url(s="wiki"), src_on == "wiki"))
    nfilter = (1 if (frm or to) else 0) + (1 if src_on != "all" else 0)

    def seg(label, h):
        on = h == hot
        return f'<a class="{"on" if on else ""}" href="{esc(url(h=h))}"{" aria-current=page" if on else ""}>{label}</a>'
    view = seg("전체", 0) + seg("오피셜", 1) + seg("+루머", 2)      # 기본(전체)을 맨 앞에

    def team_tab(k, label=None):
        on = team == k
        return (f'<a class="{"on" if on else ""}" href="{esc(url(t=k))}" data-t="{k}" title="{esc(team_name(k))}"'
                f'{" aria-current=page" if on else ""}>{team_logo(k)}<span>{esc(label or team_short(k))}</span></a>')
    all_on = team not in TEAMS
    nav = (f'<a class="{"on" if all_on else ""}" href="{esc(url(t="all"))}" data-t="all"{" aria-current=page" if all_on else ""}>전체</a>'
           + "".join(team_tab(k) for k in sorted(TEAMS, key=lambda k: k != "lck")))   # 'LCK 공통'을 '전체' 바로 뒤로

    now = datetime.now(timezone.utc)
    lis, last_day = [], None
    for r, kind, teams, rest in cluster_group(items):
        pub = datetime.fromisoformat(r["published"])
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        kst = pub.astimezone(KST)
        day = kst.date()
        if day != last_day:
            mark = ('<span class="st today">오늘</span>' if day == today else
                    '<span class="st yday">어제</span>' if day == yday else "")
            lis.append(f'<li class="day">{day.month}월 {day.day}일 ({WEEKDAYS[day.weekday()]}){mark}</li>')
            last_day = day
        new = now - pub < timedelta(hours=NEW_HOURS)
        shown = [k for k in teams if not (k == "lck" and len(teams) > 1)]   # 'LCK 공통'은 다른 팀이 있으면 생략
        badges = []
        lv = trust(r["title"], kind)
        kb = ""
        if kind in KIND and not (hot == 1 and kind == "official"):        # '오피셜' 보기에선 모두 오피셜이라 생략
            label = "루머" if kind == "rumor" and lv == 1 else KIND[kind][0]
            kb = f'<span class="kb {KIND[kind][1]}">{label}</span>'   # 1행: 성격 배지 + 제목 / 2행: 팀·매체·시간
        if lv:
            tip = {3: "구단 공식 발표", 2: "유력 보도(단독·유력)", 1: "루머·썰"}[lv]
            badges.append(f'<span class="trust lv{lv}" title="신뢰도: {tip}" aria-label="신뢰도 {lv}단계: {tip}">🍄</span>')
        if new:
            badges.append('<span class="st nw">🍄 NEW</span>')
        tms = "".join(f'<span class="tm" title="{esc(team_name(k))}">{team_logo(k)}{esc(team_short(k))}</span>' for k in shown)
        srcb = '<span class="st wiki">리그피디아</span>' if r["source"] == "wiki" else ""
        outlet = esc(r["outlet"] or "")
        title = r["title"]
        ko = wiki_ko(title) if r["source"] == "wiki" else None
        tit = (f'{esc(ko)}<span class="orig">{esc(title)}</span>' if ko else esc(title))
        ovs = overseas_tag(title, team_short) if r["source"] == "news" else ""
        if ovs:
            tit += f'<span class="ovs">{esc(ovs)}</span>'
        cls = f'item kd-{kind} lv-{lv}' + (" new" if new else "") + (" grp" if rest else "") + (" spo" if is_spoiler(title) else "")
        ts = int(pub.timestamp() * 1000)
        if len(rest) >= 3:                               # 같은 소식 기사가 4건 이상 = 오늘 뜨거운 이슈
            badges.append(f'<span class="st hotb">🔥 핫이슈 {len(rest) + 1}건</span>')
        more = ""
        if rest:
            subs = "".join(
                f'<li><a href="{esc(m["url"])}" target="_blank" rel="noopener"><span class="t">{esc(m["title"])}</span>'
                f'<small>{esc(m["outlet"] or "")} · <span class="rel" data-ts="{_ts(m)}">{rel_time(_pub(m), now)}</span></small></a></li>'
                for m, _, _ in rest)
            more = (f'<div class="sib"><button type="button" class="sib-btn" aria-expanded="false">'
                    f'관련 보도 {len(rest)}건 더보기<i aria-hidden="true">▾</i></button><ul class="sib-list" hidden>{subs}</ul></div>')
        lis.append(
            f'<li class="{cls}" data-id="{esc(r["id"])}" data-ts="{ts}"><a class="row" href="{esc(r["url"])}" target="_blank" rel="noopener">'
            f'<p class="tit">{kb}{tit}</p><div class="meta">{"".join(badges)}{tms}{srcb}'
            f'{f"<span>{outlet}</span>" if outlet else ""}'
            f'<time class="tw" datetime="{kst.isoformat()}" title="{kst:%Y-%m-%d %H:%M} KST">{kst:%H:%M}</time>'
            f'<span class="rel" data-ts="{ts}">{rel_time(pub, now)}</span></div></a>{more}</li>')

    def go_link(label, **kw):
        return f'<a href="{esc(url(**kw))}">{label}</a>'
    if lis:
        body = "".join(lis)
    else:
        if frm or to:
            text = "이 기간에는 소식이 없어요. 기간을 넓히거나 '전체 기간'을 눌러 보세요"
            gos = [go_link("전체 기간 보기", f="", e="")] + ([go_link("전체 소식 보기", h=0)] if hot else [])
        elif hot:
            text = "이 보기에 맞는 소식이 아직 없어요. '전체'에서 모든 소식을 볼 수 있어요"
            gos = [go_link("전체 소식 보기", h=0)] + ([go_link("+루머 보기", h=2)] if hot == 1 else [])
        else:
            text = "아직 모인 소식이 없어요. [조회]를 눌러 지금 가져와 보세요"
            gos = []
        if team in TEAMS:
            gos.append(go_link("전체 팀 보기", t="all"))
        if src_on != "all":
            gos.append(go_link("모든 출처 보기", s="all"))
        body = f'<li class="empty"><p>{text}</p>' + (f'<div class="go">{"".join(gos)}</div>' if gos else "") + "</li>"

    main = f"""<div class="layout"><div>
<section class="card fbar{" open" if custom else ""}" id="fbar" aria-label="보기와 필터">
<form class="srch" method="get" action="{base}" role="search">{"".join(f'<input type="hidden" name="{k}" value="{esc(str(v))}">' for k, v in (("team", team if team in TEAMS else ""),) if v != "")}
<input type="search" name="q" value="{esc(q)}" placeholder="선수·키워드 검색 (예: 커즈, 기인)" aria-label="선수·키워드 검색" enterkeyhint="search">
<button class="btn" type="submit">검색</button>{f'<a class="x" href="{esc(url(k=""))}" aria-label="검색 지우기">×</a>' if q else ""}</form>
{f'<p class="srch-head">‘{esc(q)}’ 검색 결과 {len(items)}건' + (f' · {esc(", ".join(t for t in terms if t != q))}도 함께 찾았어요' if len(terms) > 1 else "") + '</p>' if q else ""}
<div class="top"><nav class="view_tab" aria-label="보기">{view}</nav>
<button class="fbtn" type="button" id="fbtn" aria-expanded="{"true" if custom else "false"}" aria-controls="fbody">필터{f"<i>{nfilter}</i>" if nfilter else ""}</button></div>
<div class="fbody" id="fbody">{ACT}<div class="filter_bar">
<label class="fld"><span>기간</span><select id="period">{period}</select></label>
<label class="fld"><span>출처</span><select id="src">{srcs}</select></label>
{period_form}
</div></div>
</section>
{league_guide(league) if not q else ""}{team_profile(team, "tp-narrow") if team in team_keys() else ""}{narrow_roster(league, team)}{stove_strip(league)}
<p class="myteam" id="myteam" aria-live="polite"></p>
<section class="card">
<div class="tabs-wrap"><nav class="tabs" id="tabs" aria-label="팀">{nav}</nav></div>
<ul class="list">{body}</ul>
</section>
{affiliate_card("aff-narrow")}
</div>{rail(league, team)}</div>
{POPUP}"""
    return shell(league, "news", "", main, ("news.js", "player.js"), today, extra_attr=' data-teamable="1"')


# ── 이적·FA ─────────────────────────────────────────────────────────────
def fa_row_html(r, rm=None) -> str:
    """rm: 미정인 선수의 뉴스 기반 '유력'·'발표' 정보(rumor.py). 공식 상태는 그대로 두고 덧붙여 보여 줌."""
    def tm(k):
        return f'<span class="tm" title="{esc(team_name(k))}">{team_logo(k)}{esc(team_short(k))}</span>'
    pos = FA_POS.get(r["role"], r["role"])
    coach = r["role"] not in FA_ROLES
    if r["status"] == "stay":
        mv = f'{tm(r["team_from"])}<span class="und">잔류</span>'
    else:
        dest = (tm(r["team_to"]) if r["team_to"] else
                f'<span class="ext">{esc(r["team_to_name"])}</span>' if r["team_to_name"] else
                '<span class="und">미정</span>')
        if rm and r["status"] == "fa":
            dest = (f'<span class="rm-dest">{tm(rm["team"])}<span class="und">잔류?</span></span>' if rm["stay"] else
                    f'<span class="rm-dest">{tm(rm["team"])}</span>')
            if rm["stay"]:
                mv = dest
        if not (rm and r["status"] == "fa" and rm["stay"]):
            mv = f'{tm(r["team_from"])}<i class="arr" aria-hidden="true"></i>{dest}'
    sub = []
    if r["until"]:
        sub.append("~" + r["until"][:7].replace("-", "."))
    if r["memo"]:
        sub.append(r["memo"])
    if not sub and r["date"]:
        d = parse_day(r["date"])
        sub.append((f"{d.month}/{d.day}" if d else r["date"]) + (" 합류 발표" if r["status"] == "move" else " 결별"))
    lbl, cls = FA_ST.get(r["status"], ("?", "s-fa"))
    if rm and r["status"] == "fa":
        lbl, cls = ("발표" if rm["official"] else ("잔류 유력" if rm["stay"] else "유력")), ("s-ann" if rm["official"] else "s-rm")
        d = rel_day(rm["published"])
        src = f'{rm["outlet"]}{" " + d if d else ""}'
        sub = [f'<a class="rm-src" href="{esc(rm["url"])}" target="_blank" rel="noopener" title="{esc(rm["title"])}">{esc(src)} 기사 ↗</a>']
    real = f'<small>{esc(r["real"])}</small>' if r["real"] else ""
    ak = r["team_to"] if r["status"] == "move" and r["team_to"] else r["team_from"]   # 아바타: 새 팀(이적)·원래 팀
    badge = team_logo(ak, "bdg") if logo_src(ak) else ""
    grp = ("감독" if r["role"] == "Head Coach" else "코치") if coach else pos
    return (f'<li class="fa-row" data-page="{esc(r["page"])}" data-s="{r["status"]}" data-p="{grp}" data-t="{r["team_from"]}">'
            f'<span class="av tc{" off" if r["status"] == "fa" else ""}" style="--tc:{team_color(ak)}">{esc(pos)}{badge}</span>'
            f'<div class="who"><p class="nm" role="button" tabindex="0" title="선수 프로필 보기"><span class="nk">{esc(r["nick"])}</span>{real}</p>'
            f'<div class="mv">{mv}</div></div>'
            f'<div class="rt"><span class="st2 {cls}">{lbl}</span><span class="sub">{sub[0] if rm and r["status"] == "fa" else esc(" · ".join(sub))}</span></div></li>')


def rel_day(iso: str) -> str:
    """기사 시각 → '오늘'·'어제'·'11/17'(한국 시간)."""
    try:
        d = datetime.fromisoformat(iso).astimezone(KST).date()
    except (TypeError, ValueError):
        return ""
    today = datetime.now(KST).date()
    return "오늘" if d == today else "어제" if d == today - timedelta(days=1) else f"{d.month}/{d.day}"


def render_fa(league: str) -> str:
    with db() as c:
        rows = c.execute("SELECT * FROM fa").fetchall()
        upd = c.execute("SELECT v FROM meta WHERE k='fa_updated'").fetchone()
    today = datetime.now(KST).date()
    keys = team_keys()
    korder = {k: i for i, k in enumerate(keys)}
    porder = list(FA_POS)
    rows = sorted(rows, key=lambda r: (["move", "stay", "fa"].index(r["status"]) if r["status"] in FA_ST else 9,
                                       korder.get(r["team_from"], 99),
                                       porder.index(r["role"]) if r["role"] in porder else 99, r["nick"].lower()))
    cnt = {s_: sum(1 for r in rows if r["status"] == s_) for s_ in FA_ST}
    summ = (f'<button data-s="all"><b>{len(rows)}</b>FA 전체</button>'
            f'<button class="c-move" data-s="move"><b>{cnt["move"]}</b>이적 확정</button>'
            f'<button class="c-stay" data-s="stay"><b>{cnt["stay"]}</b>잔류</button>'
            f'<button class="c-fa" data-s="fa"><b>{cnt["fa"]}</b>미정</button>')
    nav = '<a href="#" data-t="all">전체</a>' + "".join(
        f'<a href="#" data-t="{k}" title="{esc(team_name(k))}">{team_logo(k)}<span>{esc(team_short(k))}</span></a>' for k in keys)
    heads = {k: f'<span class="gh">{team_logo(k)}{esc(team_short(k))}</span>' for k in keys}
    th = json.dumps(heads, ensure_ascii=False).replace("<", "\\u003c").replace("/", "\\/")
    if upd:
        u = datetime.fromisoformat(upd["v"]).astimezone(KST)
        faupd = f"{u:%H:%M} 갱신" if u.date() == today else f"{u.month}/{u.day} {u:%H:%M} 갱신"
    else:
        faupd = "아직 수집 전"
    since = parse_day(fa_since())
    rms = rumors(rows)
    board = moves_board(rows, rms)
    main = f"""{squad_toggle(league, "fa")}{board}<section class="card panel fa" aria-label="조회와 필터">
{ACT}<nav class="view_tab" id="grp" aria-label="묶어 보기"><a href="#" data-g="p">포지션별</a><a href="#" data-g="t">팀별</a><a href="#" data-g="s">상태별</a></nav>
<div class="sum">{summ}</div>
<div class="chips" id="pos">
<button data-p="all">전체 포지션</button><button data-p="탑">탑</button><button data-p="정글">정글</button><button data-p="미드">미드</button><button data-p="원딜">원딜</button><button data-p="서폿">서폿</button><button data-p="감독">감독</button><button data-p="코치">코치</button>
</div>
<p class="src">원소속 팀 기준 · 리그피디아 계약·로스터 변동 기록({f"{since.month}/{since.day}" if since else fa_since()} 이후) · {faupd} · 공식 발표가 리그피디아에 반영돼야 상태가 바뀌어요 · <b class="st2 s-rm">유력</b>은 최근 기사 제목 기준 참고 표시</p>
</section>
<section class="card">
<div class="tabs-wrap"><nav class="tabs" id="tabs" aria-label="원소속 팀">{nav}</nav></div>
<script type="application/json" id="th">{th}</script>
<ul class="list" id="falist">{"".join(fa_row_html(r, rms.get(r["page"])) for r in rows)}</ul>
</section>
{POPUP}"""
    return shell(league, "fa", "이적·FA", main, ("fa.js", "player.js"), today, scope="?what=fa")


# ── 로스터 ──────────────────────────────────────────────────────────────
def render_roster(league: str) -> str:
    today = datetime.now(KST).date()
    rows = roster_rows()
    cards = "".join(roster_card(k, rows) for k in team_keys())
    with db() as c:
        upd = c.execute("SELECT v FROM meta WHERE k='fa_updated'").fetchone()
    when = ""
    if upd:
        u = datetime.fromisoformat(upd["v"]).astimezone(KST)
        when = f" · {u.month}/{u.day} {u:%H:%M} 갱신"
    empty = '' if rows else '<p class="note">아직 로스터 정보를 모으는 중이에요. [조회]를 눌러 보세요.</p>'
    main = f"""{squad_toggle(league, "roster")}<section class="card panel fa" aria-label="조회">{ACT}
<p class="src">리그피디아 계약 기준 현재 로스터{when} · 빗금 칸은 아직 미정인 자리, '영입'은 이번 스토브리그에 새로 온 사람 · 이름을 누르면 프로필</p>
</section>
<div class="rgrid" id="rgrid">{cards}</div>{empty}
{POPUP}"""
    return shell(league, "roster", "로스터", main, ("roster.js", "player.js"), today, scope="?what=fa")


def squad_toggle(league: str, on: str, season=None) -> str:
    """'로스터·이적' 탭 안의 두 화면 전환."""
    sq = f"?season={season}" if season else ""

    def a(k, path, label):
        return f'<a class="{"on" if k == on else ""}" href="/{league}{path}{sq}" data-sec="{k}"{" aria-current=page" if k == on else ""}>{label}</a>'
    return f'<nav class="view_tab squad" aria-label="로스터·이적 보기">{a("roster", "/roster", "현재 로스터")}{a("fa", "/fa", "이적·FA 현황")}</nav>'


# ── 이동 보드(이적·FA 위) ───────────────────────────────────────────────
def moves_board(fa_rows, rms=None) -> str:
    """누가 어디서 어디로: LCK 팀끼리 이적 + LCK 밖에서 들어온 영입 + 팀을 떠난 뒤 해외·다른 곳으로 간 경우."""
    def tm(k, name=""):
        if k:
            return f'<span class="tm">{team_logo(k)}{esc(team_short(k))}</span>'
        return f'<span class="tm ext">{esc(name or "LCK 밖")}</span>'

    def who(r, pos, team, until=""):
        return (f'<span class="pn" role="button" tabindex="0" data-page="{esc(r["page"])}" data-nick="{esc(r["nick"])}"'
                f' data-real="{esc(r["real"] or "")}" data-pos="{pos}" data-team="{team}" data-until="{esc(until)}">'
                f'{esc(r["nick"])}</span>')
    items = []
    seen = set()
    outside = 0
    for r in fa_rows:
        if r["status"] != "move":
            continue
        pos = FA_POS.get(r["role"], r["role"])
        seen.add(r["page"])
        items.append((r["date"] or "", f'<li>{tm(r["team_from"])}<span class="ar" aria-label="에서">➔</span>{tm(r["team_to"], r["team_to_name"])}'
                                       f'<span class="mv-who"><small>{pos}</small>{who(r, pos, r["team_to"] or "")}</span></li>'))
    for r in fa_rows:                       # 유력(뉴스 기준, 공식 확정 전): 점선으로 구분
        rm = (rms or {}).get(r["page"])
        if r["status"] != "fa" or not rm or rm["stay"]:
            continue
        pos = FA_POS.get(r["role"], r["role"])
        tag = "발표" if rm["official"] else "유력"
        items.append((rm["published"][:10], f'<li class="rm">{tm(r["team_from"])}<span class="ar" aria-label="에서">➔</span>{tm(rm["team"])}'
                                            f'<span class="mv-who"><small>{pos}</small>{who(r, pos, rm["team"])}<em>{tag}</em></span></li>'))
    for r in roster_rows():
        if r["joined"] and r["page"] not in seen:
            outside += 1
            pos = FA_POS.get(r["role"], r["role"])
            items.append(("", f'<li>{tm("")}<span class="ar" aria-label="에서">➔</span>{tm(r["team"])}'
                              f'<span class="mv-who"><small>{pos}</small>{who(r, pos, r["team"])}</span></li>'))
    if not items:
        return ""
    items.sort(key=lambda x: x[0], reverse=True)
    return (f'<details class="card moves" open><summary>이동 보드 <small>누가 어디서 어디로 · {len(items)}건{f" (해외·2군 등 LCK 밖에서 온 영입 {outside}건 포함 — 아래 FA 목록엔 없어요)" if outside else ""}</small></summary>'
            f'<ul>{"".join(h for _, h in items)}</ul></details>')


# ── 찜·로스터 짜기용 선수 목록 ──────────────────────────────────────────
def people_list():
    out, seen = [], set()
    kmap = ko_nicks()
    for r in roster_rows():
        out.append({"page": r["page"], "nick": r["nick"], "ko": kmap.get(r["nick"], ""), "real": r["real"] or "",
                    "team": r["team"], "role": r["role"], "st": "roster"})
        seen.add(r["page"])
    with db() as c:
        for r in c.execute("SELECT * FROM fa"):
            if r["page"] in seen:
                continue
            out.append({"page": r["page"], "nick": r["nick"], "ko": kmap.get(r["nick"], ""), "real": r["real"] or "",
                        "team": r["team_to"] or (r["team_from"] if r["status"] == "stay" else ""), "role": r["role"],
                        "st": r["status"]})
    return out


# ── 로스터 짜기 ─────────────────────────────────────────────────────────
def shared_roster_og(r: str, by: str):
    """공유 링크(?r=...&n=...)를 카톡·디코에 붙였을 때 보일 제목·설명."""
    keys = team_keys()
    kmap = ko_nicks()
    lines = []
    for k, part in zip(keys, (r or "").split("|")):
        names = [x.split(" (")[0] for x in part.split(",")]
        shown = [kmap.get(n, n) for n in names if n]
        if shown:
            lines.append(f"{team_short(k)} " + "·".join(shown))
    if not lines:
        return None
    by = " ".join((by or "").split())[:12]
    year = current_season()
    return {"title": f"{by + '님의 ' if by else ''}{year} LCK 예상 로스터 🍄",
            "desc": " | ".join(lines[:3]) + (" … 10팀 전체 보고 내 버전도 짜 보기" if len(lines) > 3 else "")}


def render_builder(league: str, season=None, shared: str = "", by: str = "", code: str = "") -> str:
    today = datetime.now(KST).date()
    teams = [{"k": k, "short": team_short(k), "name": team_name(k), "color": team_color(k), "logo": logo_src(k) or ""}
             for k in team_keys()]
    data = json.dumps({"teams": teams, "people": people_list(), "pos": {k: FA_POS[k] for k in FA_ROLES}, "year": current_season(), "domain": SITE.get("domain") or "",
                       "shared": {"r": shared, "n": by} if code and shared else None},
                      ensure_ascii=False).replace("<", "\\u003c")
    main = f"""<section class="card panel bld-head">
<h2>🍄 나만의 버섯농장 짜기 <small>내년 시즌 10팀 주전 로스터 예상</small></h2>
<p class="src">선수를 고른 뒤 빈칸을 누르거나(모바일), 끌어다 놓으세요(PC). 이 브라우저에 자동 저장돼요.</p>
<div class="bld-act"><button class="btn primary" type="button" id="bsave">이미지로 저장</button><button class="btn" type="button" id="bshare">🔗 링크로 공유</button>
<button class="btn" type="button" id="breset">지금 로스터로 되돌리기</button>{"".join(f'<button class="btn" type="button" data-arch="{y}">{y} 로스터 불러오기</button>' for y in archive_years())}<button class="btn" type="button" id="bclear">모두 비우기</button></div>
</section>
<div class="shared-bar" id="bshared" hidden></div>
<div class="bld">
<section class="card pool" aria-label="선수 목록"><div class="pool-f"><input type="search" id="bq" placeholder="선수 찾기" aria-label="선수 찾기">
<div class="chips" id="bpos"><button data-p="all" class="on">전체</button>{"".join(f'<button data-p="{k}">{FA_POS[k]}</button>' for k in FA_ROLES)}</div>
<label class="chk"><input type="checkbox" id="bfree"><span>아직 팀 없는 선수만</span></label>
<label class="chk"><input type="checkbox" id="block"><span>🔒 확정 선수 잠금 (빈자리만 채우기)</span></label></div>
<ul id="bpool"></ul></section>
<div class="bgrid" id="bgrid"></div>
</div>
<script type="application/json" id="bdata">{data}</script>"""
    og = shared_roster_og(shared, by) if shared else None
    return shell(league, "builder", "로스터 짜기", main, ("builder.js",), today, season=season, og=og)


# ── 미니게임: 협곡 버섯 지뢰찾기 ────────────────────────────────────────
def render_game(league: str) -> str:
    today = datetime.now(KST).date()
    main = """<section class="card game" aria-label="협곡 버섯 지뢰찾기">
<header><b>🍄 협곡 버섯 탐지</b><select id="glv" aria-label="난이도"><option value="8,8,10">쉬움 8×8</option><option value="10,10,18">보통 10×10</option><option value="12,12,30">어려움 12×12</option></select>
<button class="btn primary" type="button" id="gnew">새 게임</button></header>
<div class="gbar"><span>남은 버섯 <b id="gleft">10</b></span><span id="gmsg">부쉬를 탐지하세요!</span><span id="gtime">0초</span></div>
<div class="gmode" role="group" aria-label="누르기 모드"><button type="button" class="on" data-m="dig">👁 탐지</button><button type="button" data-m="flag">🔴 렌즈</button></div>
<div class="gboard" id="gboard" oncontextmenu="return false"></div>
<p class="src">누르기: 시야 확보 · 오른쪽 클릭·길게 누르기·렌즈 모드: 🔴 표시 · 첫 칸은 항상 안전해요 · 최고 기록은 이 브라우저에 저장돼요 <b id="gbest"></b></p>
<button class="btn gshare" type="button" id="gshare" hidden>🍄 기록 자랑하기</button>
</section>"""
    return shell(league, "game", "미니게임", main, ("game.js",), today)


# ── 리그 안내 카드(tracker/leagues.json) ───────────────────────────────
import os as _os
try:
    with open(_os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "leagues.json"), encoding="utf-8") as _f:
        GUIDES = json.load(_f)
except (OSError, ValueError):
    GUIDES = {}


try:
    with open(_os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "team_profiles.json"), encoding="utf-8") as _f:
        PROFILES = {k: v for k, v in json.load(_f).items() if not k.startswith("_")}
except (OSError, ValueError):
    PROFILES = {}


try:
    with open(_os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "site.json"), encoding="utf-8") as _f:
        SITE = json.load(_f)
except (OSError, ValueError):
    SITE = {}


def _ok_url(u) -> bool:
    return isinstance(u, str) and u.startswith(("https://", "http://"))


def support_button() -> str:
    s = SITE.get("support") or {}
    if not _ok_url(s.get("url")):
        return ""
    qr = ""
    try:   # PC에서는 송금 링크가 안 열려서(휴대폰 전용) 버튼을 누르면 QR을 보여 줌. QR 그림은 tracker/support_qr.png
        import base64
        with open(_os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "support_qr.png"), "rb") as f:
            qr = "data:image/png;base64," + base64.b64encode(f.read()).decode()
    except OSError:
        pass
    pop = (f'<div class="sup-qr" hidden><img src="{qr}" alt="송금 QR 코드" width="160" height="160">'
           f'<p>휴대폰 카메라로 찍으면 송금 화면이 열려요</p><button type="button" class="btn">닫기</button></div>' if qr else "")
    return (f'<div class="support"><a href="{esc(s["url"])}" target="_blank" rel="noopener"{" data-qr=1" if qr else ""}>'
            f'{esc(s.get("label") or "🍄 후원하기")}</a>{pop}</div>')


def aff_note() -> str:
    """제휴 링크가 켜져 있으면 아래쪽에도 통합 안내(배너 바로 밑 문구와 별개로)."""
    if not _ok_url((SITE.get("affiliate") or {}).get("url")):
        return ""
    return ('<p class="aff-note">본 사이트 내 일부 상품 추천 링크는 제휴 마케팅 활동의 일환으로, 이를 통해 구매가 이루어질 경우 '
            '사이트 운영자에게 일정액의 수수료가 지급될 수 있습니다.</p>')



# ── 사이트 소개 · 개인정보처리방침 (구글 애드센스 심사용) ─────────────────
# 아래쪽 링크를 누르면 팝업으로 열리고, /about · /privacy 주소로 바로 열어도 같은 내용이 나와요.
POLICY_DATE = "2026년 11월 18일"


def _contact() -> str:
    c = SITE.get("contact")
    return c if isinstance(c, str) and "@" in c else ""


def _mail() -> str:
    c = _contact()
    return f'<a href="mailto:{esc(c)}">{esc(c)}</a>' if c else "사이트 아래쪽 문의하기"


def about_body() -> str:
    return f"""<h2>🍄 티모의 버섯농장 소개</h2>
<h3>어떤 사이트인가요</h3>
<p><b>티모의 버섯농장</b>({esc(SITE.get("domain") or "teemofarm.com")})은 리그 오브 레전드(LoL) 이스포츠 팬이 스토브리그 이적 소식, 구단별 로스터, 리그 정보를 한곳에서 편하게 볼 수 있도록 개인이 취미로 만들어 운영하는 팬 사이트예요. 서버비는 후원과 광고·제휴 수익으로 충당해요.</p>
<h3>주요 기능</h3>
<ul>
<li><b>소식</b> — 구글 뉴스와 리그피디아 편집 기록을 모아, 같은 내용의 기사는 하나로 묶고 오피셜·루머를 구분해 보여 줘요.</li>
<li><b>로스터·이적</b> — 구단별 현재 로스터와 계약이 끝난 선수(FA)의 이적·잔류 현황을 정리해요.</li>
<li><b>로스터 짜기</b> — 다음 시즌 로스터를 직접 조합해 이미지로 저장하거나 링크로 공유할 수 있어요.</li>
<li><b>리그·구단 안내와 시즌 기록</b> — 리그 구조, 구단 이력, 지난 시즌 우승팀·로스터·이적을 볼 수 있어요.</li>
<li><b>수다방·미니게임</b> — 로그인 없이 쓰는 대화방과 협곡 버섯 지뢰찾기가 있어요.</li>
</ul>
<h3>데이터 출처와 저작권</h3>
<p>로스터·계약·경기 정보는 <a href="https://lol.fandom.com" target="_blank" rel="noopener">Leaguepedia</a>(CC BY-SA 3.0)를 바탕으로 자동으로 모아요. 뉴스는 구글 뉴스 RSS에서 제목과 링크만 보여 주며, 기사 본문의 저작권은 각 언론사에 있어요. 리그 오브 레전드 관련 명칭과 자산은 Riot Games, Inc.의 상표예요.</p>
<h3>문의</h3>
<p>오류 제보, 데이터 수정 요청, 제휴 문의: {_mail()}</p>"""


def privacy_body() -> str:
    return f"""<h2>🔒 개인정보처리방침</h2>
<p>티모의 버섯농장(이하 '사이트')은 이용자의 개인정보를 소중히 여기며 「개인정보 보호법」 등 관련 법령을 지켜요. 사이트는 회원가입이 없고, 이름·전화번호·이메일 같은 정보를 묻거나 모으지 않아요.</p>
<h3>1. 서버에 저장되는 정보</h3>
<ul>
<li><b>수다방</b>: 이용자가 쓴 메시지, 닉네임, 작성 시각, 도배를 막기 위해 브라우저가 임의로 만든 번호. 최근 메시지 200개만 보관하고 그보다 오래된 것은 자동으로 지워져요.</li>
<li><b>로스터 공유</b>: '링크 공유하기'를 누른 경우 그 로스터 구성과 입력한 닉네임(선택). 공유 링크가 계속 열리도록 보관해요.</li>
<li><b>접속 기록</b>: 사이트 서버는 IP 주소 등 접속 기록을 따로 남기지 않아요.</li>
</ul>
<h3>2. 이용자 브라우저에만 저장되는 정보</h3>
<p>화면 테마, 스포 방지 설정, 읽은 기사, 찜한 선수, 작업 중인 로스터, 미니게임 기록, 수다방 닉네임은 이용자 브라우저의 저장 공간(localStorage)에만 남고 서버로 보내지 않아요. 브라우저의 사이트 데이터를 지우면 함께 지워져요.</p>
<h3>3. 쿠키와 광고</h3>
<ul>
<li>사이트는 운영비 마련을 위해 Google 애드센스 등 제3자 광고를 게재할 수 있어요.</li>
<li>Google을 비롯한 제3자 광고 업체는 쿠키를 사용해 이용자가 이 사이트나 다른 사이트를 방문한 기록을 바탕으로 광고를 보여 줄 수 있어요. Google은 광고 쿠키를 사용해 이용자에게 맞춤 광고를 게재해요.</li>
<li>맞춤 광고는 <a href="https://adssettings.google.com" target="_blank" rel="noopener">Google 광고 설정</a>에서 끌 수 있어요. 제3자 업체의 쿠키는 <a href="https://www.aboutads.info/choices" target="_blank" rel="noopener">aboutads.info</a>에서도 거부할 수 있어요.</li>
<li>Google의 정보 처리 방식은 <a href="https://policies.google.com/technologies/partner-sites" target="_blank" rel="noopener">Google 파트너 사이트 정책</a>에서 볼 수 있어요.</li>
</ul>
<h3>4. 외부 서비스</h3>
<ul>
<li>사이트 전송과 보안에 Cloudflare를, 글꼴 제공에 jsDelivr를 써요. 이 과정에서 각 서비스가 접속 IP 등을 자체 정책에 따라 처리할 수 있어요.</li>
<li>후원(Buy Me a Coffee), 제휴(쿠팡 파트너스), 뉴스·리그피디아 링크를 누르면 해당 사이트로 이동하며, 그곳의 개인정보 정책이 적용돼요. 제휴 링크로 구매하면 운영자가 일정액의 수수료를 받을 수 있어요.</li>
<li>사이트는 이용자 정보를 제3자에게 팔거나 제공하지 않아요.</li>
</ul>
<h3>5. 이용자의 권리</h3>
<p>본인이 쓴 수다방 메시지나 공유한 로스터를 지우고 싶으면 아래 이메일로 알려 주세요. 확인 후 지체 없이 지워 드려요.</p>
<h3>6. 개인정보 보호책임자 · 문의</h3>
<p>운영자 이메일: {_mail()}</p>
<h3>7. 시행일</h3>
<p>이 방침은 {POLICY_DATE}부터 적용돼요. 내용이 바뀌면 이 페이지에 먼저 알려 드려요.</p>"""


def policy_links() -> str:
    c = _contact()
    mail = f'<a href="mailto:{esc(c)}">문의하기</a>' if c else ""
    return (f'<nav class="policy-links" aria-label="사이트 정보"><a href="/about" data-pol="about">사이트 소개</a>'
            f'<a href="/privacy" data-pol="privacy">개인정보처리방침</a>{mail}</nav>')


def policy_dialogs() -> str:
    def d(k, body):
        return (f'<dialog class="pol-dlg" id="pol-{k}" aria-label="{"사이트 소개" if k == "about" else "개인정보처리방침"}">'
                f'<form method="dialog"><button class="pol-x" aria-label="닫기">✕</button></form>'
                f'<div class="pol-body">{body}</div></dialog>')
    return d("about", about_body()) + d("privacy", privacy_body())


def render_policy(kind: str) -> str:
    today = datetime.now(KST).date()
    body, title = (about_body(), "사이트 소개") if kind == "about" else (privacy_body(), "개인정보처리방침")
    return shell(DEFAULT_LEAGUE, "policy", title, f'<article class="card pol-page">{body}</article>', (), today)


def adsense_head() -> str:
    """site.json의 adsense.client(ca-pub-…)를 채우면 애드센스 스크립트를 <head>에 넣어요."""
    cid = (SITE.get("adsense") or {}).get("client") or ""
    if not re.fullmatch(r"ca-pub-\d{10,20}", cid):
        return ""
    return (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={cid}" '
            f'crossorigin="anonymous"></script>\n')


def ads_txt() -> str:
    cid = (SITE.get("adsense") or {}).get("client") or ""
    if not re.fullmatch(r"ca-pub-\d{10,20}", cid):
        return ""
    return f"google.com, {cid[3:]}, DIRECT, f08c47fec0942fa0\n"

def affiliate_card(cls: str = "") -> str:
    a = SITE.get("affiliate") or {}
    if not _ok_url(a.get("url")):
        return ""
    return (f'<section class="card aff {cls}" aria-label="제휴 추천 상품"><div class="ag-top"><span class="ag-badge">{esc(a.get("badge", ""))}</span>'
            f'<span class="ag-mark">AD · 제휴</span></div><b>{esc(a.get("title", ""))}</b>'
            f'<p>{esc(a.get("desc", ""))}</p><a class="btn primary" href="{esc(a["url"])}" target="_blank" rel="noopener sponsored nofollow">'
            f'{esc(a.get("button") or "보러 가기 ↗")}</a><small>{esc(a.get("disclaimer") or "")}</small></section>')


def team_profile(k: str, cls: str = "") -> str:
    """구단 소개 카드(팀을 고르면): 정식 이름·창단·주요 성적·한 줄 소개·공식 채널."""
    p = PROFILES.get(k)
    if not p:
        return ""
    links = p.get("links") or {}
    btns = "".join(f'<a class="tp-link" href="{esc(u)}" target="_blank" rel="noopener">{label}</a>'
                   for key, label in (("youtube", "▶️ 공식 유튜브"), ("x", "𝕏 공식 계정")) for u in [links.get(key)] if u)
    return (f'<section class="card tprof {cls}" style="--tcol:{esc(p.get("color", "var(--primary)"))}">'
            f'<header>{team_logo(k, "logo big")}<div><b>{esc(p["fullName"])}</b><small>창단 {esc(p.get("founded", ""))}</small></div></header>'
            f'<span class="tp-titles">🏆 {esc(p.get("titles", ""))}</span><p>{esc(p.get("summary", ""))}</p>'
            f'{f"<div class=tp-links>{btns}</div>" if btns else ""}{team_history(p)}</section>')


def team_history(p) -> str:
    """구단 이력(접힘): 팀명 변천사(계보) + 연도별 연혁."""
    lin, hist = p.get("lineage") or [], p.get("history") or []
    if not (lin or hist):
        return ""
    chain = " <i>←</i> ".join(f'<b class="cur">{esc(n)}</b>' if i == len(lin) - 1 else f"<span>{esc(n)}</span>"
                             for i, n in reversed(list(enumerate(lin))))                  # 지금 이름부터
    events = "".join(f'<li><em>{esc(e["year"])}</em>{esc(e["text"])}</li>' for e in reversed(hist))   # 최근 연도가 위로
    return (f'<details class="tp-hist"><summary>📜 구단 변천사 및 주요 이력<i aria-hidden="true">▾</i></summary>'
            f'{f"<p class=tp-lin>🏷️ {chain}</p>" if lin else ""}{f"<ul class=tp-tl>{events}</ul>" if events else ""}</details>')


def league_guide(league: str, opened: bool = False) -> str:
    g = GUIDES.get(league)
    if not g:
        return ""
    month = datetime.now(KST).month
    meta = g.get("meta", "").replace("{teams}", str(len(team_keys())))
    head = (f'<img class="lglogo" src="{esc(logo_src("lck"))}" alt="" width="40" height="40">' if league == "lck" and logo_src("lck")
            else f'<span class="lgflag" aria-hidden="true">{esc(g.get("flag", ""))}</span>')
    flow = ""
    if g.get("flow"):
        flow = '<ol class="lflow">' + "".join(
            f'<li class="{"now" if month in st.get("months", []) else ""}"><small>{esc(st["step"])}{" · ● 현재" if month in st.get("months", []) else ""}</small><b>{esc(st["title"])}</b></li>'
            for st in g["flow"]) + "</ol>"
    items = "".join(f'<div><b>{esc(it["label"])}</b><p>{esc(it["desc"])}</p></div>' for it in g.get("items", []))
    teams = ""
    if g.get("status") == "active" and league == "lck":
        teams = '<div class="lteams">' + "".join(
            f'<a href="/{league}?team={k}" title="{esc(team_name(k))}">{team_logo(k)}<span>{esc(team_short(k))}</span></a>'
            for k in team_keys()) + "</div>"
        teams = '<p class="lsec">🛡️ 참가 구단 · 누르면 그 팀 소식</p>' + teams
    road = ('<p class="lsec">📅 연간 시즌 로드맵</p>' + flow) if flow else ""   # 파이썬 3.10·3.11에서도 되게 f-string 밖에서
    return (f'<details class="card lguide" style="--la:{esc(g.get("accent", "var(--primary)"))}"{" open" if opened else ""}>'
            f'<summary>ℹ️ {esc(g["code"])} 리그 안내 <small>{esc(meta)}</small><i aria-hidden="true">▾</i></summary>'
            f'<div class="lg-body"><header>{head}<div><b>{esc(g.get("flag", ""))} {esc(g["name"])} ({esc(g["code"])})</b>'
            f'<small>{esc(g.get("region", ""))} · {esc(meta)}</small></div></header>{road}<div class="litems">{items}</div>{teams}</div></details>')


# ── 지난 시즌 기록(아카이브) ───────────────────────────────────────────
def _tname(key, name):
    return (f'<span class="tm">{team_logo(key)}{esc(team_short(key))}</span>' if key
            else f'<span class="tm ext">{esc(name or "LCK 밖")}</span>')


def render_archive(league: str, sec: str, year: int) -> str:
    """?season=2026 처럼 지난 시즌을 고르면: 소식=시즌 요약, 로스터=최종 로스터, 이적=그 시즌 스토브리그 이동, 일정=순위표."""
    today = datetime.now(KST).date()
    d = archive.get(year)
    active = {"": "news", "roster": "roster", "fa": "fa", "schedule": "schedule"}.get(sec, "news")
    title = f"{year} 시즌 기록"
    if not d:
        main = (f'<div class="card soon"><h2>📜 {year} 시즌 기록을 모으는 중이에요</h2>'
                f'<p>리그피디아에서 순위·로스터·이적 기록을 한 번 받아 저장해 둬요(처음 한 번만, 1~2분).<br>잠시 뒤 새로고침해 주세요.</p></div>')
        return shell(league, active, title, main, (), today, season=year)
    stages, champ = d.get("stages") or [], d.get("champion") or {}
    roster, moves = d.get("roster") or [], d.get("moves") or []
    note = ('<p class="src">일부 기록은 아직 못 받았어요(리그피디아 요청 한도). 30분 뒤 다시 받아요.</p>' if d.get("missing") else "")

    def champ_card():
        if not champ:
            return ""
        return (f'<section class="card champ"><span class="crown">👑</span><div><small>{esc(champ["name"])} 우승</small>'
                f'<b>{_tname(champ["wkey"], champ["winner"])}</b><p>결승 {esc(champ["score"])} · 상대 {_tname(champ["lkey"], champ["loser"])} · {esc(champ["date"])}</p></div></section>')

    def standings(limit=None):
        out = ""
        for st in reversed(stages):          # 최근 대회부터
            rows = st["table"][:limit] if limit else st["table"]
            trs = "".join(
                f'<tr><td class="pl">{esc(str(r["place"]))}</td><td>{T.tname(r["key"], r["team"])}</td>'
                f'<td>{esc(r["w"])}승 {esc(r["l"])}패</td><td class="gd">{esc(r["gw"])}–{esc(r["gl"])}</td></tr>' for r in rows)
            out += (f'<section class="card stand"><h3>{esc(st["name"])}</h3><table><thead><tr><th>순위</th><th>팀</th><th>매치</th><th>세트</th></tr></thead>'
                    f'<tbody>{trs}</tbody></table></section>')
        return out or '<p class="note">순위표 기록이 없어요.</p>'

    def moves_list(limit=None):
        items = moves[-limit:] if limit else moves
        if not items:
            return '<p class="note">이 시즌 스토브리그 이동 기록이 없어요.</p>'
        lis = "".join(f'<li>{_tname(m["fkey"], m["from"])}<span class="ar">➔</span>{_tname(m["tkey"], m["to"])}'
                      f'<span class="mv-who"><small>{esc(m["date"][5:].replace("-", "."))}</small><b>{esc(m["nick"])}</b></span></li>'
                      for m in reversed(items))
        return (f'<details class="card moves" open><summary>{year} 스토브리그 이동 <small>{year - 1}.11 ~ {year}.01 · {len(moves)}건</small></summary>'
                f'<ul>{lis}</ul></details>')

    if active == "roster":
        rows = [{"team": r["team"], "role": r["role"], "page": r["page"], "nick": r["nick"], "real": "", "until": "", "joined": 0}
                for r in roster if r["team"]]
        cards = "".join(roster_card(k, rows) for k in team_keys() if any(r["team"] == k for r in rows))
        main = (f'{squad_toggle(league, "roster", year)}<section class="card panel"><p class="src">{year} 시즌 마지막 정규 대회에 등록된 로스터(리그피디아) · 지금 팀 이름·로고로 표시</p>{note}</section>'
                f'<div class="rgrid">{cards or "<p class=note>로스터 기록이 없어요.</p>"}</div>{POPUP}')
        scripts = ("player.js",)
    elif active == "fa":
        main = f'{squad_toggle(league, "fa", year)}{note}{moves_list()}'
        scripts = ()
    elif active == "schedule":
        main = f'{champ_card()}{note}<div class="stands">{standings()}</div>'
        scripts = ()
    else:
        main = (f'{champ_card()}{note}<div class="stands">{standings(limit=3)}</div>'
                f'<p class="note"><a href="/{league}/schedule?season={year}">전체 순위표 보기 →</a></p>{moves_list(limit=8)}')
        scripts = ()
    return shell(league, active, title, main, scripts, today, season=year)


# ── 일정·결과 ───────────────────────────────────────────────────────────
STOVE_SCH = """<section class="card stove-sch"><h2>🍄 스토브리그 주요 일정</h2><ol>
<li class="done"><time>11.15</time><b>코치 영입 가능</b><small>LCK 공지 기준</small></li>
<li class="done"><time>11.17</time><b>선수 FA 시장 개장</b><small>계약 만료 선수 일제히 FA</small></li>
<li><time>미정</time><b>KeSPA Cup</b><small>일정이 발표되면 반영해요</small></li>
{opening}
</ol><p class="src">날짜는 LCK 발표·보도 기준 · 확정되지 않은 일정은 '미정'으로 둬요</p></section>"""
TOUR_KO = (("Season Playoffs", "플레이오프"), ("Season Play-In", "플레이-인"), ("Road to MSI", "MSI 선발전"),
           ("Regional Finals", "대표 선발전"), ("Grand Finals", "그랜드 파이널"), ("Rounds 1-2", "정규 1·2라운드"),
           ("Rounds 3-4", "정규 3·4라운드"), ("Lock-In", "락인"), ("Promotion", "승강전"), ("Playoffs", "플레이오프"),
           ("Play-In", "플레이-인"), ("Spring", "스프링"), ("Summer", "서머"), ("Winter", "윈터"), ("Versus", "버서스"),
           ("Split ", "스플릿 "), (" Season", ""))


def tour_ko(page: str, lg_name: str = "LCK") -> str:
    """'LPL/2026 Season/Split 1 Playoffs' → '스플릿 1 플레이오프', 'LCK/2026 Season/Cup' → 'LCK 컵'."""
    t = (page or "").split("Season/", 1)[-1]
    if t == "Cup":
        return f"{lg_name} 컵"
    for en, ko in TOUR_KO:
        t = t.replace(en, ko)
    return t.strip()


def match_teams(league: str, names) -> dict:
    """경기 상세 팝업용: 팀 이름 → {short, logo(주소, 없으면 '')}."""
    T = SchTeams(schedule.get(league))
    out = {}
    for n in names:
        k = schedule.team_id(league, n)
        out[n] = {"short": T.short(k, n), "logo": logo_src(k) if k in TEAMS else teamlogos.url(k) if k else ""}
    return out


def _page_year(page: str) -> str:
    """'LCK/2026 Season/Cup' → '2026'."""
    m = re.search(r"/(\d{4}) Season/", page or "")
    return m.group(1) if m else ""


class SchTeams:
    """일정 화면의 팀 표시: LCK 팀은 기존 로고·약칭, 다른 리그 팀은 리그피디아 약칭과 글자 로고."""

    def __init__(self, d):
        self.info = d.get("teams") or {}

    def short(self, k, name):
        if k in TEAMS:
            return team_short(k)
        return (self.info.get(k) or {}).get("short") or name or "TBD"

    def full(self, k, name):
        return team_name(k) if k in TEAMS else (name or "미정")

    def logo(self, k, name):
        if k in TEAMS:
            return team_logo(k)
        src = teamlogos.url(k) if k else ""
        if src:
            return f'<img class="logo" src="{esc(src)}" alt="" width="20" height="20" loading="lazy">'
        return f'<span class="logo txt" aria-hidden="true">{esc((self.short(k, name) if k else "?")[:1])}</span>'

    def tname(self, k, name):
        return f'<span class="tm">{self.logo(k, name)}{esc(self.short(k, name))}</span>'


def tab_ko(tab: str) -> str:
    """'Week 3' → '3주차', 'Playoffs Round 2' → '플레이오프 2라운드', 'Finals' → '결승'."""
    t = tab or ""
    for en, ko in (("Playoffs ", "플레이오프 "), ("Play-In ", "플레이-인 "), ("Group Stage", "그룹 스테이지")):
        t = t.replace(en, ko)
    words = t.split()
    if len(words) >= 2 and words[-1].isdigit():
        n, w = words[-1], words[-2]
        unit = {"Week": "주차", "Round": "라운드", "Day": "일차"}.get(w)
        if unit:
            return " ".join(words[:-2] + [n + unit])
    return {"Finals": "결승", "Final": "결승", "Semifinals": "준결승", "Quarterfinals": "8강", "Tiebreakers": "타이브레이커"}.get(t, t)


def _sch_at(m):
    try:
        return datetime.strptime(m["at"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return None


def _sch_state(m, now) -> str:
    if m.get("win") in ("1", "2"):
        return "done"
    at = _sch_at(m)
    if at and at <= now:
        return "live" if now - at < timedelta(hours=schedule.LIVE_HOURS) else "done"
    return "up"


def match_row(m, now, T, lg_name) -> str:
    """경기 한 줄: 시간 · 팀1 · 점수(또는 VS) · 팀2 · 대회·라운드. 끝난 경기 점수는 '스포 방지'면 흐리게."""
    at = _sch_at(m).astimezone(KST)
    st = _sch_state(m, now)
    w1, w2 = (" w" if m["win"] == "1" else ""), (" w" if m["win"] == "2" else "")

    def side(k, name, cls):
        return f'<span class="side {cls}" title="{esc(T.full(k, name))}">{T.logo(k, name)}<b>{esc(T.short(k, name))}</b></span>'
    if st == "done" and (m["s1"] or m["s2"]):
        mid = f'<span class="sc" title="눌러서 결과 보기">{esc(m["s1"] or "0")}<i>:</i>{esc(m["s2"] or "0")}</span>'
    elif st == "done":
        mid = '<span class="sc">종료</span>'
    elif st == "live":
        mid = '<span class="live">LIVE</span>'
    else:
        mid = '<span class="vs">VS</span>'
    meta = " · ".join(x for x in (tour_ko(m["page"], lg_name), tab_ko(m["tab"]), f'Bo{m["bo"]}' if m["bo"] else "",
                                   "몰수승" if m.get("ff") else "") if x)
    teams = " ".join(k for k in (m["k1"], m["k2"]) if k)
    det = f' data-id="{esc(m["id"])}" tabindex="0" role="button" aria-label="경기 상세 보기"' if st == "done" and m.get("id") else ""
    return (f'<li class="mt {st}" data-teams="{teams}"{det}><time datetime="{at.isoformat()}">{at:%H:%M}</time>'
            f'{side(m["k1"], m["t1"], "a" + w1)}{mid}{side(m["k2"], m["t2"], "b" + w2)}<small class="mm">{esc(meta)}</small></li>')


def match_days(ms, now, T, lg_name, newest_first=False) -> str:
    days, order = {}, []
    for m in ms:
        d = _sch_at(m).astimezone(KST).date()
        if d not in days:
            days[d] = []
            order.append(d)
        days[d].append(m)
    if newest_first:
        order.reverse()
    today = now.astimezone(KST).date()
    out = ""
    for d in order:
        tag = " <em>오늘</em>" if d == today else " <em class=tm2>내일</em>" if d == today + timedelta(days=1) else ""
        out += (f'<section class="sday"><h4>{d.month}월 {d.day}일 ({WEEKDAYS[d.weekday()]}){tag}</h4>'
                f'<ul>{"".join(match_row(m, now, T, lg_name) for m in days[d])}</ul></section>')
    return out


def render_schedule(league: str) -> str:
    today = datetime.now(KST).date()
    now = datetime.now(timezone.utc)
    d = schedule.get(league)
    lg_name = LEAGUES[league]["name"]
    T = SchTeams(d)
    cs = current_season(today)
    opening = f'<li><time>미정</time><b>{cs} LCK 개막</b><small>리그피디아에 일정이 올라오면 아래에 저절로 떠요</small></li>'
    first = min((_sch_at(m) for m in d.get("matches") or [] if _sch_at(m)), default=None) if d.get("current") else None
    if first:
        f = first.astimezone(KST)
        opening = (f'<li class="{"done" if f.date() <= today else ""}"><time>{f.month}.{f.day:02d}</time><b>{cs} LCK 개막</b>'
                   f'<small>{f:%H:%M} 첫 경기 · 리그피디아 일정 기준</small></li>')
    stove = STOVE_SCH.format(opening=opening) if in_season(today) and league == "lck" else ""
    if not d.get("season"):
        msg = ("리그피디아에서 일정을 받아 오지 못했어요. 잠시 뒤 다시 들어와 주세요." if d.get("error")
               else "리그피디아에서 일정·결과를 받아 오는 중이에요(서버를 켠 뒤 1~2분).<br>잠시 뒤 새로고침해 주세요.")
        main = f'{stove}<div class="card soon"><h2>📅 일정·결과</h2><p>{msg}</p></div>'
        return shell(league, "schedule", "일정·결과", main, (), today)

    ms = [m for m in d.get("matches") or [] if _sch_at(m)]
    live = [m for m in ms if _sch_state(m, now) == "live"]
    up = [m for m in ms if _sch_state(m, now) == "up"]
    done = [m for m in ms if _sch_state(m, now) == "done"]
    season = d["season"]

    notice = ""
    if not d.get("current"):
        notice = (f'<div class="archive-bar sch-note">📅 <b>{cs} {esc(lg_name)}</b> 일정은 아직 리그피디아에 올라오지 않았어요. 올라오면 이 화면에 저절로 떠요. '
                  f'아래는 <b>{season} 시즌</b> 결과예요.</div>')

    champ = ""
    fin = [m for m in done if m["playoff"] and m["tab"] in ("Finals", "Final") and m["win"] in ("1", "2")]
    if fin and not up and not live:
        m = fin[-1]
        a, b = ((m["k1"], m["t1"], m["s1"]), (m["k2"], m["t2"], m["s2"]))
        win, lose = (a, b) if m["win"] == "1" else (b, a)
        champ = (f'<section class="card champ sch-champ"><span class="crown">👑</span><div><small>{esc(lg_name)} {esc(tour_ko(m["page"], lg_name))} 우승 · {_page_year(m["page"])}</small>'
                 f'<b>{T.tname(win[0], win[1])}</b><p class="sc-hide">결승 {esc(win[2])}:{esc(lose[2])} · 상대 {T.tname(lose[0], lose[1])} · '
                 f'{_sch_at(m).astimezone(KST):%Y.%m.%d}</p></div></section>')

    # 팀 탭(화면 안에서 거름. '내 팀'은 별 표시)
    st = d.get("standings") or {}
    if league == "lck":
        keys = team_keys()
    else:                                   # 순위표 순서, 그다음 나머지 팀(약칭 가나다순)
        keys = [r["key"] for g in st.get("groups") or [] for r in g["table"] if r["key"]]
        keys += sorted((k for k in T.info if k not in keys), key=lambda k: T.short(k, "").lower())
        keys = list(dict.fromkeys(keys))
    nav = '<a class="on" href="#" data-t="all">전체</a>' + "".join(
        f'<a href="#" data-t="{k}" title="{esc(T.full(k, (T.info.get(k) or {}).get("name")))}">{T.logo(k, (T.info.get(k) or {}).get("name"))}'
        f'<span>{esc(T.short(k, (T.info.get(k) or {}).get("name")))}</span></a>' for k in keys)

    blocks = ""
    if live:
        blocks += f'<section class="card sblock live-b"><h3>🔴 지금 경기 중</h3>{match_days(live, now, T, lg_name)}</section>'
    if up:
        first_days = sorted({_sch_at(m).astimezone(KST).date() for m in up})
        cut = first_days[min(len(first_days), 5) - 1]
        soon = [m for m in up if _sch_at(m).astimezone(KST).date() <= cut]
        later = [m for m in up if _sch_at(m).astimezone(KST).date() > cut]
        more = (f'<details class="smore"><summary>이후 일정 <b class="n">{len(later)}</b>경기 더 보기</summary>{match_days(later, now, T, lg_name)}</details>'
                if later else "")
        blocks += f'<section class="card sblock"><h3>📅 다가오는 경기</h3>{match_days(soon, now, T, lg_name)}{more}</section>'
    if done:
        last_days = sorted({_sch_at(m).astimezone(KST).date() for m in done}, reverse=True)
        cut = last_days[min(len(last_days), 4) - 1]
        recent = [m for m in done if _sch_at(m).astimezone(KST).date() >= cut]
        older = [m for m in done if _sch_at(m).astimezone(KST).date() < cut]
        more = (f'<details class="smore"><summary>지난 결과 <b class="n">{len(older)}</b>경기 더 보기</summary>{match_days(older, now, T, lg_name, True)}</details>'
                if older else "")
        blocks += (f'<section class="card sblock"><h3>✅ {"최근 결과" if d.get("current") else f"{season} 시즌 마지막 결과"}'
                   f'<small>경기를 누르면 밴픽·선수 기록이 보여요</small></h3>{match_days(recent, now, T, lg_name, True)}{more}</section>')
    if not blocks:
        blocks = '<div class="card soon"><h2>경기 일정이 아직 없어요</h2><p>리그피디아에 일정이 올라오면 여기에 보여 줄게요.</p></div>'
    empty = '<p class="note sch-empty" id="schEmpty" hidden>이 팀 경기가 없어요.</p>'

    stand = ""
    if st.get("groups"):
        tables = ""
        for g in st["groups"]:
            trs = "".join(
                f'<tr data-team="{esc(r["key"])}"><td class="pl">{esc(str(r["place"]))}</td><td>{T.tname(r["key"], r["team"])}</td>'
                f'<td>{esc(r["w"])}승 {esc(r["l"])}패</td><td class="gd">{esc(r["gw"])}–{esc(r["gl"])}</td></tr>' for r in g["table"])
            head = f'<h4>{esc(g["name"])}</h4>' if g["name"] else ""
            tables += (f'{head}'
                       f'<table><thead><tr><th>순위</th><th>팀</th><th>매치</th><th>세트</th></tr></thead><tbody>{trs}</tbody></table>')
        stand = (f'<section class="card stand sch-stand"><h3>🏆 {esc(lg_name)} {esc(tour_ko(st.get("page") or st["name"], lg_name))} 순위 <small>{_page_year(st.get("page") or "")}</small></h3>{tables}'
                 f'<p class="src">리그피디아 순위표 기준{" · 그룹은 서로 맞붙은 팀끼리 묶어 표시" if len(st["groups"]) > 1 else ""}</p></section>')

    upd = ""
    try:
        u = datetime.fromisoformat(d["at"]).astimezone(KST)
        upd = f" · {u.month}/{u.day} {u:%H:%M} 갱신"
    except (KeyError, ValueError):
        pass
    main = f"""{notice}{stove}{champ}
<div class="sch-grid"><div>
<section class="card sch-tabs"><div class="tabs-wrap"><nav class="tabs" id="tabs" aria-label="팀">{nav}</nav></div></section>
{blocks}{empty}
</div><aside>{stand}</aside></div>
{POPUP}
<p class="note">일정·결과·순위·경기 기록 출처 리그피디아 · 챔피언 이미지 Riot Games Data Dragon{upd} · 경기 날엔 5분마다, 평소엔 30분마다 새로 받아요 · 시간은 한국 시간</p>"""
    return shell(league, "schedule", f"{lg_name} 일정·결과", main, ("schedule.js",), today)


def render_soon(league: str) -> str:
    today = datetime.now(KST).date()
    lg = LEAGUES[league]
    main = (f'<div class="soon-bar">🚧 지금은 {esc(lg["name"])} 소식·로스터 탐지를 준비 중이에요. 아래 카드에서 리그 정보를 먼저 확인해 보세요! '
            f'<a href="/lck">LCK 보러 가기 →</a></div>'
            + (f'<a class="card sch-go" href="/{league}/schedule">📅 <b>{esc(lg["name"])} 일정·결과·순위</b>는 지금 볼 수 있어요 →</a>'
               if lg.get("wiki") else "")
            + league_guide(league, opened=True))
    return shell(league, "", lg["name"], main, (), today)
