"""화면 HTML 만들기: 공통 껍데기, 소식·로스터·이적(FA)·일정, 준비 중 리그."""
import html
import re
import json
import urllib.parse
from datetime import datetime, timedelta, timezone

from ..cargo import RATE_MSG, is_rate_limit
from ..classify import article_kind, is_minor_wiki, news_teams, wiki_ko
from ..cluster import group as cluster_group
from ..rumor import movers, rumors
from .. import stove as stv, vote
from ..config import (AUTO_MINUTES, DEFAULT_LEAGUE, KST, LEAGUES, NEW_HOURS, SITE_DESC, SITE_NAME, TEAM_COLORS,
                      TEAMS)
from ..core import STATUS, STATUS_LOCK, WEEKDAYS, db, kst_day_start_utc, norm_title, parse_day, rel_time
from ..fa import FA_ROLES, fa_since
from ..filters import is_lol_news, ko_nicks
from ..insight import is_spoiler, overseas_tag, search_terms, trust
from ..archive import archive_years, current_season
from .. import archive, farm as farmd, schedule, teamlogos
from . import farm_art
from ..logos import TEAM_LOGOS

# 제목 옆 버섯: 그림 대신 기기 기본 버섯 이모지(🍄). '조회 중' 화면에서도 같은 이모지가 뛰어감
SHROOM_SVG = ('<button type="button" class="teemo" id="teemo" title="유독성 함정 배치 완료!" aria-label="버섯">'
              '<img class="mk" src="/img/shroom.png" alt="" width="34" height="34" '
              """onerror="this.parentNode.classList.add('noimg')">"""
              '<span class="mk emo" aria-hidden="true">🍄</span></button>')
# 메신저·SNS 링크 미리보기(카톡·디코·X 등). 그림은 tracker/og.jpg(1200×630)
OG_TITLE = "🍄 티모의 버섯농장 · LCK 스토브리그·로스터·이적"
OG_DESC = "LCK 오피셜·루머·로스터·이적과 리그별 일정·결과를 모아 봐요. 내 로스터도 짜 볼 수 있어요."
RIOT_NOTE = ("'티모의 버섯농장'은 Riot Games가 보증하지 않으며, Riot Games 또는 리그 오브 레전드 제작·관리에 공식적으로 관여하는 "
             "당사자의 견해나 의견을 반영하지 않습니다. 리그 오브 레전드 및 Riot Games는 Riot Games, Inc.의 상표 또는 등록 상표입니다.")
FONT_CSS = "https://cdn.jsdelivr.net/npm/pretendard-gov@1.3.9/dist/web/variable/pretendardvariable-gov-dynamic-subset.css"
STATIC_VER = "1"           # server가 정적 파일 내용으로 바꿔 넣음(캐시 무효화)
FA_POS = {"Top": "탑", "Jungle": "정글", "Mid": "미드", "Bot": "원딜", "Support": "서폿",
          "Head Coach": "감독", "Coach": "코치", "Analyst": "분석"}
FA_ST = {"move": ("이적 확정", "s-move"), "stay": ("잔류", "s-stay"), "fa": ("미정", "s-fa")}
KIND = {"official": ("오피셜", "k-official"), "rumor": ("단독·유력", "k-rumor"),
        "view": ("전망·분석", "k-view"), "edit": ("편집", "k-edit")}
SECTIONS = [("news", "", "소식"), ("roster", "/roster", "로스터"), ("fa", "/fa", "이적·FA"), ("builder", "/builder", "내맘대로 로스터"),
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


def stove_phase(today) -> bool:
    """스토브리그 단계: 11~12월, 그리고 1월 중 새 시즌 첫 경기 전(리그피디아 일정 기준, LCK)."""
    if today.month in (11, 12):
        return True
    if today.month != 1:
        return False
    cs = current_season(today)
    first = min((_sch_at(m) for m in schedule.get(DEFAULT_LEAGUE).get("matches") or []
                 if f"/{cs} Season/" in (m.get("page") or "") and _sch_at(m)), default=None)
    return first is None or first.astimezone(KST).date() > today


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
        f': {esc(friendly(st["msg"]))}<br><small>{esc(st["msg"])}</small></li>' for k, s_, st in fails)
    foot = (f'<details class="fail"><summary>일부 출처 시야가 잠시 가려졌어요 ({len(fails)}) · 잠시 뒤 다시 가져올게요</summary>'
            f'<ul>{lis}</ul></details>')
    return head, foot


ACT = f"""<div class="rfr">
<button id="go" class="rbtn" type="button" title="지금 새로 가져오기"><span class="ico" aria-hidden="true">↻</span><span class="lbl">조회</span><span id="next" class="next" aria-live="off"></span></button>
<label class="sw" title="{AUTO_MINUTES}분마다 자동으로 새로 가져오기"><input type="checkbox" id="auto" role="switch"><span class="knob" aria-hidden="true"></span><span class="swl">자동</span></label>
</div>"""
MSG = '<p id="msg" class="msg" role="status" aria-live="polite"></p>'

POPUP = """<div class="dim" id="dim" aria-hidden="true">
<div class="pop" role="dialog" aria-modal="true" aria-labelledby="pn">
<div class="grab" aria-hidden="true"></div>
<button class="x" type="button" aria-label="닫기"></button>
<div id="pbody"></div>
</div>
</div>
"""


# 선 아이콘(단색, 글자색을 따라감). 이모지 대신 꼭 필요한 버튼에만
_SVG = '<svg class="i" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
ICON_EYE_OFF = _SVG + '<path d="M3 3l18 18"/><path d="M10.6 5.1A10 10 0 0 1 12 5c6 0 9.5 7 9.5 7a17 17 0 0 1-3.3 4.2M6.6 6.6A17 17 0 0 0 2.5 12S6 19 12 19a9.6 9.6 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>'
ICON_MOON = _SVG + '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>'

SEC_PATH = {"news": "", "roster": "/roster", "fa": "/fa", "schedule": "/schedule", "results": "/results",
            "stove": "/stove", "teams": "/teams", "builder": "/builder", "game": "/game",
            "summary": "/summary", "predict": "/predict", "contracts": "/contracts"}


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
    stove = stove_phase(today)
    # 메뉴는 리그의 한 해 흐름(시즌 단계)대로: 소식 · 스토브리그(이적·FA·로스터 짜기·스토브리그 일정) · 시즌(일정·결과) · 팀(로스터·구단)
    # 스토브리그 기간엔 '스토브리그'가, 시즌 중엔 '시즌'이 소식 바로 다음. 탭의 data-sec은 그 묶음의 첫 화면
    news_t = ("news", "", "소식", ("news",))
    stove_t = ("fa", "/fa", "스토브리그", ("fa", "summary", "predict", "builder", "stove"))
    season_t = ("schedule", "/schedule", "시즌", ("schedule", "results"))
    team_t = ("roster", "/roster", "팀", ("roster", "contracts", "teams"))
    now_y = current_season(today)
    pre = bool(season) and stove and season == now_y          # 개막 전 다음 시즌 미리 보기(스토브리그 기간의 '2027 시즌 예정')
    tab_defs = [news_t, stove_t, season_t, team_t] if stove else [news_t, season_t, team_t, stove_t]
    if pre:                                                    # 미리 보기엔 아직 경기·스토브리그가 없음: 한눈에 · 시즌(일정) · 팀(로스터)
        tab_defs = [("news", "", "개막 준비", ("news",)), season_t, team_t]
    # 'HOT'은 지금 시기에 앞으로 온 메뉴 하나에만: 스토브리그 기간엔 '스토브리그', 시즌 중엔 '시즌'. 지난 시즌 기록을 볼 땐 안 붙임
    hot = {} if season else {(stove_t if stove else season_t)[0]: True}
    sq = f"?season={season}" if season else ""
    # 시즌 고르기: (스토브리그 기간엔) 다음 시즌 예정 + 지금 시즌 + 지난 시즌 기록
    # 해마다 한 묶음: 2026년 11월 스토브리그는 '2026 시즌' 안의 스토브리그 메뉴로 봄. 데이터상 시즌(now_y)은 그다음 해
    now_label = f"{now_y - 1 if stove else now_y} 시즌"
    here = SEC_PATH.get(active, "")
    # 스토브리그 기간엔 방금 끝난 시즌(now_y-1)이 곧 '지금' 화면(경기·결과는 시즌 메뉴에 그대로)이라 기록 목록엔 안 둠.
    # 같은 해가 '지금'과 '기록'으로 두 번 보이면 헷갈림. 주소로 직접 들어온 경우만 표시
    past_ys = [y for y in archive_years() if not (stove and y == now_y - 1)]
    pre_here = here if active in ("news", "schedule", "results", "roster") else ""
    s_items = ((f'<li><a class="{"on" if pre else ""}" href="/{league}{pre_here}?season={now_y}">{now_y} 시즌<small>예정</small></a></li>' if stove else "")
               + f'<li><a class="{"" if season else "on"}" href="/{league}{here}">{now_label}<small>지금</small></a></li>'
               + "".join(f'<li><a class="{"on" if season == y else ""}" href="/{league}{here}?season={y}">{y} 시즌<small>기록</small></a></li>'
                         for y in past_ys))
    ssel = "" if not cur["enabled"] else (f'<details class="lgsel ssel"><summary aria-label="시즌 고르기"><b>{f"{season} 시즌" if season else now_label}</b><i aria-hidden="true">▾</i></summary>'
            f'<ul>{s_items}</ul></details>')
    bar = (f'<div class="archive-bar">지금 <b>{season} 시즌</b> 기록을 보고 있어요. '
           f'<a href="/{league}{here}">최신 화면으로 돌아가기 →</a></div>' if season and not pre else "")
    if pre:
        bar = (f'<div class="archive-bar pre-bar"><b>{season} 시즌</b>은 아직 개막 전이에요. 지금 진행 중인 스토브리그는 '
               f'<a href="/{league}/fa">{now_label} &gt; 스토브리그</a>에서 볼 수 있어요.</div>')
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
<div class="stat">{head}<span class="tools"><button type="button" class="tbtn" id="spo" aria-pressed="false" title="경기 결과·루머 핵심을 흐리게 가려요" aria-label="스포 방지">{ICON_EYE_OFF}<span class="lb">스포 방지</span></button><button type="button" class="tbtn ico" id="thm" title="화면 밝기 바꾸기">{ICON_MOON}</button><a class="tbtn{" on" if active == "game" else ""}" href="/{league}/game" aria-label="미니게임">🍄<span class="lb">미니게임</span></a></span></div>
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
_RM_SLOTS = {"at": 0.0, "val": {}, "out": {}}


def roster_leaving() -> dict:
    """계약이 남은 선수 중 다른 팀 이적 유력: {page: 유력 정보}. rumor_slots와 같이 30초 캐시."""
    rumor_slots()
    return _RM_SLOTS["out"]


