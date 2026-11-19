"""리그피디아 Cargo 조회(요청 간격·한도 초과 재시도 공통)."""
import json
import threading
import time
import urllib.parse

from .config import CARGO_GAP, REQUEST_GAP, WIKI_API, log
from . import diag
from .core import http_get

_CARGO_LOCK = threading.Lock()
_CARGO_LAST = [0.0]
RATE_MSG = "리그피디아 요청 한도에 걸렸어요. 1~2분 뒤 다시 시도해 주세요"


def _cq(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def is_rate_limit(e) -> bool:
    return "rate limit" in str(e).lower()


def _pace():
    """리그피디아(lol.fandom.com API)로 가는 모든 요청 사이를 CARGO_GAP초 이상 띄움(모든 스레드 공통).
    Cargo뿐 아니라 위키 편집 기록·로고 정보 요청도 여기를 거침 — 한꺼번에 몰리면 요청 한도에 걸림."""
    with _CARGO_LOCK:
        wait = CARGO_GAP - (time.time() - _CARGO_LAST[0])
        if wait > 0:
            time.sleep(wait)
        _CARGO_LAST[0] = time.time()
    diag.note_request()


def api_get(params: dict) -> dict:
    """리그피디아 MediaWiki API(편집 기록·파일 정보) 한 번. 간격은 Cargo와 함께 맞춤."""
    _pace()
    data = json.loads(http_get(f"{WIKI_API}?{urllib.parse.urlencode({'format': 'json', **params})}"))
    if is_rate_limit((data.get("error") or {}).get("info", "")):
        diag.note_limit()
    return data


def cargo(gap, retry=True, **params):
    """Cargo 조회. 요청 사이 CARGO_GAP초 이상 띄우고, 한도 초과면 retry=True일 때 20초 뒤 한 번 더."""
    time.sleep(REQUEST_GAP if gap is None else gap)
    q = urllib.parse.urlencode({"action": "cargoquery", "format": "json", "limit": 500, **params})
    for attempt in (1, 2):
        _pace()
        data = json.loads(http_get(f"{WIKI_API}?{q}"))
        err = data.get("error")
        if err and is_rate_limit(err.get("info", "")):
            diag.note_limit()
        if err and is_rate_limit(err.get("info", "")) and retry and attempt == 1:
            log.warning("cargo rate limited, retry in 20s")
            time.sleep(20)
            continue
        if err:
            raise RuntimeError(err.get("info", "cargo error"))
        return [x["title"] for x in data.get("cargoquery", [])]
    return []


def _real_name(full: str) -> str:
    """'Kim Ha-ram (김하람)' → '김하람'."""
    full = full or ""
    if "(" in full and full.endswith(")"):
        inner = full[full.rfind("(") + 1:-1]
        if any("\uac00" <= ch <= "\ud7a3" for ch in inner):
            return inner
    return ""
