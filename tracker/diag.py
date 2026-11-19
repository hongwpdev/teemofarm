"""운영 점검: 로그 파일(data/app.log)과 상태 요약(/api/diag).

배포할 때마다 컨테이너가 새로 만들어져 `docker logs`가 비어 버리므로, 로그를 data/ 폴더(배포해도 남음)에도 남긴다.
/api/diag 는 서버에 들어가지 않고도 원인을 볼 수 있게 최근 경고·오류, 리그피디아 요청 수, 수집 상태를 보여 준다.
비밀번호·개인정보는 로그에 남기지 않는다(수다방 메시지 내용도 로그에 쓰지 않음)."""
import collections
import logging
import logging.handlers
import os
import threading
import time
from datetime import datetime, timezone

from .config import DB_PATH, log

START = time.time()
LOG_PATH = os.path.join(os.path.dirname(DB_PATH) or ".", "app.log")
_RECENT = collections.deque(maxlen=100)       # 최근 경고·오류(WARNING 이상)
_REQ = collections.deque(maxlen=5000)         # 리그피디아 요청 시각
_LIMIT = collections.deque(maxlen=500)        # 리그피디아 요청 한도 오류 시각
_LOCK = threading.Lock()
_installed = [False]


class _Recent(logging.Handler):
    def emit(self, record):
        try:
            _RECENT.append({"at": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="seconds"),
                            "level": record.levelname, "msg": record.getMessage()[:300]})
        except Exception:  # noqa: BLE001
            pass


def install():
    """로그 파일(1MB씩 최대 4개)과 최근 경고 모음을 켬. 여러 번 불러도 한 번만."""
    if _installed[0]:
        return
    _installed[0] = True
    rec = _Recent(level=logging.WARNING)
    log.addHandler(rec)
    try:
        os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
    except OSError as e:
        log.warning("log file disabled: %s", e)


def note_request():
    _REQ.append(time.time())


def note_limit():
    _LIMIT.append(time.time())


def _last_hour(q):
    cut = time.time() - 3600
    return sum(1 for t in list(q) if t >= cut)


def snapshot() -> dict:
    """상태 요약(JSON으로 내보냄)."""
    from . import schedule, teamlogos          # 순환 import 피하려고 여기서
    from .core import STATUS, STATUS_LOCK
    with STATUS_LOCK:
        status = {f"{t}/{s}": {"ok": v["ok"], "at": v["at"].isoformat(timespec="seconds"), "msg": str(v["msg"])[:200]}
                  for (t, s), v in STATUS.items()}
    sched = {}
    for lg in schedule.leagues():
        d = schedule.get(lg)
        sched[lg] = {"at": d.get("at", ""), "season": d.get("season"), "matches": len(d.get("matches") or []),
                     "teams": len(d.get("teams") or {}), "error": d.get("error", "")}
    idx = dict(teamlogos.INDEX)
    logos = {"saved": sum(1 for e in idx.values() if e.get("file")),
             "browser_direct": sum(1 for e in idx.values() if not e.get("file") and e.get("remote")),
             "last_download_error": dict(teamlogos.LAST_ERROR),
             "failed": sorted(k for k, e in idx.items() if not e.get("file") and not e.get("remote") and e.get("image")),
             "not_on_wiki": sum(1 for e in idx.values() if not e.get("file") and not e.get("image")),
             "queued": len(teamlogos._WANT)}
    return {
        "now": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "uptime_min": int((time.time() - START) / 60),
        "leaguepedia_last_hour": {"requests": _last_hour(_REQ), "rate_limited": _last_hour(_LIMIT)},
        "recent_warnings": list(_RECENT)[-30:][::-1],
        "schedule": sched,
        "logos": logos,
        "collectors": status,
        "log_file": LOG_PATH if os.path.exists(LOG_PATH) else "",
    }