def rumor_slots() -> dict:
    """로스터 카드용 '유력'(뉴스 기준, 공식 확정 전): {팀: {자리: [FA·로스터 행 + 유력 정보]}}. 30초 캐시.
    FA(계약 만료) 선수 + 계약이 남은 선수의 이적 유력(단독·소식통·오피셜만)."""
    import time as _t
    if _t.time() - _RM_SLOTS["at"] < 30:
        return _RM_SLOTS["val"]
    out, leaving = {}, {}
    try:
        with db() as c:
            fa_rows = c.execute("SELECT * FROM fa WHERE league='lck'").fetchall()
        rms = rumors(fa_rows)
        people = [(r, rms.get(r["page"])) for r in fa_rows]
        ros = roster_rows()
        leaving = movers(ros)
        people += [({**dict(r), "team_from": r["team"]}, leaving.get(r["page"])) for r in ros]
        for r, rm in people:
            if not rm or not rm["team"]:
                continue
            coach_news = _coach_news(rm)
            slot = r["role"] if r["role"] in ROSTER_SLOTS and not coach_news else "Head Coach"
            pos = shown_pos(r["role"], rm)
            out.setdefault(rm["team"], {}).setdefault(slot, []).append({**dict(r), "until": "", "rm": rm, "pos": pos})
    except Exception:  # noqa: BLE001  참고 표시라 실패해도 로스터는 그대로
        out, leaving = {}, {}
    _RM_SLOTS.update(at=_t.time(), val=out, out=leaving)
    return out


def rm_label(rm) -> str:
    """'유력' 표시 글자(이적 시장·로스터·이동 보드·행선지 맞히기 공통): 발표 · 유력 · 잔류 발표 · 잔류 유력."""
    return ("잔류 " if rm["stay"] else "") + ("발표" if rm["official"] else "유력")


def _coach_news(rm) -> bool:
    return bool(rm) and any(w in rm["title"] for w in ("코치", "감독", "코칭"))    # 선수 출신이 코치로 가는 기사


def shown_pos(role: str, rm=None) -> str:
    """화면마다 같은 직책을 보이게(이적 시장·로스터·팝업 공통): 리그피디아 직책,
    선수 출신이 코치로 간다는 기사면 기사 제목 기준('라이프': 서폿 → 코치)."""
    if _coach_news(rm) and role in FA_ROLES:
        return "감독" if "감독" in rm["title"] and "코치" not in rm["title"] else "코치"
    return FA_POS.get(role, role)


def roster_card(k: str, rows, extra_cls: str = "", rm: bool = True, name_then: str = "") -> str:
    """name_then: 지난 시즌 기록에서 그 당시 팀 이름(지금 이름과 다르면 제목에 쓰고 아래에 '지금: …')."""
    by = {}
    for r in rows:
        if r["team"] == k:
            by.setdefault(r["role"], []).append(r)
    rmk = rumor_slots().get(k, {}) if rm else {}
    leave = roster_leaving() if rm else {}
    filled = sum(1 for p in FA_ROLES if by.get(p))
    cells = []
    for p in ROSTER_SLOTS:
        rs = by.get(p, [])
        rmp = rmk.get(p, [])
        def pn(r, cls="pn"):
            until = f'~{r["until"][:7].replace("-", ".")}' if r["until"] else ""
            return (f'<span class="{cls}" role="button" tabindex="0" title="선수 프로필 보기" data-page="{esc(r["page"])}" data-nick="{esc(r["nick"])}"'
                    f' data-real="{esc(r["real"] or "")}" data-pos="{(r.get("pos") if isinstance(r, dict) else "") or FA_POS[p]}"'
                    f' data-team="{k}" data-until="{esc(until)}">{esc(r["nick"])}</span>')
        def rtag(x, small=False):
            t = rm_label(x["rm"])
            return f'<i class="in{" s" if small else ""} rm" title="{esc(x["rm"]["outlet"] + " · " + x["rm"]["title"])}">{t}</i>'
        if not rs:
            if rmp:      # 빈자리에 들어올 것 같은 선수(유력)
                more = "".join(f'<span class="subl">{pn(x, "pn sub")}{rtag(x, True)}</span>' for x in rmp[1:])
                cells.append(f'<li class="vac rmv"><span class="pk">{FA_POS[p]}</span>{pn(rmp[0])}{more}{rtag(rmp[0])}</li>')
            else:
                cells.append(f'<li class="vac"><span class="pk">{FA_POS[p]}</span><span class="pn">미정</span></li>')
            continue
        r = rs[0]
        IN_S = '<i class="in s">영입</i>'
        subs = "".join(f'<span class="subl">{pn(x, "pn sub")}{IN_S if x["joined"] else ""}</span>'
                       for x in rs[1:])      # 같은 포지션 선수가 더 있으면(후보 등) 이름을 모두 보여 줌
        subs += "".join(f'<span class="subl rml">{pn(x, "pn sub")}{rtag(x, True)}</span>' for x in rmp)
        lv = leave.get(r["page"])        # 이 선수가 다른 팀으로 갈 것 같다는 기사(계약은 남아 있음)
        out = (f'<span class="rmo" title="{esc(lv["outlet"] + " · " + lv["title"])}">➔ {team_logo(lv["team"])}{esc(team_short(lv["team"]))} '
               f'{"발표" if lv["official"] else "이적 유력"}</span>' if lv else "")
        cells.append(f'<li><span class="pk">{FA_POS[p]}</span>{pn(r)}{out}{subs}'
                     f'{"<i class=in>영입</i>" if r["joined"] else ""}</li>')
    anchor = "" if extra_cls else f' id="t-{k}"'              # 구단 안내의 '로스터 →'가 이 카드로
    return (f'<article class="rc{extra_cls}"{anchor} data-team="{k}" style="--tc:{team_color(k)}"><header>{team_logo(k, "logo big")}'
            f'<div>{_rc_title(k, name_then)}</div><span class="fill">{filled}/5</span></header>'
            f'<ul>{"".join(cells)}</ul></article>')


def _rc_title(k: str, name_then: str = "") -> str:
    if name_then and name_then.lower() != (TEAMS.get(k, {}).get("wiki") or "").lower():
        return f'<b title="그 당시 팀 이름">{esc(name_then)}</b><small>지금: {esc(team_name(k))}</small>'
    return f'<b>{esc(team_short(k))}</b><small>{esc(team_name(k))}</small>'


def narrow_roster(league: str, team: str) -> str:
    """휴대폰처럼 좁은 화면: 오른쪽 요약이 없어서, 팀을 고르면 그 팀 로스터를 목록 위에 접어서 보여 줌."""
    if team not in team_keys():
        return ""
    return (f'<details class="card rs-narrow" open><summary><span>{team_logo(team)} {esc(team_short(team))} 로스터</span>'
            f'<a href="/{league}/roster">전체 로스터 →</a><i aria-hidden="true">▾</i></summary>{roster_card(team, roster_rows(), " rc-narrow")}</details>')


