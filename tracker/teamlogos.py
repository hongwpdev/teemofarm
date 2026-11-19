"""해외 팀 로고: 리그피디아 Teams 표의 Image(예: 'G2 Esportslogo profile.png')를 64px 썸네일로 한 번 받아
data/logos/<팀 키>.<png|webp> 로 저장하고, 우리 서버가 /tlogo/<팀 키> 로 내보냄(방문자 브라우저는 리그피디아에 직접 가지 않음).
LCK 팀은 기존 로고(logos.py)를 그대로 씀. 못 받은 로고는 하루 뒤 다시 시도하고, 그동안 화면은 글자 로고."""
import hashlib
import json
import os
import re
import threading
import time

from .cargo import _cq, api_get, cargo
from .config import DB_PATH, log
from .core import http_get

_DIR = os.path.join(os.path.dirname(DB_PATH) or ".", "logos")
_INDEX = os.path.join(_DIR, "index.json")
_LOCK = threading.Lock()
INDEX = {}                     # 팀 키 -> {"file", "type", "v"(내용 해시), "image"} 또는 {"image", "failed_at"(시각)}
RETRY_SEC = 6 * 3600           # 리그피디아에 로고가 정말 없을 때 다시 볼 때까지
TYPES = {b"\x89PNG": ("png", "image/png"), b"RIFF": ("webp", "image/webp"), b"GIF8": ("gif", "image/gif"),
         b"\xff\xd8\xff": ("jpg", "image/jpeg")}
_KEY = re.compile(r"^[a-z0-9-]{1,60}$")
_WANT, _WANT_LOCK = set(), threading.Lock()   # 로고를 받아 둘 팀 이름(선수 커리어 등에서 처음 본 팀)
BATCH, BATCH_SEC = 40, 120


def team_rows(names, gap=None, strict=False):
    """리그피디아 Teams 표에서 팀 약칭(BLG, G2 …)·로고 파일 이름. 못 받으면 빈 dict(화면은 긴 이름·글자 로고로).
    일정의 팀 이름은 팀 문서 이름(OverviewPage)이라 그것으로 찾고, 못 찾은 이름(이름이 바뀐 팀)은 TeamRedirects로 한 번 더."""
    def by_page(pages):
        got = {}
        pages = sorted(pages)
        for i in range(0, len(pages), 40):
            rows = cargo(gap, tables="Teams", fields="Name,OverviewPage,Short,Image",
                         where=f'OverviewPage IN ({",".join(_cq(n) for n in pages[i:i + 40])})')
            got.update({r["OverviewPage"]: r for r in rows})
        return got
    names = {n for n in names if n and n != "TBD"}
    try:
        out = by_page(names)
        missing = sorted(names - set(out))
        if missing:
            redir = {}
            for i in range(0, len(missing), 40):
                rows = cargo(gap, tables="TeamRedirects", fields="AllName,_pageName=P",
                             where=f'AllName IN ({",".join(_cq(n) for n in missing[i:i + 40])})')
                redir.update({r["AllName"]: r["P"] for r in rows if r.get("P")})
            found = by_page(set(redir.values()))
            out.update({n: found[p] for n, p in redir.items() if p in found})
    except Exception as e:  # noqa: BLE001
        if strict:
            raise
        log.warning("team names failed: %s", e)
        return {}
    return out


def _sniff(data: bytes):
    for magic, t in TYPES.items():
        if data.startswith(magic) and (magic != b"RIFF" or data[8:12] == b"WEBP"):
            return t
    return None


def load():
    global INDEX
    try:
        with open(_INDEX, encoding="utf-8") as f:
            INDEX = json.load(f)
    except (OSError, ValueError):
        INDEX = {}


def _save():
    os.makedirs(_DIR, exist_ok=True)
    tmp = _INDEX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(INDEX, f, ensure_ascii=False)
    os.replace(tmp, _INDEX)


LAST_ERROR = {"at": "", "msg": ""}   # 마지막으로 이미지를 못 받은 이유(/api/diag 에 보임)


def url(key: str) -> str:
    """화면용 주소(없으면 ''). 로고가 바뀌면 ?v= 가 바뀌어 브라우저가 새로 받음."""
    e = INDEX.get(key) or {}
    if e.get("file"):
        return f"/tlogo/{key}?v={e['v']}"
    if e.get("remote"):                       # 서버가 이미지를 직접 못 받음: 리그피디아 이미지 주소로 안내
        return f"/tlogo/{key}?v=r"
    return ""


def remote(key: str) -> str:
    """서버가 직접 못 받은 로고의 리그피디아 이미지 주소(없으면 ''). /tlogo/<키> 가 이 주소로 넘겨 줌."""
    e = INDEX.get(key) or {}
    u = e.get("remote") or ""
    return u if _KEY.match(key or "") and u.startswith("https://static.wikia.nocookie.net/") else ""


def read(key: str):
    """(내용, 종류) 또는 None. /tlogo/<키> 응답용."""
    e = INDEX.get(key) or {}
    if not _KEY.match(key or "") or not e.get("file"):
        return None
    try:
        with open(os.path.join(_DIR, e["file"]), "rb") as f:
            return f.read(), e["type"]
    except OSError:
        return None


