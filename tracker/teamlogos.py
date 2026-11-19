"""해외 팀 로고: 리그피디아 Teams 표의 Image(예: 'G2 Esportslogo profile.png')를 64px 썸네일로 한 번 받아
data/logos/<팀 키>.<png|webp> 로 저장하고, 우리 서버가 /tlogo/<팀 키> 로 내보냄(방문자 브라우저는 리그피디아에 직접 가지 않음).
LCK 팀은 기존 로고(logos.py)를 그대로 씀. 못 받은 로고는 하루 뒤 다시 시도하고, 그동안 화면은 글자 로고."""
import hashlib
import json
import os
import re
import threading
import time
import urllib.parse

from .cargo import CARGO_GAP
from .config import DB_PATH, WIKI_API, log
from .core import http_get

_DIR = os.path.join(os.path.dirname(DB_PATH) or ".", "logos")
_INDEX = os.path.join(_DIR, "index.json")
_LOCK = threading.Lock()
INDEX = {}                     # 팀 키 -> {"file", "type", "v"(내용 해시), "image"} 또는 {"image", "failed_at"(시각)}
RETRY_SEC = 6 * 3600           # 리그피디아에 로고가 정말 없을 때 다시 볼 때까지
TYPES = {b"\x89PNG": ("png", "image/png"), b"RIFF": ("webp", "image/webp"), b"GIF8": ("gif", "image/gif"),
         b"\xff\xd8\xff": ("jpg", "image/jpeg")}
_KEY = re.compile(r"^[a-z0-9-]{1,60}$")


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


def url(key: str) -> str:
    """화면용 주소(없으면 ''). 로고가 바뀌면 ?v= 가 바뀌어 브라우저가 새로 받음."""
    e = INDEX.get(key) or {}
    return f"/tlogo/{key}?v={e['v']}" if e.get("file") else ""


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
        q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url",
                                    "iiurlwidth": 64, "titles": "|".join("File:" + x for x in chunk)})
        time.sleep(CARGO_GAP)
        d = json.loads(http_get(f"{WIKI_API}?{q}"))
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
            and ((INDEX.get(k) or {}).get("image") != img or
                 (not (INDEX.get(k) or {}).get("file") and now - (INDEX.get(k) or {}).get("failed_at", 0) > RETRY_SEC))}
    if not need:
        return 0
    try:
        thumbs = _thumbs(sorted({c for v in need.values() for c in v.split("|")}))
    except Exception as e:  # noqa: BLE001
        log.warning("team logos: thumb urls failed: %s", e)
        return 0
    got = 0
    for k, img in need.items():
        data, t = None, None
        src = next((thumbs[c] for c in img.split("|") if thumbs.get(c)), "")
        if src:
            try:
                time.sleep(0.3)
                data = http_get(src)
                t = _sniff(data)
            except Exception as e:  # noqa: BLE001
                log.warning("team logo %s failed: %s", k, e)   # 받기 실패(일시적): 적지 않고 다음 갱신 때 다시
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
    log.info("team logos: %d new of %d", got, len(need))
    return got
