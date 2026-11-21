"""같은 소식 묶기: 36시간 안에 올라온 뉴스 중 인물·사건(영입/결별/재계약)이 겹치면 한 묶음으로(팀 표시는 달라도 됨).
대표 기사 순서: 제목에 [오피셜]·[공식] → 주요 e스포츠 매체 → 가장 먼저 나온 기사."""
import re
import threading
import time
from datetime import datetime, timezone

from .core import db
from .filters import KO_ALT, ko_nicks

EVENTS = {   # 앞에 있는 것부터 봄
    "renew": ("재계약", "계약 연장", "연장 계약", "동행", "잔류"),
    "leave": ("계약 종료", "계약종료", "결별", "떠나", "떠난", "떠났", "이탈", "방출", "마침표", "FA 시장", "FA 신분", "시장행", "은퇴"),
    "join": ("영입", "합류", "선임", "승격", "콜업", "리턴", "복귀", "입단", "사령탑", "새 둥지", "새둥지"),
}
MAJOR = ("인벤", "inven", "데일리e스포츠", "dailyesports", "osen", "엑스포츠뉴스", "xportsnews", "포모스", "fomos")
_QUOTED = re.compile(r"['‘’\"“”]([^'‘’\"“”]{1,30})['‘’\"“”]")


def _ko2en() -> dict:
    return {**{v: k.lower() for k, v in ko_nicks().items()}, **{ko: en.lower() for ko, en in KO_ALT.items()}}
_PEOPLE = {"at": 0.0, "real": {}, "en": {}}
_LOCK = threading.Lock()


def _people():
    """본명 → 닉네임, 닉네임(소문자) → 닉네임. 로스터·FA 표에서 10분마다 다시 읽음."""
    with _LOCK:
        if time.time() - _PEOPLE["at"] > 600:
            real, en = {}, {}
            try:
                with db() as c:
                    for t in ("roster", "fa"):
                        for r in c.execute(f"SELECT nick, real FROM {t}"):
                            if r["nick"]:
                                en[r["nick"].lower()] = r["nick"].lower()
                                if r["real"] and len(r["real"]) >= 2:
                                    real[r["real"]] = r["nick"].lower()
            except Exception:  # noqa: BLE001
                pass
            _PEOPLE.update(at=time.time(), real=real, en=en)
        return _PEOPLE["real"], _PEOPLE["en"]


def persons(title: str) -> frozenset:
    """제목 속 인물. 같은 사람은 한 이름으로(예: '기인'·김기인·Kiin → kiin)."""
    real, en = _people()
    ko2en = _ko2en()
    out = set()
    for q in _QUOTED.findall(title):
        for part in re.split(r"[·ㆍ,/&]| 및 ", q):
            p = part.strip()
            if 1 <= len(p) <= 8 and " " not in p:
                out.add(ko2en.get(p, en.get(p.lower(), p)))
    for name, nick in real.items():
        if name in title:
            out.add(nick)
    for ko, nick in ko2en.items():
        if len(ko) >= 2 and ko in title:
            out.add(nick)
    for word in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", title):
        if word.lower() in en:
            out.add(en[word.lower()])
    return frozenset(out)


def events(title: str) -> frozenset:
    return frozenset(k for k, words in EVENTS.items() if any(w in title for w in words))


def _rank(r):
    t = r["title"]
    official = "[오피셜]" in t or "[공식]" in t
    major = any(m in (r["outlet"] or "").lower() for m in MAJOR)
    return (0 if official else 1, 0 if major else 1, r["published"])


WINDOW = 36 * 3600


def _ts(r):
    pub = datetime.fromisoformat(r["published"])
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=timezone.utc)
    return pub.timestamp()


def group(items):
    """items: [(행, 성격, 팀 목록)] (최신순) → [(대표 행, 성격, 팀 목록, [나머지 (행, 성격, 팀 목록)])] (최신순 유지)"""
    clusters = []                       # [씨앗 특징, 구성원 목록]
    for it in items:
        r, kind, teams = it
        if r["source"] != "news" or kind == "talk":    # 커뮤니티 글은 기사 묶음('관련 보도')에 넣지 않음
            clusters.append([None, [it]])
            continue
        feat = (_ts(r), persons(r["title"]), events(r["title"]))
        home = None
        if feat[1] and feat[2]:
            for c in clusters:
                f = c[0]
                if f and abs(f[0] - feat[0]) <= WINDOW and f[1] & feat[1] and f[2] & feat[2]:
                    home = c
                    break
        if home:
            home[1].append(it)
        else:
            clusters.append([feat if (feat[1] and feat[2]) else None, [it]])
    out = []
    for _, members in clusters:
        rep = min(members, key=lambda m: _rank(m[0]))
        rest = sorted((m for m in members if m is not rep), key=lambda m: m[0]["published"], reverse=True)
        teams = list(dict.fromkeys(k for m in members for k in m[2]))
        out.append((rep[0], rep[1], teams, rest))
    out.sort(key=lambda x: x[0]["published"], reverse=True)   # 대표 기사 시간 순(날짜 구분선이 어긋나지 않게)
    return out