def _thumbs(images):
    """파일 이름 목록 → {파일 이름: 64px 썸네일 주소} (한 번에 40개씩)."""
    out = {}
    for i in range(0, len(images), 40):
        chunk = images[i:i + 40]
        d = api_get({"action": "query", "prop": "imageinfo", "iiprop": "url",          # 간격은 Cargo와 함께 맞춤
                     "iiurlwidth": 64, "titles": "|".join("File:" + x for x in chunk)})
        if d.get("error"):                     # 요청 한도 등: '로고 없음'으로 적지 않고 다음에 다시
            raise RuntimeError((d["error"] or {}).get("info", "api error"))
        names = {n["to"]: n["from"] for n in (d.get("query") or {}).get("normalized") or []}
        for p in ((d.get("query") or {}).get("pages") or {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            title = names.get(p.get("title"), p.get("title") or "")
            if ii.get("thumburl"):
                out[title.split(":", 1)[-1]] = ii["thumburl"]
    return out


def _cands(img: str):
    """정사각 로고('…logo square.png')가 있으면 그것부터: 'profile' 로고는 가로로 긴 글자 로고가 많아 작게 줄이면 안 보임."""
    sq = img.replace("logo profile.", "logo square.")
    return [sq, img] if sq != img else [img]


def ensure(images: dict):
    """{팀 키: 리그피디아 파일 이름} 중 아직 없는 로고(또는 파일 이름이 바뀐 로고)를 받아 둠."""
    images = {k: "|".join(_cands(v)) for k, v in images.items() if v}
    now = time.time()
    need = {k: img for k, img in images.items() if img and _KEY.match(k)
            and ((INDEX.get(k) or {}).get("image") != img or (INDEX.get(k) or {}).get("remote") or
                 (not (INDEX.get(k) or {}).get("file") and now - (INDEX.get(k) or {}).get("failed_at", 0) > RETRY_SEC))}
    if not need:
        return 0
    try:
        thumbs = _thumbs(sorted({c for v in need.values() for c in v.split("|")}))
        if not thumbs:
            log.warning("team logos: no thumbnail urls for %d teams (e.g. %s)", len(need), next(iter(need.values())))
    except Exception as e:  # noqa: BLE001
        log.warning("team logos: thumb urls failed: %s", e)
        return 0
    got, blocked = 0, []
    for k, img in need.items():
        data, t = None, None
        src = next((thumbs[c] for c in img.split("|") if thumbs.get(c)), "")
        if src:
            try:
                time.sleep(0.3)
                data = http_get(src)
                t = _sniff(data)
            except Exception as e:  # noqa: BLE001
                # 서버에서 이미지 서버로 못 감(네트워크·인증서 등): 주소만 적어 두고 브라우저가 직접 받게 함.
                # 다음 갱신 때 다시 직접 받아 보고, 되면 파일로 바꿈
                blocked.append(k)                                  # 팀마다 경고를 남기면 진짜 오류가 묻혀서 끝에 한 줄로 요약
                LAST_ERROR.update(at=time.strftime("%Y-%m-%d %H:%M:%S"), msg=f"{type(e).__name__}: {e}"[:300])
                with _LOCK:
                    if not (INDEX.get(k) or {}).get("file"):
                        INDEX[k] = {"image": img, "remote": src}
                        _save()
                continue
        with _LOCK:
            if t and len(data) < 200_000:
                os.makedirs(_DIR, exist_ok=True)
                fn = f"{k}.{t[0]}"
                with open(os.path.join(_DIR, fn), "wb") as f:
                    f.write(data)
                INDEX[k] = {"file": fn, "type": t[1], "v": hashlib.sha1(data).hexdigest()[:8], "image": img}
                got += 1
            elif not (INDEX.get(k) or {}).get("file"):           # 받아 둔 예전 로고가 있으면 그대로 둠
                INDEX[k] = {"image": img, "failed_at": now}   # (예전 "failed" 표시는 무시 → 한 번 다시 받음)
            _save()
    if blocked:
        log.warning("team logos: %d팀 이미지 서버에서 직접 못 받음(%s) → 브라우저가 직접 받음. 예: %s",
                    len(blocked), LAST_ERROR["msg"][:60], ", ".join(blocked[:3]))
    log.info("team logos: %d new of %d", got, len(need))
    return got


def slug(name: str) -> str:
    """팀 이름 → 팀 키(schedule.slug와 같음). 예: 'Griffin (Korean Team)' → 'griffin-korean-team'."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def known(key: str) -> bool:
    """로고가 있거나, 최근에 찾아봤는데 없었던 팀."""
    e = INDEX.get(key) or {}
    return bool(e.get("file")) or time.time() - e.get("failed_at", 0) < RETRY_SEC


def request(names):
    """처음 보는 팀 로고를 뒤에서 받아 두도록 줄 세움(화면은 기다리지 않음 — 다음에 열 때 보임)."""
    with _WANT_LOCK:
        _WANT.update(n for n in names if n and not known(slug(n)))


def _work():
    """줄 선 팀을 BATCH_SEC마다 BATCH개씩: 리그피디아 Teams에서 로고 파일 이름을 찾아 받음. 못 찾은 팀은 RETRY_SEC 동안 다시 안 찾음."""
    while True:
        time.sleep(BATCH_SEC)
        _batch()


def _batch():
    """줄 선 팀 한 묶음 처리(테스트에서 바로 부름)."""
    with _WANT_LOCK:
        names = sorted(_WANT)[:BATCH]
        _WANT.difference_update(names)
    names = [n for n in names if not known(slug(n))]
    if not names:
        return
    try:
        rows = team_rows(set(names), strict=True)
    except Exception as e:  # noqa: BLE001
        log.warning("team logos: lookup failed: %s", e)
        with _WANT_LOCK:
            _WANT.update(names)
        return
    ensure({slug(n): (rows.get(n) or {}).get("Image") or "" for n in names})
    with _LOCK:                                    # 리그피디아에 로고가 없는 팀: 한동안 다시 안 찾음
        for n in names:
            if not (rows.get(n) or {}).get("Image") and not (INDEX.get(slug(n)) or {}).get("file"):
                INDEX[slug(n)] = {"image": "", "failed_at": time.time()}
        _save()


def start():
    load()
    threading.Thread(target=_work, daemon=True).start()
