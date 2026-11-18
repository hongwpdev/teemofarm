"""수집: Leaguepedia 팀 페이지 편집 기록."""
import json
import time
import urllib.parse
from datetime import datetime

from .config import REQUEST_GAP, TEAMS, WIKI_API, WIKI_BASE, log
from .core import http_get, save, set_status, to_utc_iso


def poll_wiki(gap=None):
    for key, t in TEAMS.items():
        if not t.get("wiki"):
            continue
        time.sleep(REQUEST_GAP if gap is None else gap)
        try:
            q = urllib.parse.urlencode({
                "action": "query", "prop": "revisions", "titles": t["wiki"], "redirects": 1,
                "rvprop": "ids|timestamp|user|comment|flags", "rvlimit": 20,
                "format": "json", "formatversion": 2,
            })
            data = json.loads(http_get(f"{WIKI_API}?{q}"))
            rows = []
            pages = data.get("query", {}).get("pages", [])
            if not pages or pages[0].get("missing"):
                set_status(key, "wiki", False, f"위키 페이지 없음: {t['wiki']}")
                log.warning("wiki %s: page missing (%s)", key, t["wiki"])
                continue
            for p in pages:
                page = p.get("title", t["wiki"])
                for rv in p.get("revisions", []):
                    if rv.get("minor"):
                        continue  # 사소한 수정은 건너뜀
                    ts = datetime.fromisoformat(rv["timestamp"].replace("Z", "+00:00"))
                    rows.append({
                        "id": f"wiki:{rv['revid']}", "team": key, "source": "wiki",
                        "title": rv.get("comment") or "(편집 요약 없음)",
                        "url": f"{WIKI_BASE}{urllib.parse.quote(page.replace(' ', '_'))}?diff={rv['revid']}",
                        "outlet": f"Leaguepedia · {rv.get('user', '')}",
                        "published": to_utc_iso(ts),
                    })
            n = save(rows)
            set_status(key, "wiki", True, f"새 항목 {n}건")
            log.info("wiki %s: %d new", key, n)
        except Exception as e:  # noqa: BLE001
            set_status(key, "wiki", False, str(e)[:120])
            log.warning("wiki %s failed: %s", key, e)
