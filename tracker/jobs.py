"""수집 일정과 [조회] 버튼 처리."""
import threading
import time
from datetime import datetime, timezone

from .config import FA_COOLDOWN, MANUAL_COOLDOWN, MANUAL_GAP
from .fa import poll_fa, retry_profiles
from .news import poll_news
from .wiki import poll_wiki

COLLECT_LOCK = threading.Lock()      # 자동 수집과 [조회]가 겹치지 않게
MANUAL = {"running": False, "last_start": 0.0, "last_done": None, "done": []}
FA_LOCK = threading.Lock()           # FA는 뉴스·위키와 따로 돌아서 서로 기다리지 않음
FA_MANUAL = {"running": False, "last_start": 0.0, "last_done": None, "done": []}


def loop(fn, interval, lock=COLLECT_LOCK):
    while True:
        with lock:
            fn()
        time.sleep(interval)


def poll_fa_locked(gap=None, max_age=None):
    with FA_LOCK:
        if max_age is None:
            poll_fa(gap)
        else:
            poll_fa(gap, max_age)


def poll_fa_manual(gap=None):
    """[조회] 버튼: 이적 기록이 그대로여도 마지막 전체 갱신이 30분 넘었으면 전부 새로."""
    poll_fa_locked(gap, 1800)


def manual_collect():
    """[조회] 버튼: 위키·뉴스·FA를 동시에 빠르게 한 바퀴."""
    with COLLECT_LOCK:
        MANUAL["done"] = []
        def part(name, fn):   # 끝난 순서대로 '조회 중' 화면에 표시
            try:
                fn(MANUAL_GAP)
            finally:
                MANUAL["done"].append(name)
        try:
            ts = [threading.Thread(target=part, args=("wiki", poll_wiki)),
                  threading.Thread(target=part, args=("news", poll_news)),
                  threading.Thread(target=part, args=("fa", poll_fa_manual))]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        finally:
            MANUAL["running"] = False
            MANUAL["last_done"] = datetime.now(timezone.utc).isoformat()


def request_manual():
    if MANUAL["running"]:
        return {"status": "running"}
    wait = MANUAL_COOLDOWN - (time.time() - MANUAL["last_start"])
    if wait > 0:
        return {"status": "cooldown", "wait": int(wait) + 1}
    MANUAL["last_start"] = time.time()
    MANUAL["done"] = []
    MANUAL["running"] = True   # 스레드가 잠금을 잡기 전에도 '진행 중'으로 보이게
    threading.Thread(target=manual_collect, daemon=True).start()
    return {"status": "started"}


def fa_collect():
    """FA 화면 [조회]: FA만 빠르게 한 번(뉴스·위키 수집을 기다리지 않음)."""
    try:
        poll_fa_manual(MANUAL_GAP)
    finally:
        FA_MANUAL["running"] = False
        FA_MANUAL["last_done"] = datetime.now(timezone.utc).isoformat()


def request_manual_fa():
    if FA_MANUAL["running"]:
        return {"status": "running"}
    wait = FA_COOLDOWN - (time.time() - FA_MANUAL["last_start"])
    if wait > 0:
        return {"status": "cooldown", "wait": int(wait) + 1}
    FA_MANUAL["last_start"] = time.time()
    FA_MANUAL["running"] = True
    threading.Thread(target=fa_collect, daemon=True).start()
    return {"status": "started"}
