"""웹 서버: 주소 나누기, 정적 파일·로고, API, 시작."""
import base64
import html
import gzip
import hashlib
import json
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import archive, champs, chat, jobs, maint, matchinfo, player_extra, riot, schedule, share, teamlogos
from ..cargo import RATE_MSG, is_rate_limit
from ..config import DEFAULT_LEAGUE, FA_INTERVAL, LEAGUES, NEWS_INTERVAL, PORT, WIKI_INTERVAL, log
from ..core import db, init_db
from ..fa import player_info
from ..logos import TEAM_LOGOS
from . import views

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
STATIC_TYPES = {".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8"}
STATIC = {}       # 파일 이름 -> (내용, 종류, gzip 내용)  시작할 때 한 번 읽어 둠
ZIP_TYPES = ("text/", "application/javascript", "application/json")
LOGO_PNG = {k: base64.b64decode(v) for k, v in TEAM_LOGOS.items()}
try:
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "og.jpg"), "rb") as _f:
        OG_JPG = _f.read()
except OSError:
    OG_JPG = b""


def load_static():
    h = hashlib.sha1()
    for name in sorted(os.listdir(STATIC_DIR)):
        ext = os.path.splitext(name)[1]
        if ext in STATIC_TYPES:
            with open(os.path.join(STATIC_DIR, name), "rb") as f:
                data = f.read()
            STATIC[name] = (data, STATIC_TYPES[ext], gzip.compress(data, 6))
            h.update(data)
    for k in sorted(LOGO_PNG):               # 로고가 바뀌어도 주소가 바뀌게
        h.update(LOGO_PNG[k])
    views.STATIC_VER = h.hexdigest()[:8]     # 파일이 바뀌면 주소의 ?v= 가 바뀌어 브라우저가 새로 받음


