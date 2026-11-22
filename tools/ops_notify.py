"""반영(update.sh) 결과를 디스코드 운영 채널로 알리고, 성공하면 캐시 비우기·실제 주소 점검까지 함. 표준 라이브러리만.

update.sh가 테스트용 이미지로 돌림(서버에 파이썬이 없어도 됨):
    docker run --rm --network host -v "$PWD:/src:ro" -w /src python:3.12-slim python tools/ops_notify.py ok   "<새 커밋>" "<이전 커밋>"
    ... python tools/ops_notify.py fail "<이유>" "<건너뛴 커밋>" "<유지한 커밋>"   (표준 입력: 테스트 기록 끝부분, 있으면)
    ... python tools/ops_notify.py restart

설정(서버의 .env 또는 환경 변수, 저장소에는 넣지 않음):
    DISCORD_OPS_WEBHOOK   운영 채널 웹훅(없으면 DISCORD_WEBHOOK_URL). 소식 채널(DISCORD_WEBHOOK)로는 절대 안 보냄
    CF_ZONE_ID, CF_API_TOKEN   있으면 반영 성공 뒤 Cloudflare 캐시 전체 비우기(토큰 권한: Zone > Cache Purge)
    SITE_BASE_URL         실제 주소 점검(기본 https://teemofarm.com)
    INTERNAL_URL          컨테이너 직접 주소(기본 http://127.0.0.1:8088, docker-compose의 8088:8080)
웹훅이 없으면 알림 내용을 화면(update.log)에만 찍음. 무엇이 실패해도 종료 코드는 0(반영 자체를 막지 않음)."""
import json
import os
import sys
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; teemofarm-deploy-check)"
# 실제 주소 점검: 주소 → 그 화면에 꼭 있어야 하는 글자(200이어도 빈 껍데기·오류 화면이면 실패)
PAGES = {
    "/healthz": "",
    "/lck": 'class="top_tab"',
    "/lck/fa": 'id="falist"',
    "/lck/summary": 'class="sgrid"',
    "/lck/roster": 'class="top_tab"',
    "/lck/schedule": 'class="top_tab"',
}
BAD_WORDS = ("Traceback", "Internal Server Error")