def stove_strip(league: str) -> str:
    """소식 화면 맨 위(휴대폰): 스토브리그 진행 숫자. PC는 오른쪽 요약에 같은 숫자가 있음."""
    if not in_season(datetime.now(KST).date()):
        return ""
    cnt = fa_counts()
    return (f'<nav class="stove" aria-label="스토브리그 현황"><b>스토브리그</b>'
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
        card = roster_card(team, roster_rows(), " rc-side")
        box += (f'<section class="card"><h3><span>{team_logo(team)} {esc(team_short(team))} 로스터</span>'
                f'<a href="/{league}/roster">전체 로스터 →</a></h3>{card}</section>')
    else:
        box += ('<section class="card"><h3>팀 로스터</h3>'
                '<p class="hint">위에서 팀 로고를 누르면 그 팀 로스터가 보여요.</p></section>')
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
    sql, args = "SELECT * FROM items WHERE source != 'news_en'", []      # 영어 기사는 '유력' 판단에만 씀
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
        # 1행: 성격 배지(오피셜·단독·루머) + 제목 / 2행: 팀 · 매체 · 몇 분 전 — 배지는 하나만(신뢰도·NEW·출처 배지는 뺌)
        same = re.match(r"\s*\[(오피셜|공식|단독|소식통)\]", r["title"])   # 제목에 이미 [오피셜]·[단독]이 있으면 배지는 생략
        if kind in KIND and not (hot == 1 and kind == "official") and not same:   # '오피셜' 보기에선 모두 오피셜이라 생략
            label = "루머" if kind == "rumor" and lv == 1 else KIND[kind][0]
            kb = f'<span class="kb {KIND[kind][1]}">{label}</span>'
        tms = "".join(f'<span class="tm" title="{esc(team_name(k))}">{team_logo(k)}{esc(team_short(k))}</span>' for k in shown)
        srcb = ""
        outlet = "리그피디아" if r["source"] == "wiki" else esc(r["outlet"] or "")
        title = r["title"]
        ko = wiki_ko(title) if r["source"] == "wiki" else None
        tit = (f'{esc(ko)}<span class="orig">{esc(title)}</span>' if ko else esc(title))
        ovs = overseas_tag(title, team_short) if r["source"] == "news" else ""
        if ovs:
            tit += f'<span class="ovs">{esc(ovs)}</span>'
        cls = f'item kd-{kind} lv-{lv}' + (" new" if new else "") + (" grp" if rest else "") + (" spo" if is_spoiler(title) else "")
        ts = int(pub.timestamp() * 1000)
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
            f'{f"<span class=ol>{outlet}</span>" if outlet else ""}'
            f'<time class="rel" data-ts="{ts}" datetime="{kst.isoformat()}" title="{kst:%Y-%m-%d %H:%M} KST">{rel_time(pub, now)}</time></div></a>{more}</li>')

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

    farm = league == "lck" and not q          # 독버섯 심기(서버가 골격·판 목록을 그리고 static/farm.js가 내 점수·심은 상태를 덮어씀)
    main = f"""<div class="layout"><div>{farm_block() if farm else ""}
<section class="card fbar{" open" if custom else ""}" id="fbar" aria-label="보기와 필터">
<form class="srch" method="get" action="{base}" role="search">{"".join(f'<input type="hidden" name="{k}" value="{esc(str(v))}">' for k, v in (("team", team if team in TEAMS else ""),) if v != "")}
<input type="search" name="q" value="{esc(q)}" placeholder="선수·키워드 검색 (예: 커즈, 기인)" aria-label="선수·키워드 검색" enterkeyhint="search">
<button class="btn" type="submit">검색</button>{f'<a class="x" href="{esc(url(k=""))}" aria-label="검색 지우기">×</a>' if q else ""}</form>
{f'<p class="srch-head">‘{esc(q)}’ 검색 결과 {len(items)}건' + (f' · {esc(", ".join(t for t in terms if t != q))}도 함께 찾았어요' if len(terms) > 1 else "") + '</p>' if q else ""}
<div class="top"><nav class="view_tab" aria-label="보기">{view}</nav>
<button class="fbtn" type="button" id="fbtn" aria-expanded="{"true" if custom else "false"}" aria-controls="fbody">필터{f"<i>{nfilter}</i>" if nfilter else ""}</button>{ACT}</div>{MSG}
<div class="fbody" id="fbody"><div class="filter_bar">
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
    return shell(league, "news", "", main, ("news.js", "player.js") + (("farm.js",) if farm else ()), today, extra_attr=' data-teamable="1"')


# ── 이적·FA ─────────────────────────────────────────────────────────────
def fa_row_html(r, rm=None) -> str:
    """rm: 미정인 선수의 뉴스 기반 '유력'·'발표' 정보(rumor.py). 공식 상태는 그대로 두고 덧붙여 보여 줌."""
    def tm(k):
        return f'<span class="tm" title="{esc(team_name(k))}">{team_logo(k)}{esc(team_short(k))}</span>'
    pos = shown_pos(r["role"], rm if r["status"] == "fa" else None)
    coach = r["role"] not in FA_ROLES or pos in ("코치", "감독")
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
        lbl, cls = rm_label(rm), ("s-ann" if rm["official"] else "s-rm")
        d = rel_day(rm["published"])
        src = f'{rm["outlet"]}{" " + d if d else ""}'
        sub = [f'<a class="rm-src" href="{esc(rm["url"])}" target="_blank" rel="noopener" title="{esc(rm["title"])}">{esc(src)} 기사 ↗</a>']
    real = f'<small>{esc(r["real"])}</small>' if r["real"] else ""
    ak = r["team_to"] if r["status"] == "move" and r["team_to"] else r["team_from"]   # 아바타: 새 팀(이적)·원래 팀
    badge = team_logo(ak, "bdg") if logo_src(ak) else ""
    grp = ("감독" if r["role"] == "Head Coach" else "코치") if coach else pos
    dest = rm["team"] if rm and r["status"] == "fa" else (r["team_to"] if r["status"] == "move" else r["team_from"] if r["status"] == "stay" else "")
    return (f'<li class="fa-row" data-page="{esc(r["page"])}" data-s="{r["status"]}" data-p="{grp}" data-t="{r["team_from"]}"'
            f' data-nick="{esc(r["nick"])}" data-pos="{esc(pos)}" data-label="{lbl}" data-dest="{dest}">'
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


# ── 독버섯 심기: 첫 화면(서버) ─────────────────────────────────────────────
# 첫 HTML에 상태바(빈 밭 7칸)·진행 중 판·결과 내역을 '아직 아무것도 안 한 사람' 모양으로 그려 둠 → 자바스크립트가 내 점수·심은
# 상태를 얹을 때 아래 소식이 밀리지 않고, 자바스크립트를 안 돌리는 검색봇·미리보기에도 보임. static/farm.js의 bar()·openRow()·
# doneRow()·card()와 같은 모양(클래스·글자)이어야 함(바꾸면 둘 다). 그림은 farm_art 한 벌을 둘이 같이 씀.
def _tf_tug(it, show: bool) -> str:
    p, q = ("o", "x") if it["kind"] == "rumor" else ("a", "b")
    n = it.get("n") or 0
    if not show:
        return f'<div class="tf-tug"><span class="tf-none">{f"{n}명 참여 중 · 심으면 민심 공개" if n else "아직 아무도 안 심었어요"}</span></div>'
    a, b = it["tally"].get(p, 0), it["tally"].get(q, 0)
    m = a + b
    if not m:
        return '<div class="tf-tug"><span class="tf-none">아직 아무도 안 심었어요</span></div>'
    pa = round(100 * a / m)
    segs = "".join(f'<i class="{"a" if i < round(pa * 20 / 100) else "b"}"></i>' for i in range(20))
    lab = ("O", "X") if it["kind"] == "rumor" else (it["a_short"], it["b_short"])
    return (f'<div class="tf-tug"><div class="tf-tl"><span class="tf-pa">{esc(lab[0])} {pa}%</span><span class="tf-n">민심 {m}명</span>'
            f'<span class="tf-pb">{esc(lab[1])} {100 - pa}%</span></div><span class="tf-gauge">{segs}</span></div>')


def _tf_title(it) -> str:
    if it["kind"] == "rumor":
        stay = it["id"].endswith(":s")
        return f'<b>{esc(it["nick"])} · {esc(it["a_short"]) + " 잔류?" if stay else esc(it["a_short"]) + " → " + esc(it["b_short"])}</b>'
    return f'<b>{esc(it["a_label"])} vs {esc(it["b_label"])}</b>'


def _tf_open_row(it) -> str:
    stay = it["id"].endswith(":s")
    if it["kind"] == "rumor":
        src = (f'<span class="tf-src">{esc(it["tag"] or "유력")} · '
               f'<a href="{esc(it["url"])}" target="_blank" rel="noopener">{esc(it["outlet"])} 기사 ↗</a></span>')
        picks = [("o", "O 남는다" if stay else "O 간다"), ("x", "X 떠난다" if stay else "X 안 간다")]
        facts = f' data-nick="{esc(it["nick"])}" data-label="{esc(it["tag"] or "")}" data-dest="{esc(it["b"])}"'
    else:
        try:
            d = datetime.fromisoformat(it["published"]).astimezone(KST)
            when = f"{d.month}/{d.day} {d:%H:%M}"
        except (TypeError, ValueError):
            when = ""
        src = f'<span class="tf-src">{when} · {esc(it["title"])}</span>'
        picks = [("a", it["a_label"]), ("b", it["b_label"])]
        facts = ""
    btns = "".join(f'<button type="button" class="{"" if i else "tf-o"}" data-plant="{esc(it["id"])}" data-pick="{c}">{esc(label)}</button>'
                   for i, (c, label) in enumerate(picks))
    return (f'<li class="" data-item="{esc(it["id"])}"{facts}>{farm_art.plot(None, 48, "tf-empty")}<div class="tf-q">{_tf_title(it)}{src}</div>'
            f'{_tf_tug(it, False)}<div class="tf-act tf-ox">{btns}</div></li>')


def _tf_done_row(it) -> str:
    stay = it["id"].endswith(":s")
    if it["kind"] != "rumor":
        out = f'{esc(it["a_short"] if it["result"] == "a" else it["b_short"])} 승'
    elif it["result"] == "o":
        out = f'O · {esc(it["a_short"])} 잔류 확정' if stay else f'O · {esc(it["b_short"])} 이적 확정'
    else:
        out = "X · 잔류 안 함" if stay else f'X · {esc(it["b_short"])}행 아님'
    try:
        d = datetime.fromisoformat(it["resolved_at"]).astimezone(KST)
        day = f"{d.month}/{d.day}"
    except (TypeError, ValueError):
        day = ""
    n, w = it.get("n") or 0, it["tally"].get(it["result"], 0)
    verdict = ('<span class="tf-act tf-verdict">참여 없음</span>' if not n else
               '<span class="tf-act tf-verdict tf-v-major">민심 적중</span>' if w / n >= .5 else
               '<span class="tf-act tf-verdict tf-v-upset">역배 대이변!</span>' if w / n < .3 else
               '<span class="tf-act tf-verdict tf-v-minor">소수 적중</span>')
    return (f'<li class="tf-res" data-item="{esc(it["id"])}">{farm_art.plot("shroom", 40)}<div class="tf-q">{_tf_title(it)}'
            f'<span class="tf-src">결과 {out} · {day}</span></div>{_tf_tug(it, True)}{verdict}</li>')


def farm_block() -> str:
    try:
        board = farmd.board([])
    except Exception:  # noqa: BLE001  놀이 칸이라 실패해도 소식 화면은 그대로
        board = {"open": [], "mine": {}, "done": []}
    opn, done = board["open"], board["done"]
    holes = "".join(farm_art.plot(None, 28) for _ in range(7))
    bar = (f'<section class="card tf-bar" aria-label="내 버섯 농장">\n<div class="tf-field" title="수확한 버섯이 밭에 자라요">{holes}</div>\n'
           '<div class="tf-who"><span class="tf-tier">🌱 새싹 농부</span><small>다음 등급까지 5점 · <span class="tf-fcnt">밭 0/7칸</span></small></div>\n'
           '<div class="tf-num"><span><em class="tf-pts">0</em>농장 점수</span><span class="tf-stk"><em>0</em>연속 수확</span>'
           '<span title="오늘의 황금 버섯이 화면 어딘가에 숨어 있어요"><em>🔍</em>황금 버섯</span></div></section>')
    card = ""
    if opn or done:
        season = any(it["kind"] == "match" for it in opn)
        desc = ("경기 시작 10분 전까지 이길 팀 진영에 심어요. 맞히면 +1점, 30% 미만 소수 쪽이 맞으면 역배 +2점(10명 이상 참여한 판)." if season else
                "유력 기사가 맞을지 O·X 밭에 버섯을 심어요. 심으면 민심이 공개되고, 공식 확정되면 결과가 나와요. 맞히면 +1점, 30% 미만 소수 쪽이면 역배 +2점(10명 이상 참여한 판).")
        # 휴대폰 2개 · PC 4개(나머지는 '더 보기'): 화면 폭은 서버가 모르니 4개를 그리고 휴대폰에선 CSS로 2개만(tf-ssr)
        more = (f'<button type="button" class="tf-more{"" if len(opn) > 4 else " tf-mo"}" data-more="1">더 보기 · 전체 {len(opn)}개</button>'
                if len(opn) > 2 else "")
        open_panel = (f'<ul>{"".join(_tf_open_row(it) for it in opn[:4])}</ul>{more}' if opn else
                      '<p class="tf-emptymsg">지금 심을 판이 없어요. 새 유력 기사가 뜨면 생겨요.</p>')
        done_panel = (f'<ul>{"".join(_tf_done_row(it) for it in done)}</ul>' if done else '<p class="tf-emptymsg">아직 결과가 난 판이 없어요.</p>')
        card = (f'<section class="card tf-card tf-ssr" aria-label="독버섯 심기"><div class="tf-head"><h3>독버섯 심기 <small>{"오늘의 경기" if season else "스토브리그 편"}</small></h3>\n'
                f'<div class="tf-tabs" role="tablist"><button type="button" role="tab" data-tab="open" aria-selected="true">진행 중 <b>{len(opn)}</b></button>'
                f'<button type="button" role="tab" data-tab="done" aria-selected="false">결과 내역 <b>{len(done)}</b></button></div></div>\n'
                f'<p class="tf-desc">{desc}</p>\n<div class="tf-panel" data-panel="open">{open_panel}</div>\n'
                f'<div class="tf-panel" data-panel="done" hidden>{done_panel}</div></section>')
    data = json.dumps({**board, "art": farm_art.ART}, ensure_ascii=False).replace("<", "\\u003c")
    return f'<div id="tf" class="tf-wrap">{bar}{card}</div><script type="application/json" id="tf-data">{data}</script>'


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
    main = f"""{squad_toggle(league, "fa")}{page_head("이적 시장", "계약이 끝난 선수와 코치가 어디로 가는지 모았어요.")}{stove_dates(today)}{board}<section class="card panel fa" aria-label="조회와 필터">
