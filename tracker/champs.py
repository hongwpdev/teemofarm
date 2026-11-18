"""챔피언 이름·아이콘: 라이엇 공식 Data Dragon(영문·한국어 champion.json)을 하루 한 번 받아 둠.
리그피디아의 영문 이름('Jarvan IV', 'Nunu & Willump')을 Data Dragon 키('JarvanIV')·한국어 이름('자르반 4세')으로 바꿔 줌.
라이엇 팬 콘텐츠 정책(Legal Jibber Jabber)에 따라 비상업 팬 사이트에서 사용. 못 받으면 영문 이름만 보여 줌."""
import json
import os
import re
import threading
import time

from .config import DB_PATH, log
from .core import http_get

DDRAGON = "https://ddragon.leagueoflegends.com"
_PATH = os.path.join(os.path.dirname(DB_PATH) or ".", "champs.json")
_LOCK = threading.Lock()
DATA = {"ver": "", "map": {}, "at": 0}       # map: 정규화한 영문 이름 → {"id", "ko"}


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _fetch():
    global DATA
    ver = json.loads(http_get(f"{DDRAGON}/api/versions.json"))[0]
    en = json.loads(http_get(f"{DDRAGON}/cdn/{ver}/data/en_US/champion.json"))["data"]
    ko = json.loads(http_get(f"{DDRAGON}/cdn/{ver}/data/ko_KR/champion.json"))["data"]
    m = {}
    for cid, c in en.items():
        info = {"id": cid, "ko": (ko.get(cid) or {}).get("name") or c["name"]}
        m[norm(c["name"])] = info
        m.setdefault(norm(cid), info)                       # 'MonkeyKing' 같은 내부 이름으로도 찾게
    d = {"ver": ver, "map": m, "at": time.time()}
    with _LOCK:
        DATA = d
    try:
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except OSError:
        pass
    log.info("champs: %s, %d champions", ver, len(en))


def info(name: str) -> dict:
    """{'en': 'Jarvan IV', 'ko': '자르반 4세', 'img': '…/JarvanIV.png'} (모르는 챔피언이면 img 없이 영문 이름)."""
    d = DATA
    c = d["map"].get(norm(name))
    if not c:
        return {"en": name, "ko": name, "img": ""}
    return {"en": name, "ko": c["ko"], "img": f'{DDRAGON}/cdn/{d["ver"]}/img/champion/{c["id"]}.png'}


def start():
    global DATA
    try:
        with open(_PATH, encoding="utf-8") as f:
            DATA = json.load(f)
    except (OSError, ValueError):
        pass

    def loop():
        while True:
            try:
                if time.time() - DATA.get("at", 0) > 86400 or not DATA.get("map"):
                    _fetch()
                time.sleep(3600)
            except Exception as e:  # noqa: BLE001
                log.warning("champs failed: %s", e)
                time.sleep(600)
    threading.Thread(target=loop, daemon=True).start()