def parse_hot(v: str) -> int:
    return 0 if v == "0" else 2 if v == "2" else 1


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.1: 연결 하나로 HTML·CSS·JS·로고를 이어서 받음(Tailscale처럼 멀리 돌아가는 연결에서 훨씬 빠름)
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        one = lambda k, d="": qs.get(k, [d])[0]   # noqa: E731
        parts = [p for p in u.path.split("/") if p]

        # 예전 주소 호환: / → /lck, /fa → /lck/fa (쿼리 그대로)
        if u.path in ("/", "/fa"):
            dest = f"/{DEFAULT_LEAGUE}" + ("/fa" if u.path == "/fa" else "")
            return self._redirect(dest + (f"?{u.query}" if u.query else ""))
        if parts and parts[0] == "static" and len(parts) == 2 and parts[1] in STATIC:
            data, ctype, zipped = STATIC[parts[1]]
            return self._send(200, data, ctype, cache="public, max-age=31536000, immutable" if "v" in qs else "no-cache",
                              zipped=zipped)
        if parts and parts[0] == "logo" and len(parts) == 2 and parts[1].endswith(".png") and parts[1][:-4] in LOGO_PNG:
            return self._send(200, LOGO_PNG[parts[1][:-4]], "image/png",
                              cache="public, max-age=31536000, immutable" if "v" in qs else "public, max-age=86400")
        if len(parts) == 2 and parts[0] == "tlogo":        # 해외 팀 로고(리그피디아에서 받아 둔 것)
            hit = teamlogos.read(parts[1])
            if not hit:
                return self._send(404, b"", "image/png", cache="no-store")
            return self._send(200, hit[0], hit[1], cache="public, max-age=31536000, immutable" if "v" in qs else "public, max-age=86400")
        if len(parts) == 2 and parts[0] == "s":            # 공유 로스터 짧은 주소
            hit = share.get(parts[1])
            if not hit:
                return self._send(404, "공유한 로스터를 찾을 수 없어요. <a href='/lck/builder'>로스터 짜기로</a>".encode(), "text/html; charset=utf-8")
            page = views.render_builder(DEFAULT_LEAGUE, None, hit[0], hit[1], code=parts[1])
            page = page.replace("{{ORIGIN}}", self._origin()).replace("{{PATH}}", html.escape(u.path, quote=True))
            return self._send(200, page.encode(), "text/html; charset=utf-8", cache="public, max-age=0, s-maxage=300")
        if u.path == "/img/og.jpg":                       # 링크 미리보기 그림
            return self._send(200, OG_JPG, "image/jpeg", cache="public, max-age=604800") if OG_JPG else self._send(404, b"", "image/jpeg")
        if u.path == "/img/shroom.png":
            if riot.ICON["png"]:
                return self._send(200, riot.ICON["png"], "image/png", cache="public, max-age=604800")
            return self._send(404, b"", "image/png", cache="no-store")
        if u.path == "/api/archive":                      # 로스터 짜기 '지난 시즌 불러오기'
            try:
                y = int(one("year") or 0)
            except ValueError:
                y = 0
            d = archive.get(y) if y in archive.archive_years() else None
            body = json.dumps({"ready": bool(d), "roster": (d or {}).get("roster") or []}, ensure_ascii=False).encode()
            return self._send(200, body, "application/json; charset=utf-8", cache="no-cache")
        if u.path == "/api/people":                       # 찜·로스터 짜기용: 선수 목록(닉네임·한글 닉네임·본명·팀·포지션)
            return self._send(200, json.dumps(views.people_list(), ensure_ascii=False).encode(),
                              "application/json; charset=utf-8", cache="no-cache")
        if u.path == "/api/player":
            try:
                info = player_info(one("page"))
                info["extra"] = player_extra.get(one("page").strip())    # 생년월일·시그니처 챔피언·SNS(있으면)
                body, code = json.dumps(info, ensure_ascii=False), 200
            except Exception as e:  # noqa: BLE001
                log.warning("player %s failed: %s", one("page"), e)
                msg = RATE_MSG if is_rate_limit(e) else "정보를 불러오지 못했어요. 잠시 뒤 다시 눌러 보세요"
                body, code = json.dumps({"error": str(e)[:120], "msg": msg}, ensure_ascii=False), 502
            return self._send(code, body.encode(), "application/json; charset=utf-8")
        if u.path == "/api/items":
            with db() as c:
                rows = [dict(r) for r in c.execute("SELECT * FROM items ORDER BY published DESC LIMIT 300").fetchall()]
            return self._send(200, json.dumps(rows, ensure_ascii=False).encode(), "application/json")
        if u.path == "/api/status":
            st = jobs.FA_MANUAL if one("what") == "fa" else jobs.MANUAL
            return self._send(200, json.dumps({"running": st["running"], "last_done": st["last_done"],
                                               "done": list(st.get("done") or [])}).encode(), "application/json")
        if u.path == "/api/chat":
            try:
                after = int(one("after", "0") or 0)
            except ValueError:
                after = 0
            body = json.dumps(chat.fetch(after, one("cid")), ensure_ascii=False).encode()
            return self._send(200, body, "application/json; charset=utf-8", cache="no-store")
        if u.path == "/api/schedule":                     # 일정·결과·순위(리그피디아에서 받아 둔 그대로)
            lg = one("league", DEFAULT_LEAGUE)
            return self._send(200, json.dumps(schedule.get(lg if lg in LEAGUES else DEFAULT_LEAGUE), ensure_ascii=False).encode(),
                              "application/json; charset=utf-8", cache="no-cache")
        if u.path == "/api/match":                        # 경기 상세(세트별 밴픽·선수·챔피언·KDA). 일정에 있는 경기만
            lg, mid = one("league", DEFAULT_LEAGUE), one("id")
            m = next((x for x in (schedule.get(lg).get("matches") or []) if x["id"] == mid), None) if lg in LEAGUES and mid else None
            if not m:
                return self._send(404, json.dumps({"msg": "경기를 찾을 수 없어요"}, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            try:
                d = matchinfo.get(mid)
                names = {g[s]["team"] for g in d["games"] for s in ("blue", "red")} | {m["t1"], m["t2"]}
                d["teams"] = views.match_teams(lg, names)
                d["match"] = {k: m[k] for k in ("t1", "t2", "s1", "s2", "win", "at", "bo", "tab", "page")}
                body, code = json.dumps(d, ensure_ascii=False), 200
            except Exception as e:  # noqa: BLE001
                log.warning("match %s failed: %s", mid, e)
                msg = RATE_MSG if is_rate_limit(e) else "경기 기록을 불러오지 못했어요. 잠시 뒤 다시 눌러 보세요"
                body, code = json.dumps({"msg": msg}, ensure_ascii=False), 502
            return self._send(code, body.encode(), "application/json; charset=utf-8", cache="no-cache")
        if u.path == "/healthz":
            return self._send(200, b"ok", "text/plain")
        if u.path in ("/about", "/privacy"):               # 사이트 소개·개인정보처리방침(애드센스 심사용)
            page = views.render_policy(u.path[1:]).replace("{{ORIGIN}}", self._origin()).replace("{{PATH}}", u.path)
            return self._send(200, page.encode(), "text/html; charset=utf-8", cache="public, max-age=0, s-maxage=300")
        if u.path == "/ads.txt":                           # 애드센스 판매자 확인(site.json에 client를 넣으면 생김)
            txt = views.ads_txt()
            return self._send(200 if txt else 404, txt.encode(), "text/plain; charset=utf-8", cache="public, max-age=3600")

        # 리그 화면: /<리그>[/roster|/fa|/schedule]
        if parts and parts[0] in LEAGUES and len(parts) <= 2:
            league, sec = parts[0], (parts[1] if len(parts) == 2 else "")
            try:
                season = int(one("season") or 0)
            except ValueError:
                season = 0
            season = season if season in archive.archive_years() else None
            if not LEAGUES[league]["enabled"]:          # 아직 켜지지 않은 리그: 일정·결과만, 나머지는 '곧 추가'
                page = views.render_schedule(league) if sec == "schedule" and LEAGUES[league].get("wiki") else views.render_soon(league)
            elif season and sec in ("", "roster", "fa", "schedule"):
                page = views.render_archive(league, sec, season)
            elif sec == "":
                page = views.render_news(league, one("team"), one("src", "all"), parse_hot(one("hot", "0" if one("q").strip() else "1")),
                                         one("from"), one("to"), one("q"))
            elif sec == "roster":
                page = views.render_roster(league)
            elif sec == "fa":
                page = views.render_fa(league)
            elif sec == "schedule":
                page = views.render_schedule(league)
            elif sec == "builder":
                page = views.render_builder(league, season, one("r"), one("n"))
            elif sec == "game":
                page = views.render_game(league)
            else:
                page = None
            if page is not None:
                page = page.replace("{{ORIGIN}}", self._origin()).replace("{{PATH}}", html.escape(u.path + (f"?{u.query}" if u.query else ""), quote=True))
                return self._send(200, page.encode(), "text/html; charset=utf-8",
                                  cache="public, max-age=0, s-maxage=30")
        self._send(404, "찾는 화면이 없어요. <a href='/'>처음으로</a>".encode(), "text/html; charset=utf-8")

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/refresh":
            fa = urllib.parse.parse_qs(u.query).get("what", [""])[0] == "fa"
            res = jobs.request_manual_fa() if fa else jobs.request_manual()
            return self._send(200, json.dumps(res).encode(), "application/json")
        if u.path == "/api/share":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n).decode("utf-8")) if 0 < n <= 8192 else {}
                code = share.make(str(data.get("r") or ""), str(data.get("n") or ""))
                return self._send(200, json.dumps({"code": code}).encode(), "application/json")
            except Exception as e:  # noqa: BLE001
                return self._send(400, json.dumps({"msg": str(e)[:80]}, ensure_ascii=False).encode(), "application/json; charset=utf-8")
        if u.path == "/api/chat":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n).decode("utf-8")) if 0 < n <= 4096 else None
            except (ValueError, UnicodeDecodeError):
                data = None
            if not isinstance(data, dict):
                code, res = 400, {"msg": "보낼 수 없는 형식이에요"}
            else:
                code, res = chat.post(str(data.get("cid") or ""), str(data.get("name") or ""), str(data.get("text") or ""))
            return self._send(code, json.dumps(res, ensure_ascii=False).encode(), "application/json; charset=utf-8")
        self._send(404, b"not found", "text/plain")

    def _origin(self) -> str:
        """미리보기 그림 주소용: 이 사이트의 바깥 주소(https://도메인). 프록시(Tailscale·Cloudflare)가 넘겨준 이름을 우선."""
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "localhost").split(",")[0].strip()
        proto = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
        if not proto:
            proto = "http" if host.startswith(("localhost", "127.", "[::1]")) or host.split(":")[0].replace(".", "").isdigit() else "https"
        return f"{proto}://{host}"

    def _redirect(self, loc):
        self.send_response(302)
        self.send_header("Location", loc)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, code, body, ctype, cache=None, zipped=None):
        # 글자 파일(HTML·CSS·JS·JSON)은 브라우저가 받을 수 있으면 압축해서 보냄(보통 1/4~1/6 크기)
        enc = None
        if "gzip" in (self.headers.get("Accept-Encoding") or "") and ctype.startswith(ZIP_TYPES) and len(body) > 1024:
            body, enc = (zipped or gzip.compress(body, 6)), "gzip"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if enc:
            self.send_header("Content-Encoding", enc)
        if ctype.startswith(ZIP_TYPES):
            self.send_header("Vary", "Accept-Encoding")
        if cache:
            self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # 접속 로그는 조용히
        pass


def main():
    init_db()
    chat.init()
    player_extra.init()
    player_extra.start()
    maint.init()
    share.init()
    matchinfo.init()
    champs.start()                       # 챔피언 한국어 이름·아이콘(Data Dragon, 하루 한 번)
    maint.start()
    riot.start()
    # 지난 시즌 기록이 없으면 한 번 모아 둠(있으면 파일만 읽음). 켜자마자 몰리는 수집과 겹치지 않게 2분 뒤
    archive.start()
    schedule.start()                     # 일정·결과: 저장해 둔 것부터 보여 주고 1분 뒤부터 새로 받음
    load_static()
    threading.Thread(target=jobs.loop, args=(jobs.poll_wiki, WIKI_INTERVAL), daemon=True).start()
    threading.Thread(target=jobs.loop, args=(jobs.poll_news, NEWS_INTERVAL), daemon=True).start()
    threading.Thread(target=jobs.loop, args=(jobs.poll_fa, FA_INTERVAL, jobs.FA_LOCK), daemon=True).start()
    threading.Thread(target=jobs.loop, args=(jobs.retry_profiles, 180, jobs.FA_LOCK), daemon=True).start()
    log.info("listening on :%d", PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