<div class="ptop"><nav class="view_tab" id="grp" aria-label="묶어 보기"><a href="#" data-g="p">포지션별</a><a href="#" data-g="t">팀별</a><a href="#" data-g="s">상태별</a></nav>{ACT}</div>{MSG}
<div class="sum">{summ}</div>
<div class="chips" id="pos">
<button data-p="all">전체 포지션</button><button data-p="탑">탑</button><button data-p="정글">정글</button><button data-p="미드">미드</button><button data-p="원딜">원딜</button><button data-p="서폿">서폿</button><button data-p="감독">감독</button><button data-p="코치">코치</button>
</div>
<p class="src">팀은 원래 소속 기준이에요. 상태는 리그피디아에 공식 발표가 올라오면 바뀌고, <b class="st2 s-rm">유력</b>은 기사 제목을 보고 붙여요. {faupd}</p>
</section>
<section class="card">
<div class="tabs-wrap"><nav class="tabs" id="tabs" aria-label="원소속 팀">{nav}</nav></div>
<script type="application/json" id="th">{th}</script>
<ul class="list" id="falist">{"".join(fa_row_html(r, rms.get(r["page"])) for r in rows)}</ul>
</section>
{POPUP}"""
    return shell(league, "fa", "이적·FA", main, ("fa.js", "player.js"), today, scope="?what=fa")


# ── 로스터 ──────────────────────────────────────────────────────────────
def render_roster(league: str, season=None) -> str:
    """season: 스토브리그 기간 '{다음 시즌} 시즌(예정)'에서 열 때(지금 계약 기준 로스터 그대로, 표시만 그 시즌)."""
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
    ended = current_season(today) - 1 if stove_phase(today) else None     # 스토브리그 기간: 위 탭 '{ended} 시즌 로스터'
    past = " · ".join(f'<a href="/{league}/roster?season={y}">{y} 시즌</a>' for y in archive_years() if y != ended)
    head = (f'{team_toggle(league, "roster", season)}{page_head(f"{season} 시즌 로스터", "지금까지 계약으로 정해진 팀별 선수예요. 스토브리그가 끝날 때까지 계속 바뀌어요.")}'
            if season else f'{squad_toggle(league, "roster")}<p class="past-link">지난 시즌 로스터 보기: {past}</p>')
    main = f"""{head}<section class="card panel fa" aria-label="조회"><div class="ptop"><p class="src">리그피디아 계약 기준 현재 로스터{when} · 빗금 칸은 아직 미정인 자리, '영입'은 이번 스토브리그에 새로 온 사람 · <i class="in rm">유력</i>은 최근 기사 제목 기준 참고 표시(공식 확정 전) · 이름을 누르면 프로필</p>{ACT}</div>{MSG}
</section>
<div class="rgrid" id="rgrid">{cards}</div>{empty}
{POPUP}"""
    return shell(league, "roster", f"{season} 시즌 로스터" if season else "로스터", main, ("roster.js", "player.js"), today,
                 scope="?what=fa", season=season)


def _toggle(league, on, season, label, items):
    sq = f"?season={season}" if season else ""
    return f'<nav class="view_tab squad" aria-label="{label}">' + "".join(
        f'<a class="{"on" if k == on else ""}" href="/{league}{path}{sq}" data-sec="{k}"{" aria-current=page" if k == on else ""}>{t}</a>'
        for k, path, t in items) + "</nav>"


def stove_toggle(league: str, on: str, season=None) -> str:
    """'스토브리그' 탭 안: 이적 시장 | 구단별 | 행선지 맞히기 | 내맘대로 로스터."""
    if season:
        return _toggle(league, on, season, "스토브리그 보기", [("fa", "/fa", f"{season - 1} 스토브리그 이동")])
    return _toggle(league, on, None, "스토브리그 보기",
                   [("fa", "/fa", "이적 시장"), ("summary", "/summary", "구단별"), ("predict", "/predict", "행선지 맞히기"),
                    ("builder", "/builder", "내맘대로 로스터")])


def team_toggle(league: str, on: str, season=None) -> str:
    """'팀' 탭 안: 현재 로스터 | (스토브리그 기간) 방금 끝난 시즌 로스터 | 계약 만료 | 구단 안내."""
    if season:
        return _toggle(league, on, season, "팀 보기", [("roster", "/roster", f"{season} 로스터")])
    today = datetime.now(KST).date()
    ended = [("final", f"/roster?final={current_season(today) - 1}", f"{current_season(today) - 1} 시즌 로스터")] \
        if stove_phase(today) else []
    return _toggle(league, on, None, "팀 보기", [("roster", "/roster", "현재 로스터")] + ended +
                   [("contracts", "/contracts", "계약 만료"), ("teams", "/teams", "구단 안내")])


def squad_toggle(league: str, on: str, season=None) -> str:
    """(예전) '로스터·이적' 전환 → 이제 팀/스토브리그 탭 안 전환으로."""
    return team_toggle(league, on, season) if on == "roster" else stove_toggle(league, on, season)


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
        pos = shown_pos(r["role"])
        seen.add(r["page"])
        items.append((r["date"] or "", f'<li data-label="확정" data-dest="{r["team_to"]}">{tm(r["team_from"])}<span class="ar" aria-label="에서">➔</span>{tm(r["team_to"], r["team_to_name"])}'
                                       f'<span class="mv-who"><small>{pos}</small>{who(r, pos, r["team_to"] or "")}</span></li>'))
    for r in fa_rows:                       # 유력(뉴스 기준, 공식 확정 전): 점선으로 구분
        rm = (rms or {}).get(r["page"])
        if r["status"] != "fa" or not rm or rm["stay"]:
            continue
        pos = shown_pos(r["role"], rm)
        tag = rm_label(rm)
        items.append((rm["published"][:10], f'<li class="rm" data-label="{tag}" data-dest="{rm["team"]}">{tm(r["team_from"])}<span class="ar" aria-label="에서">➔</span>{tm(rm["team"])}'
                                            f'<span class="mv-who"><small>{pos}</small>{who(r, pos, rm["team"])}<em>{tag}</em></span></li>'))
    for r in roster_rows():                  # 계약이 남은 선수의 이적 유력
        lv = roster_leaving().get(r["page"])
        if not lv:
            continue
        pos = FA_POS.get(r["role"], r["role"])
        items.append((lv["published"][:10], f'<li class="rm" data-label="{"발표" if lv["official"] else "유력"}" data-dest="{lv["team"]}">{tm(r["team"])}<span class="ar" aria-label="에서">➔</span>{tm(lv["team"])}'
                                            f'<span class="mv-who"><small>{pos}</small>{who(r, pos, lv["team"])}<em>{"발표" if lv["official"] else "유력"}</em></span></li>'))
    for r in roster_rows():
        if r["joined"] and r["page"] not in seen:
            outside += 1
            pos = FA_POS.get(r["role"], r["role"])
            items.append(("", f'<li>{tm("")}<span class="ar" aria-label="에서">➔</span>{tm(r["team"])}'
                              f'<span class="mv-who"><small>{pos}</small>{who(r, pos, r["team"])}</span></li>'))
    if not items:
        return ""
    items.sort(key=lambda x: x[0], reverse=True)
    return (f'<details class="card moves" open><summary>이동 보드 <small>{len(items)}건{f" · LCK 밖에서 온 영입 {outside}건 포함" if outside else ""}</small></summary>'
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
    return {"title": f"{by + '의 ' if by else '내맘대로 '}{year} LCK 로스터 🍄",
            "desc": " | ".join(lines[:3]) + (" … 10개 팀 전부 보고 나도 짜 보기" if len(lines) > 3 else "")}


def render_builder(league: str, season=None, shared: str = "", by: str = "", code: str = "") -> str:
    today = datetime.now(KST).date()
    teams = [{"k": k, "short": team_short(k), "name": team_name(k), "color": team_color(k), "logo": logo_src(k) or ""}
             for k in team_keys()]
    data = json.dumps({"teams": teams, "people": people_list(), "pos": {k: FA_POS[k] for k in FA_ROLES}, "year": current_season(), "domain": SITE.get("domain") or "",
                       "shared": {"r": shared, "n": by} if code and shared else None},
                      ensure_ascii=False).replace("<", "\\u003c")
    main = f"""{stove_toggle(league, "builder") if not season else ""}<section class="card panel bld-head">
<h2>내맘대로 로스터 <small>{current_season()} 시즌 10개 팀 주전을 직접 골라 보세요</small></h2>
<p class="src">선수를 고른 뒤 빈칸을 누르세요. PC에서는 끌어다 놓아도 돼요. 짠 로스터는 이 브라우저에 저장되고, 이미지나 링크로 자랑할 수 있어요.</p>
<div class="bld-act"><button class="btn primary" type="button" id="bsave">이미지로 저장</button><button class="btn" type="button" id="bshare">링크로 공유</button>
<button class="btn" type="button" id="breset">지금 로스터로 되돌리기</button>{"".join(f'<button class="btn" type="button" data-arch="{y}">{y} 로스터 불러오기</button>' for y in archive_years())}<button class="btn" type="button" id="bclear">모두 비우기</button></div>
</section>
<div class="shared-bar" id="bshared" hidden></div>
<div class="bld">
<section class="card pool" aria-label="선수 목록"><div class="pool-f"><input type="search" id="bq" placeholder="선수 찾기" aria-label="선수 찾기">
<div class="chips" id="bpos"><button data-p="all" class="on">전체</button>{"".join(f'<button data-p="{k}">{FA_POS[k]}</button>' for k in FA_ROLES)}</div>
<label class="chk"><input type="checkbox" id="bfree"><span>아직 팀 없는 선수만</span></label>
<label class="chk"><input type="checkbox" id="block"><span>확정 선수 잠금 (빈자리만 채우기)</span></label></div>
<ul id="bpool"></ul></section>
<div class="bgrid" id="bgrid"></div>
</div>
{popular_rosters() if not season and not code else ""}
<script type="application/json" id="bdata">{data}</script>"""
    og = shared_roster_og(shared, by) if shared else None
    return shell(league, "builder", "내맘대로 로스터", main, ("builder.js",), today, season=season, og=og)


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
    return f"""<h2>티모의 버섯농장 소개</h2>
