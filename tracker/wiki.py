"""수집: Leaguepedia 팀 페이지 편집 기록.
요청을 줄이려고 먼저 10팀 문서의 마지막 편집 번호를 한 번에 확인하고(요청 1번), 지난번과 달라진 팀만 편집 기록을 받음.
마지막으로 본 편집 번호는 DB(meta)에 저장해서 서버를 다시 켜도 처음부터 다시 받지 않음."""
import urllib.parse
from datetime import datetime

from .cargo import api_get
from .config import TEAMS, WIKI_BASE, log
from .core import db, save, set_status, to_utc_iso


def _seen(key: str) -> str:
    with db() as c:
        r = c.execute("SELECT v FROM meta WHERE k=?", (f"wiki_rev:{key}",)).fetchone()
    return r[0] if r else ""


def _set_seen(key: str, rev: str):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (f"wiki_rev:{key}", rev))


def latest_revs(titles):
    """문서 이름 목록 → {문서 이름(설정에 적힌 그대로): (실제 제목, 마지막 편집 번호)} — 요청 1번(최대 50개)."""
    data = api_get({"action": "query", "prop": "revisions", "titles": "|".join(titles), "redirects": 1,
                    "rvprop": "ids", "formatversion": 2})
    if data.get("error"):
        raise RuntimeError((data["error"] or {}).get("info", "api error"))
    q = data.get("query", {})
    alias = {}                                        # 설정의 이름 → 최종 제목(대소문자 정리·넘겨주기 따라감)
    for x in (q.get("normalized") or []) + (q.get("redirects") or []):
        alias[x["from"]] = x["to"]
    final = {}
    for t in titles:
        n, hops = t, 0
        while n in alias and hops < 5:
            n, hops = alias[n], hops + 1
        final[t] = n
    pages = {p.get("title"): p for p in q.get("pages", [])}
    out = {}
    for t in titles:
        p = pages.get(final[t])
        if p and not p.get("missing") and p.get("revisions"):
            out[t] = (p["title"], str(p["revisions"][0]["revid"]))
    return out


def poll_wiki(gap=None):
    teams = {k: t for k, t in TEAMS.items() if t.get("wiki")}
    try:
        latest = latest_revs([t["wiki"] for t in teams.values()])
    except Exception as e:  # noqa: BLE001
        for key in teams:
            set_status(key, "wiki", False, str(e)[:120])
        log.warning("wiki check failed: %s", e)
        return
    changed = 0
    for key, t in teams.items():
        if t["wiki"] not in latest:
            set_status(key, "wiki", False, f"위키 페이지 없음: {t['wiki']}")
            log.warning("wiki %s: page missing (%s)", key, t["wiki"])
            continue
        page, rev = latest[t["wiki"]]
        if rev == _seen(key):
            set_status(key, "wiki", True, "새 항목 0건")
            continue
        changed += 1
        try:
            data = api_get({"action": "query", "prop": "revisions", "titles": page,
                            "rvprop": "ids|timestamp|user|comment|flags", "rvlimit": 20, "formatversion": 2})
            if data.get("error"):
                raise RuntimeError((data["error"] or {}).get("info", "api error"))
            rows = []
            for p in data.get("query", {}).get("pages", []):
                title = p.get("title", page)
                for rv in p.get("revisions", []):
                    if rv.get("minor"):
                        continue  # 사소한 수정은 건너뜀
                    ts = datetime.fromisoformat(rv["timestamp"].replace("Z", "+00:00"))
                    rows.append({
                        "id": f"wiki:{rv['revid']}", "team": key, "source": "wiki",
                        "title": rv.get("comment") or "(편집 요약 없음)",
                        "url": f"{WIKI_BASE}{urllib.parse.quote(title.replace(' ', '_'))}?diff={rv['revid']}",
                        "outlet": f"Leaguepedia · {rv.get('user', '')}",
                        "published": to_utc_iso(ts),
                    })
            n = save(rows)
            _set_seen(key, rev)                          # 저장까지 끝난 뒤에만 '봤음'으로
            set_status(key, "wiki", True, f"새 항목 {n}건")
            log.info("wiki %s: %d new", key, n)
        except Exception as e:  # noqa: BLE001
            set_status(key, "wiki", False, str(e)[:120])
            log.warning("wiki %s failed: %s", key, e)
    log.info("wiki: %d of %d pages changed", changed, len(teams))