def parse_env(text: str) -> dict:
    """.env 한 줄에 KEY=값. 주석·빈 줄·export 무시, 따옴표 벗김. 값 안의 = 는 그대로."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        elif " #" in v:
            v = v.split(" #", 1)[0].rstrip()
        if k:
            out[k] = v
    return out


def settings(env_path=".env", environ=None) -> dict:
    environ = os.environ if environ is None else environ
    try:
        with open(env_path, encoding="utf-8") as f:
            file_env = parse_env(f.read())
    except OSError:
        file_env = {}
    get = lambda k, d="": (environ.get(k) or file_env.get(k) or d).strip()   # noqa: E731  환경 변수가 .env보다 먼저
    return {"webhook": get("DISCORD_OPS_WEBHOOK") or get("DISCORD_WEBHOOK_URL"),
            "cf_zone": get("CF_ZONE_ID"), "cf_token": get("CF_API_TOKEN"),
            "site": get("SITE_BASE_URL", "https://teemofarm.com").rstrip("/"),
            "internal": get("INTERNAL_URL", "http://127.0.0.1:8088").rstrip("/")}


def http(url, data=None, headers=None, timeout=20):
    """→ (상태 코드, 본문 글자). 연결 실패는 (0, 이유)."""
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:500]
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:200]


def purge(cfg, fetch=http) -> str:
    if not (cfg["cf_zone"] and cfg["cf_token"]):
        return "캐시 비우기: 설정 없음(건너뜀)"
    code, body = fetch(f'https://api.cloudflare.com/client/v4/zones/{cfg["cf_zone"]}/purge_cache',
                       data=json.dumps({"purge_everything": True}).encode(),
                       headers={"Authorization": "Bearer " + cfg["cf_token"], "Content-Type": "application/json"})
    try:
        ok = code == 200 and json.loads(body).get("success")
    except ValueError:
        ok = False
    return "캐시 비우기: 완료" if ok else f"캐시 비우기: 실패(HTTP {code})"


def smoke(base, fetch=http) -> list:
    """실제 주소의 주요 화면 → 문제 목록(빈 목록이면 통과)."""
    bad = []
    for path, mark in PAGES.items():
        code, body = fetch(base + path + ("&" if "?" in path else "?") + f"_t={int(time.time())}")
        if code != 200:
            bad.append(f"{path} HTTP {code or '연결 실패'}")
        elif mark and mark not in body:
            bad.append(f"{path} 화면이 비었거나 깨짐({mark} 없음)")
        elif any(w in body for w in BAD_WORDS):
            bad.append(f"{path} 오류 글자가 보임")
    return bad


def audits(base, fetch=http) -> list:
    """데이터 점검 요약 줄들: 정합성 문제 수 · '유력' 기사 읽음률."""
    lines = []
    code, body = fetch(base + "/api/integrity")
    try:
        probs = json.loads(body)["problems"] if code == 200 else None
    except (ValueError, KeyError, TypeError):
        probs = None
    if probs is None:
        lines.append(f"정합성: 못 읽음(HTTP {code})")
    elif probs:
        lines.append(f"정합성: 문제 {len(probs)}건 — " + " / ".join(str(p) for p in probs[:3]) + (" …" if len(probs) > 3 else ""))
    else:
        lines.append("정합성: 이상 없음")
    code, body = fetch(base + "/api/rumor-audit")
    try:
        r = json.loads(body) if code == 200 else None
        rate = r.get("read_rate")
        lines.append(f"기사 읽음률: {round(rate * 100, 1)}% (못 읽은 후보 {r.get('unread', 0)}건)" if rate is not None else "기사 읽음률: 아직 표본 없음")
    except (ValueError, AttributeError, TypeError):
        lines.append(f"기사 읽음률: 못 읽음(HTTP {code})")
    return lines


def message(kind, args, cfg, log_tail="", fetch=http, wait=0) -> str:
    if kind == "restart":
        return "♻️ 티모의 버섯농장: 응답이 없어서 컨테이너를 다시 켰어요"
    if kind == "fail":
        reason, skipped, kept = (list(args) + ["", "", ""])[:3]
        msg = f"🚨 반영 실패({reason})\n건너뜀: {skipped}\n유지: {kept}"
        if log_tail.strip():
            msg += "\n```\n" + log_tail.strip()[-1200:] + "\n```"
        return msg
    new, old = (list(args) + ["", ""])[:2]
    parts = [purge(cfg, fetch)]
    if wait:
        time.sleep(wait)                    # 캐시가 비워진 뒤 첫 요청이 새 코드로 가게 잠깐
    live = smoke(cfg["site"], fetch)
    parts.append("실제 주소 점검: 통과" if not live else "실제 주소 점검: " + " · ".join(live))
    parts += audits(cfg["internal"], fetch)
    warn = bool(live) or any(p.startswith(("정합성: 문제", "정합성: 못 읽음", "캐시 비우기: 실패")) for p in parts)
    head = ("⚠️ 반영은 됐지만 확인 필요" if warn else "✅ 반영 완료") + f": {new}" + (f"\n(이전: {old})" if old else "")
    return head + "\n" + "\n".join("• " + p for p in parts)


def send(cfg, text, fetch=http) -> str:
    if not cfg["webhook"]:
        return "웹훅 없음 — 화면에만"
    code, body = fetch(cfg["webhook"], data=json.dumps({"content": text[:1900]}).encode(),
                       headers={"Content-Type": "application/json"})
    return "보냄" if code in (200, 204) else f"못 보냄(HTTP {code})"


def main(argv):
    if not argv or argv[0] not in ("ok", "fail", "restart"):
        print(__doc__)
        return 0
    cfg = settings()
    tail = sys.stdin.read() if argv[0] == "fail" and not sys.stdin.isatty() else ""
    try:
        text = message(argv[0], argv[1:], cfg, tail, wait=5)
    except Exception as e:  # noqa: BLE001  알림이 반영을 막으면 안 됨
        text = f"⚠️ 반영 알림을 만들다 오류: {e}"
    print(text)
    print("디스코드:", send(cfg, text))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