<h3>어떤 사이트인가요</h3>
<p><b>티모의 버섯농장</b>({esc(SITE.get("domain") or "teemofarm.com")})은 리그 오브 레전드(LoL) 이스포츠 팬이 스토브리그 이적 소식, 구단별 로스터, 리그 정보를 한곳에서 편하게 볼 수 있도록 개인이 취미로 만들어 운영하는 팬 사이트예요. 서버비는 후원과 광고·제휴 수익으로 충당해요.</p>
<h3>주요 기능</h3>
<ul>
<li><b>소식</b>: 구글 뉴스와 리그피디아 편집 기록을 모아, 같은 내용의 기사는 하나로 묶고 오피셜·루머를 구분해 보여 줘요.</li>
<li><b>로스터·이적</b>: 구단별 현재 로스터와 계약이 끝난 선수(FA)의 이적·잔류 현황을 정리해요.</li>
<li><b>내맘대로 로스터</b>: 다음 시즌 10개 팀 로스터를 내 마음대로 짜서 이미지로 저장하거나 링크로 공유할 수 있어요.</li>
<li><b>리그·구단 안내와 시즌 기록</b>: 리그 구조, 구단 이력, 지난 시즌 우승팀·로스터·이적을 볼 수 있어요.</li>
<li><b>밴들 광장·미니게임</b>: 로그인 없이 쓰는 대화방(밴들 광장)과 협곡 버섯 지뢰찾기가 있어요.</li>
</ul>
<h3>데이터 출처와 저작권</h3>
<p>로스터·계약·경기 정보는 <a href="https://lol.fandom.com" target="_blank" rel="noopener">Leaguepedia</a>(CC BY-SA 3.0)를 바탕으로 자동으로 모아요. 뉴스는 구글 뉴스 RSS에서 제목과 링크만 보여 주며, 기사 본문의 저작권은 각 언론사에 있어요. 리그 오브 레전드 관련 명칭과 자산은 Riot Games, Inc.의 상표예요.</p>
<h3>문의</h3>
<p>오류 제보, 데이터 수정 요청, 제휴 문의: {_mail()}</p>"""


def privacy_body() -> str:
    return f"""<h2>개인정보처리방침</h2>
<p>티모의 버섯농장(이하 '사이트')은 이용자의 개인정보를 소중히 여기며 「개인정보 보호법」 등 관련 법령을 지켜요. 사이트는 회원가입이 없고, 이름·전화번호·이메일 같은 정보를 묻거나 모으지 않아요.</p>
<h3>1. 서버에 저장되는 정보</h3>
<ul>
<li><b>밴들 광장(대화방)</b>: 이용자가 쓴 메시지, 닉네임, 작성 시각, 도배를 막기 위해 브라우저가 임의로 만든 번호. 최근 메시지 200개만 보관하고 그보다 오래된 것은 자동으로 지워져요.</li>
<li><b>로스터 공유</b>: '링크 공유하기'를 누른 경우 그 로스터 구성과 입력한 닉네임(선택). 공유 링크가 계속 열리도록 보관해요.</li>
<li><b>접속 기록</b>: 사이트 서버는 IP 주소 등 접속 기록을 따로 남기지 않아요.</li>
</ul>
<h3>2. 이용자 브라우저에만 저장되는 정보</h3>
<p>화면 테마, 스포 방지 설정, 읽은 기사, 찜한 선수, 작업 중인 로스터, 미니게임 기록, 밴들 광장 닉네임은 이용자 브라우저의 저장 공간(localStorage)에만 남고 서버로 보내지 않아요. 브라우저의 사이트 데이터를 지우면 함께 지워져요.</p>
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
<p>본인이 쓴 밴들 광장 메시지나 공유한 로스터를 지우고 싶으면 아래 이메일로 알려 주세요. 확인 후 지체 없이 지워 드려요.</p>
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
            f'<span class="tp-titles">{esc(p.get("titles", ""))}</span><p>{esc(p.get("summary", ""))}</p>'
            f'{f"<div class=tp-links>{btns}</div>" if btns else ""}{team_history(p)}</section>')


def team_history(p) -> str:
    """구단 이력(접힘): 팀명 변천사(계보) + 연도별 연혁."""
    lin, hist = p.get("lineage") or [], p.get("history") or []
    if not (lin or hist):
        return ""
    chain = " <i>←</i> ".join(f'<b class="cur">{esc(n)}</b>' if i == len(lin) - 1 else f"<span>{esc(n)}</span>"
                             for i, n in reversed(list(enumerate(lin))))                  # 지금 이름부터
    events = "".join(f'<li><em>{esc(e["year"])}</em>{esc(e["text"])}</li>' for e in reversed(hist))   # 최근 연도가 위로
    return (f'<details class="tp-hist"><summary>구단 변천사 및 주요 이력<i aria-hidden="true">▾</i></summary>'
            f'{f"<p class=tp-lin>{chain}</p>" if lin else ""}{f"<ul class=tp-tl>{events}</ul>" if events else ""}</details>')


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
        teams = '<p class="lsec">참가 구단 · 누르면 그 팀 소식</p>' + teams
    road = ('<p class="lsec">연간 시즌 로드맵</p>' + flow) if flow else ""   # 파이썬 3.10·3.11에서도 되게 f-string 밖에서
    return (f'<details class="card lguide" style="--la:{esc(g.get("accent", "var(--primary)"))}"{" open" if opened else ""}>'
            f'<summary>{esc(g["code"])} 리그 안내 <small>{esc(meta)}</small><i aria-hidden="true">▾</i></summary>'
            f'<div class="lg-body"><header>{head}<div><b>{esc(g.get("flag", ""))} {esc(g["name"])} ({esc(g["code"])})</b>'
            f'<small>{esc(g.get("region", ""))} · {esc(meta)}</small></div></header>{road}<div class="litems">{items}</div>{teams}</div></details>')


# ── 지난 시즌 기록(아카이브) ───────────────────────────────────────────
def _tname(key, name):
    return (f'<span class="tm">{team_logo(key)}{esc(team_short(key))}</span>' if key
            else f'<span class="tm ext">{esc(name or "LCK 밖")}</span>')


