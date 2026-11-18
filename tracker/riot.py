"""라이엇 공식 정적 이미지(Data Dragon)에서 티모 궁극기(유독성 함정) 아이콘을 한 번 받아 두고 우리 서버가 내려줌.
라이엇 팬 콘텐츠 정책(Legal Jibber Jabber)에 따라 비상업 팬 사이트에서 쓰고, 화면 아래에 안내 문구를 넣음.
받지 못하면(인터넷 끊김 등) 화면은 🍄 이모지로 대신함."""
import json
import os
import threading
import time

from .config import DB_PATH, log
from .core import http_get

DDRAGON = "https://ddragon.leagueoflegends.com"
# 리그피디아에 올라온 같은 아이콘(라이엇 자산). 이 주소는 서버가 이미 팀 로고를 받는 곳이라 먼저 시도
WIKI_ICON = "https://static.wikia.nocookie.net/lolesports_gamepedia_en/images/2/21/Noxious_Trap.png/revision/latest?cb=20241009204156"
FALLBACK_VER = "14.24.1"          # 버전 목록을 못 받으면 이 버전 주소로 시도(예전 버전 이미지도 그대로 남아 있음)
ICON = {"png": None}
_PATH = os.path.join(os.path.dirname(DB_PATH) or ".", "teemo_r.png")


def _load():
    try:                      # 코드에 넣어 둔 아이콘을 먼저 씀(이 PC의 파이썬이 일부 이미지 서버 인증서를 못 믿는 문제를 피함)
        import base64
        from .teemo_icon import ICON_B64
        ICON["png"] = base64.b64decode(ICON_B64)
        return
    except Exception as e:  # noqa: BLE001
        log.warning("riot: embedded icon failed: %s", e)
    if os.path.exists(_PATH):
        with open(_PATH, "rb") as f:
            ICON["png"] = f.read()
        return
    for attempt in range(5):
        try:
            try:
                png, ver = http_get(WIKI_ICON), "leaguepedia"
            except Exception:  # noqa: BLE001
                try:
                    ver = json.loads(http_get(f"{DDRAGON}/api/versions.json"))[0]
                except Exception:  # noqa: BLE001
                    ver = FALLBACK_VER
                png = http_get(f"{DDRAGON}/cdn/{ver}/img/spell/TeemoR.png")
            if png[:8] == b"\x89PNG\r\n\x1a\n":
                ICON["png"] = png
                with open(_PATH, "wb") as f:
                    f.write(png)
                log.info("riot: teemo icon %s (%d bytes)", ver, len(png))
                return
        except Exception as e:  # noqa: BLE001
            log.warning("riot: teemo icon failed: %s", e)
            try:   # 원인 확인용(서버 창을 못 볼 때)
                with open(_PATH + ".err.txt", "a", encoding="utf-8") as f:
                    f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {type(e).__name__}: {e}\n")
            except OSError:
                pass
        time.sleep(60 * (attempt + 1))


def start():
    threading.Thread(target=_load, daemon=True).start()
