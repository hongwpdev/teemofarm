"""사람별 상태 스냅숏 하나: FA 표 · 로스터 표 · 뉴스 유력(FA 선수 · 계약 중 선수 · 무산)을 한 시점에 함께 계산.

화면(이적 시장 · 로스터 카드 · 팀별 · 이동 보드 · 행선지 맞히기)과 독버섯 판 · 데이터 점검이 모두 이것만 읽음.
예전엔 화면마다 따로 계산해서 따로 저장(30초·60초)해 둬서, 같은 순간에도 화면끼리 서로 다른 시점의 데이터를
섞어 쓸 수 있었음(이적 시장은 새 FA 목록, 로스터 카드는 30초 전 계산). 이제는 원본(fa·roster 표, 뉴스)이 바뀌면
스냅숏을 한 번에 새로 만들고, 바뀌지 않았으면 그대로 씀. 기사 기간(최근 2주)이 지나는 것도 반영되게 5분마다는 새로."""
import hashlib
import threading
import time

from . import rumor
from .core import db

MAX_AGE = 300            # 원본이 그대로여도 이 시간이 지나면 새로(유력은 최근 2주 기사만 보므로)
_LOCK = threading.Lock()
_BUILD = threading.Lock()
_S = {"key": None, "at": 0.0, "val": None}


def _read():
    with db() as c:
        fa = [dict(r) for r in c.execute("SELECT * FROM fa WHERE league='lck'").fetchall()]
        ro = [dict(r) for r in c.execute("SELECT * FROM roster WHERE league='lck'").fetchall()]
        try:
            news = tuple(c.execute("SELECT COUNT(*), COALESCE(MAX(first_seen), '') FROM items "
                                   "WHERE source IN ('news', 'news_en')").fetchone())
        except Exception:  # noqa: BLE001  (표가 아직 없을 때)
            news = (0, "")
    raw = [dict(r) for r in fa]
    # 우선순위(로스터 > FA 목록): FA 목록은 아직 '미정'인데 리그피디아 로스터엔 다른 LCK 팀으로 올라온 사람(도란: 로스터 DK, FA 목록 T1 미정)은
    # 모든 화면에서 그 팀 이적 확정으로(이적 시장은 미정 · 팀별은 영입으로 엇갈려 보이던 문제). 운영 알림(integrity)은 원래 목록(fa_raw)으로
    on = {r["page"]: r["team"] for r in ro}
    for r in fa:
        t = on.get(r["page"])
        if r["status"] == "fa" and t and t != r["team_from"]:
            r.update(status="move", team_to=t, by_roster=1)
    key = hashlib.sha1(repr((sorted(tuple(sorted(r.items())) for r in fa),
                             sorted(tuple(sorted(r.items())) for r in ro), news)).encode()).hexdigest()
    return key, fa, ro, raw


def get() -> dict:
    """{"fa": [fa 행], "roster": [roster 행], "rumors": {page: 유력}, "leaving": {page: 유력}, "off": {page: {(팀, 잔류)}}, "key", "at"}"""
    key, fa, ro, raw = _read()
    with _LOCK:
        s = _S["val"]
        if s and _S["key"] == key and time.time() - _S["at"] < MAX_AGE:
            return s
    with _BUILD:                                   # 동시에 여러 요청이 와도 한 번만 계산
        with _LOCK:
            s = _S["val"]
            if s and _S["key"] == key and time.time() - _S["at"] < MAX_AGE:
                return s
        with rumor._LOCK:
            rumor._CACHE.clear()                   # (rumor 자체의 1분 저장본은 비워서 같은 시점의 기사로)
        # 이번 겨울 이미 옮긴 사람(이적 확정)에게 또 '다른 팀 이적 유력'은 지난 소문으로 봄(오피셜 기사만 인정)
        moved = {r["page"] for r in fa if r["status"] == "move"}
        leaving = {p: x for p, x in rumor.movers(ro).items() if p not in moved or x["official"]}
        val = {"fa": fa, "fa_raw": raw, "roster": ro, "rumors": rumor.rumors(fa), "leaving": leaving,
               "off": rumor.called_off(fa, ro), "key": key, "at": time.time()}
        with _LOCK:
            _S.update(key=key, at=val["at"], val=val)
        return val


def reset():
    """시험용: 저장본 비우기."""
    with _LOCK:
        _S.update(key=None, at=0.0, val=None)