def render_archive(league: str, sec: str, year: int, t_sel: str = "", inline: bool = False) -> str:
    """?season=2026 처럼 지난 시즌을 고르면: 소식=시즌 요약, 로스터=최종 로스터, 이적=그 시즌 스토브리그 이동, 일정=순위표."""
    today = datetime.now(KST).date()
    d = archive.get(year)
    active = {"": "news", "roster": "roster", "fa": "fa", "schedule": "schedule", "results": "results"}.get(sec, "news")
    title = f"{year} 시즌 기록"
    if not d:
        main = (f'<div class="card soon"><h2>{year} 시즌 기록을 모으는 중이에요</h2>'
                f'<p>리그피디아에서 순위·로스터·이적 기록을 한 번 받아 저장해 둬요(처음 한 번만, 1~2분).<br>잠시 뒤 새로고침해 주세요.</p></div>')
        return shell(league, active, title, (team_toggle(league, "final") if inline else "") + main, (), today,
                     season=None if inline else year)
    stages, champ = d.get("stages") or [], d.get("champion") or {}
    roster, moves = d.get("roster") or [], d.get("moves") or []
    note = ('<p class="src">일부 기록은 아직 못 받았어요(리그피디아 요청 한도). 30분 뒤 다시 받아요.</p>' if d.get("missing") else "")

    def champ_card():
        if not champ:
            return ""
        return (f'<section class="card champ"><div><small>{esc(champ["name"])} 우승</small>'
                f'<b>{_tname(champ["wkey"], champ["winner"])}</b><p>결승 {esc(champ["score"])} · 상대 {_tname(champ["lkey"], champ["loser"])} · {esc(champ["date"])}</p></div></section>')

    def standings(limit=None):
        out = ""
        for st in reversed(stages):          # 최근 대회부터
            rows = st["table"][:limit] if limit else st["table"]
            trs = "".join(
                f'<tr><td class="pl">{esc(str(r["place"]))}</td><td>{_tname(r["key"], r["team"])}</td>'
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
        return (f'<details class="card moves" open><summary>{year - 1} 스토브리그 이동 <small>{year} 시즌 준비 · {year - 1}.11 ~ {year}.01 · {len(moves)}건</small></summary>'
                f'<ul>{lis}</ul></details>')

    if active == "roster":
        tours = d.get("rosters") or []
        default = max((i for i, t in enumerate(tours) if not t.get("playoff")), default=len(tours) - 1)  # 마지막 정규 대회
        try:
            ti = int(t_sel) if str(t_sel).strip() != "" else default
        except ValueError:
            ti = default
        ti = ti if 0 <= ti < len(tours) else default
        src_rows = tours[ti]["roster"] if tours else roster
        rows = [{"team": r["team"], "role": r["role"], "page": r["page"], "nick": r["nick"], "real": "", "until": "", "joined": 0}
                for r in src_rows if r["team"]]
        then = {r["team"]: r.get("team_name", "") for r in src_rows if r["team"]}
        cards = "".join(roster_card(k, rows, rm=False, name_then=then.get(k, "")) for k in team_keys() if any(r["team"] == k for r in rows))
        tabs = ""
        if len(tours) > 1:
            tabs = ('<nav class="view_tab ar-tours" aria-label="대회 고르기">' + "".join(
                f'<a class="{"on" if i == ti else ""}" href="/{league}/roster?{"final" if inline else "season"}={year}&amp;t={i}"{" aria-current=page" if i == ti else ""}>'
                f'{esc(tour_ko(t["page"], "LCK"))}</a>' for i, t in enumerate(tours)) + '</nav>')
        what = f'{esc(tour_ko(tours[ti]["page"], "LCK"))}에 등록된 로스터' if tours else '시즌 마지막 정규 대회에 등록된 로스터'
        head = team_toggle(league, "final") if inline else squad_toggle(league, "roster", year)
        main = (f'{head}{tabs}<section class="card panel"><p class="src">{year} {what}(리그피디아) · '
                f'팀 이름은 그 당시 이름, 로고는 지금 것</p>{note}</section>'
                f'<div class="rgrid">{cards or "<p class=note>로스터 기록이 없어요.</p>"}</div>{POPUP}')
        scripts = ("player.js",)
    elif active == "fa":
        main = f'{squad_toggle(league, "fa", year)}{note}{moves_list()}'
        scripts = ()
    elif active in ("schedule", "results"):           # 경기 기록이 없는 지난 시즌: 일정·결과 모두 우승·순위표 기록
        main = f'{sched_toggle(league, active, year)}{champ_card()}{note}<div class="stands">{standings()}</div>'
        scripts = ()
    else:
        main = (f'{champ_card()}{note}<div class="stands">{standings(limit=3)}</div>'
                f'<p class="note"><a href="/{league}/results?season={year}">전체 순위표 보기 →</a></p>{moves_list(limit=8)}')
        scripts = ()
    if inline:                                         # 지금 화면 안(시즌 선택 그대로 '지금')
        return shell(league, "roster", f"{year} 시즌 로스터", main, scripts, today)
    return shell(league, active, title, main, scripts, today, season=year)


# ── 일정·결과 ───────────────────────────────────────────────────────────
STOVE_SCH = """<section class="card stove-sch"><h2>스토브리그 주요 일정</h2><ol>
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
    m = re.fullmatch(r"Rounds (\d+)-(\d+)", t)          # 'Rounds 1-2' → 정규 1·2라운드, 'Rounds 3-5' → 정규 3~5라운드
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return f"정규 {a}{'·' if b - a == 1 else '~'}{b}라운드"
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
        if src:   # 해외 로고는 리그피디아 이미지 서버로 넘어갈 수 있음: 다른 사이트 표시(Referer)가 있으면 회색 그림을 줘서 빼고 부름
            return f'<img class="logo" src="{esc(src)}" alt="" width="20" height="20" loading="lazy" referrerpolicy="no-referrer">'
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


def stove_card(today) -> str:
    """스토브리그 주요 일정(LCK): 코치 영입·FA 개장·KeSPA컵·새 시즌 개막(리그피디아에 일정이 올라오면 날짜가 채워짐)."""
    cs = current_season(today)
    opening = f'<li><time>미정</time><b>{cs} LCK 개막</b><small>리그피디아에 일정이 올라오면 여기에 저절로 떠요</small></li>'
    first = min((_sch_at(m) for m in schedule.get("lck").get("matches") or []
                 if _m_year(m) == str(cs) and _sch_at(m)), default=None)
    if first:
        f = first.astimezone(KST)
        opening = (f'<li class="{"done" if f.date() <= today else ""}"><time>{f.month}.{f.day:02d}</time><b>{cs} LCK 개막</b>'
                   f'<small>{f:%H:%M} 첫 경기 · 리그피디아 일정 기준</small></li>')
    return STOVE_SCH.format(opening=opening)


def render_stove(league: str) -> str:
    """스토브리그 > 일정: 주요 일정과 FA 현황 숫자."""
    today = datetime.now(KST).date()
    cnt = fa_counts()
    nums = (f'<section class="card stove-now"><h3>지금 스토브리그 <a href="/{league}/fa">이적·FA 보기 →</a></h3>'
            f'<div class="mini"><a class="m" href="/{league}/fa?s=move"><b>{cnt.get("move", 0)}</b>이적 확정</a>'
            f'<a href="/{league}/fa?s=stay"><b>{cnt.get("stay", 0)}</b>잔류</a>'
            f'<a href="/{league}/fa?s=fa"><b>{cnt.get("fa", 0)}</b>미정</a></div></section>')
    main = (f'{stove_toggle(league, "stove")}{stove_card(today)}{nums}'
            f'<p class="note"><a href="/{league}/schedule">새 시즌 대회 일정·경기는 \'시즌\'에서 볼 수 있어요 →</a></p>')
    return shell(league, "stove", "스토브리그 일정", main, (), today)


def render_teams(league: str) -> str:
    """팀 > 구단 안내: 팀마다 정식 이름·창단·주요 성적·소개·변천사."""
    today = datetime.now(KST).date()
    cards = "".join(
        f'<div class="tcard" id="tc-{k}">{team_profile(k)}<p class="tgo"><a href="/{league}/roster#t-{k}">로스터 →</a>'
        f'<a href="/{league}?team={k}">소식 →</a></p></div>' for k in team_keys() if PROFILES.get(k))
    main = f'{team_toggle(league, "teams")}{lineage_map(league)}<div class="tgrid">{cards or "<p class=note>구단 정보가 아직 없어요.</p>"}</div>'
    return shell(league, "teams", "구단 안내", main, (), today)


def sched_toggle(league: str, on: str, season=None) -> str:
    """'일정·결과' 탭 안의 두 화면 전환(로스터·이적 탭과 같은 방식)."""
    sq = f"?season={season}" if season else ""

    def a(k, path, label):
        return f'<a class="{"on" if k == on else ""}" href="/{league}{path}{sq}" data-sec="{k}"{" aria-current=page" if k == on else ""}>{label}</a>'
    return f'<nav class="view_tab squad" aria-label="시즌 보기">{a("schedule", "/schedule", "일정")}{a("results", "/results", "결과·순위")}</nav>'


def _m_year(m) -> str:
    return _page_year(m.get("page", ""))


def tours_card(d, year: str, lg_name: str, today) -> str:
    """그 시즌 대회 일정(리그피디아 대회 목록): 'LCK 컵 · 1.14 ~ 3.1 · 진행 중'."""
    tours = [t for t in d.get("tours") or [] if f"/{year} Season/" in t.get("page", "")]
    if not tours:
        return ""
    iso = today.isoformat()

    def md(x):
        return f"{int(x[5:7])}.{int(x[8:10])}" if len(x or "") >= 10 else "미정"

    lis = ""
    for t in tours:
        a, b = t.get("start") or "", t.get("end") or ""
        stt = ("done", "끝") if b and b < iso else ("now", "진행 중") if a and a <= iso else ("up", "예정")
        lis += (f'<li class="{stt[0]}"><b>{esc(tour_ko(t["page"], lg_name))}</b>'
                f'<time>{md(a)} ~ {md(b)}</time><span class="tst">{stt[1]}</span></li>')
    return f'<section class="card tours"><h3>{esc(year)} {esc(lg_name)} 대회 일정</h3><ul>{lis}</ul></section>'


def render_schedule(league: str, pick=None, mode: str = "plan") -> str:
    """일정(mode='plan'): 고른 리그의 앞으로 일정 — 스토브리그 주요 일정(LCK), 대회 일정, 지금 경기 중·다가오는 경기.
    결과(mode='results'): 끝난 경기·우승·순위·경기 상세. 고른 시즌에 아직 결과가 없으면(비시즌) 가장 최근 시즌 결과.
    pick: 시즌 선택에서 고른 지난 시즌(LCK)."""
    today = datetime.now(KST).date()
    now = datetime.now(timezone.utc)
    d = schedule.get(league)
    lg_name = LEAGUES[league]["name"]
    T = SchTeams(d)
    cs = current_season(today)
    has_pick = bool(LEAGUES[league]["enabled"])            # 시즌 선택이 있는 리그(지금은 LCK)
    pick = pick if has_pick else None
    active = "results" if mode == "results" else "schedule"
    toggle = sched_toggle(league, active, pick)
    title = f"{lg_name} {'결과' if mode == 'results' else '일정'}"

    def page(main, scripts=()):
        return shell(league, active, title, toggle + main, scripts, today, season=pick)

    if not d.get("season"):
        msg = ("리그피디아에서 일정을 받아 오지 못했어요. 잠시 뒤 다시 들어와 주세요." if d.get("error")
               else "리그피디아에서 일정·결과를 받아 오는 중이에요(서버를 켠 뒤 1~2분).<br>잠시 뒤 새로고침해 주세요.")
        return page(f'<div class="card soon"><h2>일정·결과</h2><p>{msg}</p></div>')

    ms = [m for m in d.get("matches") or [] if _sch_at(m)]
    live = [m for m in ms if _sch_state(m, now) == "live"]
    up = [m for m in ms if _sch_state(m, now) == "up"]
    done = [m for m in ms if _sch_state(m, now) == "done"]

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
    tabs_html = f'<section class="card sch-tabs"><div class="tabs-wrap"><nav class="tabs" id="tabs" aria-label="팀">{nav}</nav></div></section>'
    empty = '<p class="note sch-empty" id="schEmpty" hidden>이 팀 경기가 없어요.</p>'
    upd = ""
    try:
        u = datetime.fromisoformat(d["at"]).astimezone(KST)
        upd = f" · {u.month}/{u.day} {u:%H:%M} 갱신"
    except (KeyError, ValueError):
        pass
    foot = (f'<p class="note">일정·결과·순위·경기 기록 출처 리그피디아 · 챔피언 이미지 Riot Games Data Dragon{upd} · '
            f'경기 앞뒤엔 5분마다, 경기가 없는 기간엔 몇 시간마다 새로 받아요 · 시간은 한국 시간</p>')

    if mode != "results":
        # ── 일정 ──
        year = str(pick or cs)
        stove = ""                                   # 스토브리그 일정은 '스토브리그 > 일정'으로 옮김
        tours = tours_card(d, year, lg_name, today)
        if not tours:
            tours = (f'<section class="card tours"><h3>{year} {esc(lg_name)} 대회 일정</h3>'
                     f'<p class="hint">아직 리그피디아에 올라오지 않았어요. 올라오면 여기에 바로 보여요.</p></section>')
        blocks = ""
        if not pick or pick == cs:                    # 지금 시즌이거나 개막 전 다음 시즌(미리 보기)
            if live:
                blocks += f'<section class="card sblock live-b"><h3><i class="live-dot" aria-hidden="true"></i>지금 경기 중</h3>{match_days(live, now, T, lg_name)}</section>'
            if up:
                first_days = sorted({_sch_at(m).astimezone(KST).date() for m in up})
                cut = first_days[min(len(first_days), 5) - 1]
                soon = [m for m in up if _sch_at(m).astimezone(KST).date() <= cut]
                later = [m for m in up if _sch_at(m).astimezone(KST).date() > cut]
                more = (f'<details class="smore"><summary>이후 일정 <b class="n">{len(later)}</b>경기 더 보기</summary>{match_days(later, now, T, lg_name)}</details>'
                        if later else "")
                blocks += f'<section class="card sblock"><h3>다가오는 경기</h3>{match_days(soon, now, T, lg_name)}{more}</section>'
        go = f'<p class="note"><a href="/{league}/results{f"?season={pick}" if pick else ""}">지난 경기 결과·순위는 \'결과\'에서 볼 수 있어요 →</a></p>'
        if blocks:
            main = f'{stove}{tours}<div class="sch-grid one"><div>{tabs_html}{blocks}{empty}</div></div>{go}{POPUP}{foot}'
            return page(main, ("player.js", "schedule.js"))
        none = ("" if pick and pick != cs else '<section class="card sblock"><h3>다가오는 경기</h3><p class="hint">예정된 경기가 아직 없어요.</p></section>')
        return page(f'{stove}{tours}{none}{go}{foot}')

    # ── 결과 ──
    years = sorted({_m_year(m) for m in done if _m_year(m)}, reverse=True)
    show = str(pick) if pick else (years[0] if years else str(cs))
    done_s = [m for m in done if _m_year(m) == show]
    season_over = not any(_m_year(m) == show for m in up + live)
    champ = ""
    fin = [m for m in done_s if m["playoff"] and m["tab"] in ("Finals", "Final") and m["win"] in ("1", "2")]
    if fin and season_over:
        m = fin[-1]
        a, b = ((m["k1"], m["t1"], m["s1"]), (m["k2"], m["t2"], m["s2"]))
        win, lose = (a, b) if m["win"] == "1" else (b, a)
        champ = (f'<section class="card champ sch-champ"><div><small>{esc(lg_name)} {esc(tour_ko(m["page"], lg_name))} 우승 · {show}</small>'
                 f'<b>{T.tname(win[0], win[1])}</b><p class="sc-hide">결승 {esc(win[2])}:{esc(lose[2])} · 상대 {T.tname(lose[0], lose[1])} · '
                 f'{_sch_at(m).astimezone(KST):%Y.%m.%d}</p></div></section>')
    why = ""
    if not pick and show != str(cs):
        why = f'<small>{cs} 시즌은 아직 경기 전이라 가장 최근 시즌 결과를 보여 줘요</small>'
    head = f'<h2 class="res-title">{show} 시즌 결과{why}</h2>'
    blocks = ""
    if done_s:
        last_days = sorted({_sch_at(m).astimezone(KST).date() for m in done_s}, reverse=True)
        cut = last_days[min(len(last_days), 4) - 1]
        recent = [m for m in done_s if _sch_at(m).astimezone(KST).date() >= cut]
        older = [m for m in done_s if _sch_at(m).astimezone(KST).date() < cut]
        more = (f'<details class="smore"><summary>지난 결과 <b class="n">{len(older)}</b>경기 더 보기</summary>{match_days(older, now, T, lg_name, True)}</details>'
                if older else "")
        blocks = (f'<section class="card sblock"><h3>{"마지막 결과" if season_over else "최근 결과"}'
                  f'<small>경기를 누르면 밴픽·선수 기록이 보여요</small></h3>{match_days(recent, now, T, lg_name, True)}{more}</section>')
    else:
        blocks = '<div class="card soon"><h2>아직 끝난 경기가 없어요</h2><p>경기가 끝나면 여기에 결과가 쌓여요.</p></div>'
    stand = ""
    if st.get("groups") and _page_year(st.get("page") or "") == show:
        tables = ""
        for g in st["groups"]:
            trs = "".join(
                f'<tr data-team="{esc(r["key"])}"><td class="pl">{esc(str(r["place"]))}</td><td>{T.tname(r["key"], r["team"])}</td>'
                f'<td>{esc(r["w"])}승 {esc(r["l"])}패</td><td class="gd">{esc(r["gw"])}–{esc(r["gl"])}</td></tr>' for r in g["table"])
            gh = f'<h4>{esc(g["name"])}</h4>' if g["name"] else ""
            tables += (f'{gh}'
                       f'<table><thead><tr><th>순위</th><th>팀</th><th>매치</th><th>세트</th></tr></thead><tbody>{trs}</tbody></table>')
        stand = (f'<section class="card stand sch-stand"><h3>{esc(lg_name)} {esc(tour_ko(st.get("page") or st["name"], lg_name))} 순위 <small>{show}</small></h3>{tables}'
                 f'<p class="src">리그피디아 순위표 기준{" · 그룹은 서로 맞붙은 팀끼리 묶어 표시" if len(st["groups"]) > 1 else ""}</p></section>')
    main = f"""{head}{champ}
<div class="sch-grid"><div>
{tabs_html}
{blocks}{empty}
</div><aside>{stand}</aside></div>
{POPUP}
{foot}"""
    return page(main, ("player.js", "schedule.js"))


def render_soon(league: str) -> str:
    today = datetime.now(KST).date()
    lg = LEAGUES[league]
    main = (f'<div class="soon-bar">지금은 {esc(lg["name"])} 소식·로스터는 준비 중이에요. 아래에서 리그 정보를 먼저 볼 수 있어요. '
            f'<a href="/lck">LCK 보러 가기 →</a></div>'
            + (f'<a class="card sch-go" href="/{league}/schedule"><b>{esc(lg["name"])} 일정·결과·순위</b>는 지금 볼 수 있어요 →</a>'
               if lg.get("wiki") else "")
            + league_guide(league, opened=True))
    return shell(league, "", lg["name"], main, (), today)


# ── 스토브리그 새 화면 공통 ─────────────────────────────────────────────
def page_head(title: str, sub: str, stats: str = "") -> str:
    """화면 맨 위 한 줄: 제목 · 무엇을 하는 화면인지 · 핵심 숫자."""
    return (f'<header class="phead"><div><h2>{title}</h2><p>{sub}</p></div>'
            f'{f"<div class=pstat>{stats}</div>" if stats else ""}</header>')


def stove_dates(today) -> str:
    """이적 시장 맨 위 한 줄: 스토브리그 주요 날짜(지난 건 흐리게)."""
    cs = current_season(today)
    first = min((_sch_at(m) for m in schedule.get("lck").get("matches") or []
                 if _m_year(m) == str(cs) and _sch_at(m)), default=None)
    items = [("11.15", "코치 영입 시작", True), ("11.17", "선수 FA 개장", True), ("미정", "KeSPA컵", False)]
    if first:
        f = first.astimezone(KST)
        items.append((f"{f.month}.{f.day:02d}", f"{cs} LCK 개막", f.date() <= today))
    else:
        items.append(("미정", f"{cs} LCK 개막", False))
    lis = "".join(f'<li class="{"done" if d else ""}"><time>{t}</time>{esc(n)}</li>' for t, n, d in items)
    return f'<section class="sdates" aria-label="스토브리그 일정"><ol>{lis}</ol></section>'


# ── 스토브리그 > 구단별 ─────────────────────────────────────────────────
def _chip(p, cls="", extra="", pos=None):
    pos = pos or FA_POS.get(p.get("role", ""), p.get("role", ""))
    return f'<span class="pc {cls}" title="{esc(extra)}">{esc(p["nick"])}<small>{esc(pos)}</small></span>'


def render_summary(league: str) -> str:
    """구단마다 이번 겨울 들어온 사람·나간 사람·재계약·미정, 그리고 기사로만 나온 소문(따로)."""
    today = datetime.now(KST).date()
    keys = team_keys()
    sm = stv.team_summary(keys)
    rms = rumor_slots()
    cards = []
    for k in keys:
        v = sm[k]
        rumor = [x for xs in rms.get(k, {}).values() for x in xs if not x["rm"]["stay"]]
        lines = []

        def line(label, cls, chips):
            if chips:
                lines.append(f'<div class="sl {cls}"><em>{label}</em><div>{chips}</div></div>')
        line("들어옴", "in", "".join(_chip(p, "in", f'{team_short(p["from"])}에서' if p.get("from") else "LCK 밖에서") for p in v["in"]))
        line("나감", "out", "".join(_chip(p, "out", "→ " + (team_short(p["to"]) if p.get("to") else (p.get("to_name") or "LCK 밖"))) for p in v["out"]))
        line("재계약", "stay", "".join(_chip(p, "stay") for p in v["stay"]))
        line("소문", "rm", "".join(_chip(x, "rm", f'{x["rm"]["outlet"]}: {x["rm"]["title"]}', x.get("pos")) for x in rumor))
        line("미정", "open", "".join(_chip(p, "open") for p in v["open"]))
        moved = len(v["in"]) + len(v["out"]) + len(v["stay"])
        d = parse_day(v["updated"]) if v["updated"] else None
        meta = f"확정 {moved}건" + (f" · 마지막 {d.month}/{d.day}" if d else "")
        cards.append((-moved, -len(rumor), keys.index(k),
                      f'<article class="scard" id="m-{k}" style="--tc:{team_color(k)}"><header>{team_logo(k, "logo big")}'
                      f'<b>{esc(team_name(k))}</b><small>{meta}</small></header>{"".join(lines) or "<p class=sl-empty>아직 변동이 없어요</p>"}</article>'))
    cards.sort()
    cnt = fa_counts()
    stats = (f'<span><b>{cnt.get("move", 0)}</b>이적</span><span><b>{cnt.get("stay", 0)}</b>재계약</span>'
             f'<span><b>{cnt.get("fa", 0)}</b>미정</span>')
    main = (f'{stove_toggle(league, "summary")}<div class="stack">'
            + page_head("구단별", "이번 겨울 구단마다 누가 오고 갔는지 모았어요. 확정은 리그피디아 기록, 소문은 기사 제목 기준이에요.", stats)
            + f'<div class="sgrid">{"".join(c[3] for c in cards)}</div>'
            + f'<p class="plinks"><a href="/{league}/feed.xml">이적 소식 RSS</a></p></div>')
    return shell(league, "summary", "구단별 이적", main, (), today)


# ── 다음 시즌 미리 보기(스토브리그 기간 '2027 시즌 · 예정') ─────────────────
def render_preview(league: str) -> str:
    """개막 전 다음 시즌 한눈에: 개막까지 남은 날, 대회 일정, 팀별 주전 확정 현황."""
    today = datetime.now(KST).date()
    cs = current_season(today)
    d = schedule.get(league)
    first = min((_sch_at(m) for m in d.get("matches") or [] if _m_year(m) == str(cs) and _sch_at(m)), default=None)
    if first:
        f = first.astimezone(KST)
        left = (f.date() - today).days
        stats = (f'<span><b>D-{left}</b>{f.month}.{f.day} 개막</span>' if left > 0 else '<span><b>오늘</b>개막</span>')
    else:
        stats = '<span><b>미정</b>개막일</span>'
    tours = tours_card(d, str(cs), LEAGUES[league]["name"], today) or (
        f'<section class="card tours"><h3>{cs} {esc(LEAGUES[league]["name"])} 대회 일정</h3>'
        f'<p class="hint">아직 리그피디아에 올라오지 않았어요. 올라오면 여기에 바로 보여요.</p></section>')
    rows = roster_rows()
    cards, total = [], 0
    for k in team_keys():
        by = {}
        for r in rows:
            if r["team"] == k:
                by.setdefault(r["role"], r)
        n = sum(1 for p in FA_ROLES if p in by)
        total += n
        lis = "".join(f'<li class="{"" if p in by else "vac"}"><span class="pk">{FA_POS[p]}</span>'
                      f'<b>{esc(by[p]["nick"]) if p in by else "미정"}</b></li>' for p in FA_ROLES)
        cards.append((-n, team_keys().index(k),
                      f'<article class="scard pv" style="--tc:{team_color(k)}"><header>{team_logo(k, "logo big")}'
                      f'<b>{esc(team_name(k))}</b><small class="{"full" if n == 5 else ""}">주전 {n}/5</small></header>'
                      f'<ul class="pv5">{lis}</ul></article>'))
    cards.sort()
    full = sum(1 for c in cards if c[0] == -5)
    stats += f'<span><b>{full}</b>팀 주전 완성</span>'
    main = (f'<div class="stack">'
            + page_head(f"{cs} 시즌 개막 준비", "대회 일정과 지금까지 계약으로 정해진 팀별 주전이에요. 스토브리그 동안 계속 바뀌어요.", stats)
            + tours
            + f'<div class="sgrid">{"".join(c[2] for c in cards)}</div>'
            + f'<p class="plinks"><a href="/{league}/roster?season={cs}">팀별 로스터 자세히 →</a> · '
              f'<a href="/{league}/schedule?season={cs}">경기 일정 →</a></p></div>')
    return shell(league, "news", f"{cs} 시즌 개막 준비", main, (), today, season=cs)


# ── 스토브리그 > 행선지 맞히기 ──────────────────────────────────────────
def render_predict(league: str) -> str:
    today = datetime.now(KST).date()
    keys = team_keys()
    with db() as c:
        fa = [dict(r) for r in c.execute("SELECT * FROM fa WHERE league='lck'").fetchall()]
    rms = rumors(fa)
    tal = vote.tally()
    order = lambda r: (keys.index(r["team_from"]) if r["team_from"] in keys else 99, r["role"])   # noqa: E731

    def row(r):
        rm = rms.get(r["page"])
        pos = shown_pos(r["role"], rm)
        lab = rm_label(rm) if rm else ""
        hint = (f'<span class="vh-rm">{esc(team_short(rm["team"]))} {lab}'
                f'<small>{esc(rm["outlet"])}</small></span>' if rm else "")
        return (f'<li class="vrow" data-page="{esc(r["page"])}" data-nick="{esc(r["nick"])}" data-pos="{pos}"'
                f' data-label="{lab}" data-dest="{rm["team"] if rm else ""}">'
                f'<span class="av tc" style="--tc:{team_color(r["team_from"])}">{esc(pos)}</span>'
                f'<div class="vwho"><b>{esc(r["nick"])}</b><small>{team_logo(r["team_from"])}{esc(team_short(r["team_from"]))}에서</small></div>'
                f'{hint}<span class="vtop"></span><button type="button" class="btn vpick">고르기</button></li>')
    players = [r for r in fa if r["role"] in FA_ROLES]
    hot = sorted((r for r in players if r["status"] == "fa" and r["page"] in rms), key=order)
    rest = sorted((r for r in players if r["status"] == "fa" and r["page"] not in rms), key=order)
    done = []
    for r in sorted((r for r in players if r["status"] != "fa" and tal.get(r["page"])), key=order):
        ans = r["team_to"] if r["status"] == "move" else r["team_from"]
        t = tal[r["page"]]
        n = sum(t.values())
        right = t.get(ans or vote.OTHER, 0)
        lbl = f'{team_short(ans)} {"재계약" if r["status"] == "stay" else "이적"}' if ans else "LCK 밖"
        done.append(f'<li class="vdone"><b>{esc(r["nick"])}</b><span>정답 {esc(lbl)}</span><em>{round(100 * right / n)}% 맞힘</em><small>{n}표</small></li>')
    votes = sum(sum(v.values()) for v in tal.values())
    sheet = ('<dialog class="vsheet" id="vsheet"><form method="dialog"><button class="pol-x" aria-label="닫기">✕</button></form>'
             '<p class="vs-t"><b id="vs-nick"></b> 어디로 갈까요?</p><div class="vopts">'
             + "".join(f'<button type="button" data-c="{k}">{team_logo(k)}<span>{esc(team_short(k))}</span></button>' for k in keys)
             + f'<button type="button" data-c="{vote.OTHER}"><span>LCK 밖</span></button></div>'
             '<p class="vs-n">발표 전까지는 몇 번이든 바꿀 수 있어요.</p></dialog>')
    lists = ""
    if hot:
        lists += f'<section class="card vsec"><h3>기사가 나온 선수 <small>{len(hot)}명</small></h3><ul class="vlist">{"".join(row(r) for r in hot)}</ul></section>'
    if rest:
        lists += (f'<details class="card vsec"{"" if hot else " open"}><summary><h3>나머지 미정 선수 <small>{len(rest)}명</small></h3></summary>'
                  f'<ul class="vlist">{"".join(row(r) for r in rest)}</ul></details>')
    if not (hot or rest):
        lists = '<p class="note">지금은 행선지가 안 정해진 선수가 없어요.</p>'
    if done:
        lists += f'<section class="card vsec"><h3>정답이 나온 선수</h3><ul class="vlist">{"".join(done)}</ul></section>'
    stats = f'<span><b>{len(hot) + len(rest)}</b>미정</span><span><b>{votes}</b>표</span>'
    main = (f'{stove_toggle(league, "predict")}<div class="stack">'
            + page_head("행선지 맞히기", "행선지가 안 정해진 선수, 어디로 갈 것 같나요? 발표가 나면 정답과 맞힌 비율을 알려 드려요.", stats)
            + lists + source_board() + f'</div>{sheet}')
    return shell(league, "predict", "행선지 맞히기", main, ("predict.js",), today)


def source_board() -> str:
    """소식통 성적표: 결과가 난 예측이 있는 매체만 표로, 나머지는 '결과 기다리는 기사'로."""
    preds = stv.predictions()
    acc = [a for a in stv.accuracy(preds) if a["hit"] + a["miss"]]
    res = {"hit": ("맞음", "h"), "miss": ("틀림", "m"), "wait": ("대기", "w")}
    table = "".join(f'<tr><th>{esc(a["outlet"])}</th><td><b>{a["rate"]}%</b></td><td>{a["hit"]}/{a["hit"] + a["miss"]}</td>'
                    f'<td class="w">{a["wait"] or ""}</td></tr>' for a in acc)

    def item(p):
        lbl, cls = res[p["result"]]
        return (f'<li><span class="pr {cls}">{lbl}</span><b>{esc(p["nick"])}</b><span class="to">{esc(team_short(p["team"]))}'
                f'{" 잔류" if p["stay"] else ""}</span><a href="{esc(p["url"])}" target="_blank" rel="noopener">{esc(p["outlet"])}</a></li>')
    waiting = [p for p in preds if p["result"] == "wait"]
    decided = [p for p in preds if p["result"] != "wait"]
    body = (f'<table class="acct"><thead><tr><th>매체</th><td>적중률</td><td>맞힘</td><td>대기</td></tr></thead><tbody>{table}</tbody></table>'
            if acc else '<p class="note">아직 발표로 확인된 기사가 없어요. 발표가 나는 대로 채워져요.</p>')
    if decided:
        body += f'<ul class="plist">{"".join(item(p) for p in decided[:10])}</ul>'
    if waiting:
        body += (f'<details class="pwait"><summary>발표를 기다리는 기사 {len(waiting)}건</summary>'
                 f'<ul class="plist">{"".join(item(p) for p in waiting[:20])}</ul></details>')
    return (f'<section class="card acc"><h3>소식통 성적표 <small>최근 2주</small></h3>'
            f'<p class="sub">단독·소식통 기사가 실제 발표와 맞았는지 세어 봤어요.</p>{body}</section>')


# ── 팀 > 계약 만료 ──────────────────────────────────────────────────────
def render_contracts(league: str) -> str:
    today = datetime.now(KST).date()
    rows = stv.contracts()
    by_year = {}
    for r in rows:
        by_year.setdefault((r["until"] or "")[:4] or "미공개", []).append(r)
    secs = []
    for y, rs in by_year.items():
        def li(r):
            real = f'<small>{esc(r["real"])}</small>' if r["real"] else ""
            until = ("~" + r["until"][:7].replace("-", ".")) if r["until"] else "날짜 미공개"
            return (f'<li><span class="tm">{team_logo(r["team"])}{esc(team_short(r["team"]))}</span>'
                    f'<span class="ps">{esc(FA_POS.get(r["role"], r["role"]))}</span><b>{esc(r["nick"])}</b>{real}<em>{until}</em></li>')
        title = f"{y}년에 끝나요" if y != "미공개" else "계약 기간 미공개"
        secs.append(f'<section class="card ctr" id="y-{y}"><h3>{title} <small>{len(rs)}명</small></h3><ul>{"".join(li(r) for r in rs)}</ul></section>')
    jump = "".join(f'<a href="#y-{y}">{y}</a>' for y in by_year)
    stats = "".join(f'<span><b>{len(v)}</b>{y}</span>' for y, v in list(by_year.items())[:2] if y != "미공개")
    main = (f'{team_toggle(league, "contracts")}<div class="stack">'
            + page_head("계약 만료", "지금 로스터의 계약이 언제 끝나는지 모았어요. 계약이 끝나는 해 11월에 FA가 돼요.", stats)
            + (f'<nav class="chips yjump">{jump}</nav>' if len(by_year) > 1 else "")
            + ("".join(secs) or '<p class="note">로스터 정보를 모으는 중이에요.</p>') + "</div>")
    return shell(league, "contracts", "계약 만료", main, (), today)


# ── 로스터 짜기 > 인기 로스터 ───────────────────────────────────────────
def popular_rosters() -> str:
    """공유된 로스터가 모이면 팀·자리마다 가장 많이 고른 선수. 모이기 전엔 아무것도 안 보여 줌."""
    keys = team_keys()
    pop = stv.popular(keys)
    if not pop["teams"]:
        return ""
    nick = {p["page"]: (p.get("ko") or p["nick"]) for p in people_list()}
    cards = []
    for k in keys:
        lines = []
        for role in stv.ROLES:
            top = pop["teams"][k][role]
            if top:
                pg, n = top[0]
                lines.append(f'<li><span>{FA_POS[role]}</span><b>{esc(nick.get(pg, pg.split(" (")[0]))}</b><em>{round(100 * n / pop["n"])}%</em></li>')
            else:
                lines.append(f'<li><span>{FA_POS[role]}</span><i>-</i></li>')
        cards.append(f'<div class="prc" style="--tc:{team_color(k)}"><p>{team_logo(k)}<b>{esc(team_short(k))}</b></p><ul>{"".join(lines)}</ul></div>')
    return (f'<section class="card poprs"><h3>다들 이렇게 짰어요 <small>공유된 로스터 {pop["n"]}개</small></h3>'
            f'<div class="prgrid">{"".join(cards)}</div></section>')


# ── 팀 > 구단 안내: 계보 ───────────────────────────────────────────────
def lineage_map(league: str) -> str:
    rows = []
    for k in team_keys():
        lin = (PROFILES.get(k) or {}).get("lineage") or []
        if not lin:
            continue
        chain = '<i class="ln" aria-hidden="true"></i>'.join(
            f'<span class="lgp{" cur" if i == len(lin) - 1 else ""}">{esc(n)}</span>' for i, n in enumerate(lin))
        rows.append(f'<li style="--tc:{team_color(k)}"><a class="lt" href="#tc-{k}">{team_logo(k)}<b>{esc(team_short(k))}</b></a><div class="lchain">{chain}</div></li>')
    if not rows:
        return ""
    return f'<section class="card lmap"><h3>구단 계보 <small>왼쪽이 옛 이름</small></h3><ul>{"".join(rows)}</ul></section>'
