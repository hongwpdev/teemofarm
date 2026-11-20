"""이적 소식 알림: 팀별 RSS 주소(/lck/feed.xml?team=t1)와 디스코드 알림(설정했을 때만).
대상은 오피셜·단독·유력 같은 이적 기사(LoL 기사만). 디스코드 웹훅 주소는 비밀이라 저장소에 넣지 않고 환경변수 DISCORD_WEBHOOK으로."""
import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

from .classify import article_kind, news_teams
from .config import SITE_NAME, TEAMS, log
from .core import db
from .filters import is_lol_news

KINDS = ("official", "rumor")
LABEL = {"official": "오피셜", "rumor": "유력"}
# 이적 기사 표시: 이 말 중 하나가 제목에 있어야 함('합류 후 100승' 같은 경기 기사 제외)
MARKS = ("오피셜", "공식", "단독", "소식통", "유력", "임박", "합의", "예정", "근접", "영입", "재계약", "결별",
         "계약 종료", "계약 만료", "계약 연장", "잔류", "FA", "이적")
RUMOR = ("단독", "소식통", "유력", "임박", "합의", "예정", "근접", "협상", "설")
WEBHOOK = os.getenv("DISCORD_WEBHOOK", "").strip()
NOTIFY_SEC = 180
MAX_PER_RUN = 5


def stove_news(days: int = 7, team: str = "", since: str = ""):
    """최근 이적 기사(제목 같은 건 하나로): [{"title","url","outlet","published","first_seen","kind","teams"}] 최신순."""
    lim = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db() as c:
        rows = c.execute("SELECT title, MIN(url) url, MIN(outlet) outlet, MAX(published) published, MIN(first_seen) first_seen "
                         "FROM items WHERE source='news' AND published >= ? GROUP BY title ORDER BY published DESC", (lim,)).fetchall()
    out = []
    for r in rows:
        t = r["title"]
        if since and (r["first_seen"] or "") <= since:
            continue
        kind = article_kind(t, "news", r["outlet"] or "")
        if kind not in KINDS or not is_lol_news(t) or not any(w in t for w in MARKS):
            continue
        if "오피셜" not in t and "공식" not in t and any(w in t for w in RUMOR):
            kind = "rumor"
        teams = news_teams(t, [])
        if team and team not in teams:
            continue
        out.append({**dict(r), "kind": kind, "teams": teams})
    return out


def rss(origin: str, league: str, team: str = "") -> str:
    name = TEAMS.get(team, {}).get("name") if team else ""
    title = f"{SITE_NAME} · {name + ' ' if name else ''}이적 소식"
    link = f"{origin}/{league}" + (f"?team={team}" if team else "")
    items = []
    for n in stove_news(team=team)[:50]:
        try:
            when = format_datetime(datetime.fromisoformat(n["published"]))
        except ValueError:
            when = ""
        head = n["title"] if n["title"].startswith("[") else f"[{LABEL[n['kind']]}] {n['title']}"
        items.append(f"<item><title>{escape(head)}</title><link>{escape(n['url'])}</link>"
                     f"<guid isPermaLink=\"false\">{escape(n['url'])}</guid><source url=\"{escape(link)}\">{escape(n['outlet'] or '')}</source>"
                     + (f"<pubDate>{when}</pubDate>" if when else "") + "</item>")
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
            f"<title>{escape(title)}</title><link>{escape(link)}</link><description>{escape('오피셜·단독·유력 이적 기사')}</description>"
            f"<language>ko</language>{''.join(items)}</channel></rss>")


# ── 디스코드 ────────────────────────────────────────────────────────────
def _post(content: str):
    req = urllib.request.Request(WEBHOOK, data=json.dumps({"content": content[:1900]}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "teemofarm (notify)"})
    urllib.request.urlopen(req, timeout=15).read()


def _meta(k, v=None):
    with db() as c:
        if v is None:
            r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
            return r["v"] if r else ""
        c.execute("INSERT OR REPLACE INTO meta(k, v) VALUES(?, ?)", (k, v))


def notify_once():
    last = _meta("discord_at")
    if not last:                                   # 처음 켰을 때는 지난 기사로 도배하지 않게 지금부터
        _meta("discord_at", datetime.now(timezone.utc).isoformat())
        return 0
    news = sorted(stove_news(days=2, since=last), key=lambda n: n["first_seen"])[:MAX_PER_RUN]
    for n in news:
        teams = " ".join(TEAMS.get(k, {}).get("short", k.upper()) for k in n["teams"] if k != "lck")
        _post(f"🍄 {'' if n['title'].startswith('[') else '**[' + LABEL[n['kind']] + ']** '}{n['title']}\n{(teams + ' · ') if teams else ''}{n['outlet'] or ''}\n<{n['url']}>")
        _meta("discord_at", n["first_seen"])
        time.sleep(1.5)
    return len(news)


def start():
    if not WEBHOOK:
        return

    def loop():
        time.sleep(90)
        while True:
            try:
                notify_once()
            except Exception as e:  # noqa: BLE001
                log.warning("discord notify failed: %s", e)
            time.sleep(NOTIFY_SEC)
    threading.Thread(target=loop, daemon=True).start()
