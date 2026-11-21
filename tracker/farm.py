"""독버섯 심기(소식 화면의 작은 예측 놀이): 판(항목)과 O/X·팀 선택 집계, 결과 판정.
점수·연속 수확·밭은 이용자 브라우저에만 저장(localStorage 'teemofarm_lck_v1', static/farm.js). 서버는
  - 판 목록: 스토브리그엔 '유력' 기사(간다 O / 안 간다 X), 시즌엔 다가오는 LCK 경기(두 팀 중 하나)
  - 선택 집계(민심 줄다리기·역배 판정용, 브라우저 번호 하나당 한 번, 바꿀 수 없음)
  - 결과: 유력 → 리그피디아 FA 상태가 바뀌면(그 팀 이적이면 O, 다른 팀·잔류면 X), 경기 → 승리 팀
만 맡는다. 판은 한 번 만들어지면 결과가 날 때까지 남아서, 유력 표시가 사라져도 판정할 수 있다."""
import hashlib
import random
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from . import schedule
from .config import KST, TEAMS
from .core import db
from .rumor import called_off, movers, rumors

LOCK_MIN = 10            # 경기 시작 몇 분 전까지 심을 수 있나
BONUS_UNDER = 0.30       # 이 비율 미만 쪽에 심어서 맞히면 역배
BONUS_MIN = 10           # 참여가 이만큼은 돼야 역배(몇 명뿐이면 비율이 의미 없음)
OPEN_MAX = 8             # 카드에 보일 열린 판 수(최근 것부터)
_CID = re.compile(r"^[A-Za-z0-9_-]{8,40}$")
_SENT, _LOCK, _SYNC = {}, threading.Lock(), {"at": 0.0}


def init():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS farm_items(
            id TEXT PRIMARY KEY, kind TEXT, page TEXT, nick TEXT, a TEXT, b TEXT, a_label TEXT, b_label TEXT,
            title TEXT, url TEXT, outlet TEXT, published TEXT, lock_at TEXT, result TEXT, resolved_at TEXT, created TEXT, tag TEXT)""")
        c.execute("CREATE TABLE IF NOT EXISTS farm_picks(item TEXT, cid TEXT, pick TEXT, at TEXT, PRIMARY KEY(item, cid))")


def _now():
    return datetime.now(timezone.utc)


def sync(force=False):
    """판을 새로 만들고(유력·경기) 결과를 매김. 1분에 한 번이면 충분."""
    if not force and time.time() - _SYNC["at"] < 60:
        return
    _SYNC["at"] = time.time()
    now = _now().isoformat()
    with db() as c:
        fa = [dict(r) for r in c.execute("SELECT * FROM fa WHERE league='lck'")]
        st = {r["page"]: r for r in fa}
        # 1) 유력 기사 → 판(같은 선수·같은 팀·같은 방향은 한 판)
        for page, rm in rumors(fa).items():
            r = st.get(page)
            if not r or r["status"] != "fa" or not rm.get("team"):
                continue
            iid = f"rm:{page}:{rm['team']}:{'s' if rm['stay'] else 'm'}"
            if not rm["stay"] and _has_open(c, f"mv:{page}:{rm['team']}"):
                continue                               # 같은 사람·같은 행선지 판이 이미 있음(로스터에 있을 때 만든 판)
            _put(c, iid, page, r["nick"], r["team_from"], rm, now)
        # 1-2) 계약이 남은 선수의 이적 유력('커리어 DK → 한화생명') → 판
        roster = [dict(r) for r in c.execute("SELECT * FROM roster WHERE league='lck'")]
        for page, rm in movers(roster).items():
            r = next((x for x in roster if x["page"] == page), None)
            if not r or not rm.get("team") or rm["team"] == r["team"]:
                continue
            if _has_open(c, f"rm:{page}:{rm['team']}:m"):
                continue
            _put(c, f"mv:{page}:{rm['team']}", page, r["nick"], r["team"], rm, now)
        # 1-3) 더 새 기사가 그 행선지를 '무산·결렬'이라 하면 새로 심기는 마감(결과는 계속 리그피디아 기준)
        off = called_off(fa, roster)
        for it in [dict(r) for r in c.execute("SELECT id, page, b, tag FROM farm_items WHERE result IS NULL AND kind='rumor'")]:
            tag = it["tag"] or ""
            if "발표" in tag or "무산" in tag:
                continue
            if (it["b"], it["id"].endswith(":s")) in off.get(it["page"], ()):
                c.execute("UPDATE farm_items SET tag=? WHERE id=?", (("잔류 " if it["id"].endswith(":s") else "") + "무산", it["id"]))
        on = {x["page"]: x["team"] for x in roster}
        started = any(m.get("win") in ("1", "2") and str(_season()) in (m.get("page") or "")
                      for m in schedule.get("lck").get("matches") or [])
        # 2) 다가오는 LCK 경기 + LCK 팀이 나오는 국제전 경기(이틀 안) → 판
        soon = _now() + timedelta(days=2)
        all_games = _games()
        for m in all_games:
            at = _at(m)
            if not at or not m.get("id") or m.get("k1") in ("", None) or m.get("k2") in ("", None) or "TBD" in (m["t1"], m["t2"]):
                continue
            if _now() - timedelta(days=3) < at < soon:
                c.execute("INSERT OR IGNORE INTO farm_items(id,kind,page,nick,a,b,a_label,b_label,title,url,outlet,published,lock_at,created) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          ("m:" + m["id"], "match", m.get("page", ""), "", m["k1"], m["k2"], m["t1"], m["t2"], m.get("tour", ""),
                           "", "", at.isoformat(), (at - timedelta(minutes=LOCK_MIN)).isoformat(), now))
        # 3) 결과 매기기
        games = {"m:" + m["id"]: m for m in all_games}
        for it in [dict(r) for r in c.execute("SELECT * FROM farm_items WHERE result IS NULL")]:
            res = None
            if it["id"].startswith("mv:"):            # 계약 중 선수: 로스터가 그 팀으로 바뀌면 O, 다른 팀이거나 새 시즌이 시작될 때까지 그대로면 X
                team, r = on.get(it["page"]), st.get(it["page"])
                if team == it["b"] or (r and r["status"] == "move" and r["team_to"] == it["b"]):
                    res = "o"
                elif (team and team not in (it["a"], it["b"])) or (r and r["status"] == "move" and r["team_to"] != it["b"]) or (team == it["a"] and started):
                    res = "x"
            elif it["kind"] == "rumor":
                r = st.get(it["page"])
                stay = it["id"].endswith(":s")
                if r and r["status"] == "move":
                    res = "o" if (r["team_to"] == it["b"] and not stay) else "x"
                elif r and r["status"] == "stay":
                    res = "o" if stay else "x"
            else:
                m = games.get(it["id"])
                if m and m.get("win") in ("1", "2"):
                    res = "a" if m["win"] == "1" else "b"
            if res:
                c.execute("UPDATE farm_items SET result=?, resolved_at=? WHERE id=?", (res, now, it["id"]))


def _games():
    """판을 만들 경기: LCK 전부 + 국제전(퍼스트 스탠드·MSI·월즈·EWC) 중 LCK 팀이 나오는 경기. 대회가 바뀌어도 일정만 보고 저절로."""
    out, seen = [], set()
    for lg in ("lck", schedule.INTL):
        for m in schedule.get(lg).get("matches") or []:
            if not m.get("id") or m["id"] in seen:
                continue
            if lg == "lck" or m.get("k1") in schedule.LCK_KEYS or m.get("k2") in schedule.LCK_KEYS:
                seen.add(m["id"])
                out.append(m)
    return out


def _has_open(c, iid) -> bool:
    return bool(c.execute("SELECT 1 FROM farm_items WHERE id=? AND result IS NULL", (iid,)).fetchone())


def _dedupe(items):
    """같은 사람·같은 행선지·같은 방향(이적/잔류) 판이 둘이면(예전에 FA·로스터 쪽에서 따로 만든 것) 먼저 만든 판 하나만."""
    seen, out = set(), []
    for r in sorted(items, key=lambda r: r.get("created") or ""):
        key = (r["page"], r["b"], r["id"].endswith(":s")) if r["kind"] == "rumor" else (r["id"],)
        if key not in seen:
            seen.add(key)
            out.append(r)
    keep = {r["id"] for r in out}
    return [r for r in items if r["id"] in keep]


def _put(c, iid, page, nick, frm, rm, now):
    """유력 기사 판 하나(같은 판이면 결과가 나기 전까지 최신 기사·표시로 바꿈: 유력 → 발표)."""
    from .stove import outlet_name
    tag = ("잔류 " if rm["stay"] else "") + ("발표" if rm["official"] else "유력")    # 화면 공통 글자(views.rm_label과 같음)
    c.execute("INSERT INTO farm_items(id,kind,page,nick,a,b,a_label,b_label,title,url,outlet,published,lock_at,created,tag) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title, url=excluded.url, "
              "outlet=excluded.outlet, published=excluded.published, tag=excluded.tag WHERE farm_items.result IS NULL",
              (iid, "rumor", page, nick, frm, rm["team"], "O", "X", rm["title"], rm["url"],
               outlet_name(rm["outlet"] or ""), rm["published"], "", now, tag))


def _season():
    from .archive import current_season
    return current_season()


def _at(m):
    try:
        return datetime.strptime(m["at"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (KeyError, ValueError, TypeError):
        return None


def _tally(c, ids):
    out = {i: {} for i in ids}
    if ids:
        q = ",".join("?" * len(ids))
        for r in c.execute(f"SELECT item, pick, COUNT(*) n FROM farm_picks WHERE item IN ({q}) GROUP BY item, pick", ids):
            out[r["item"]][r["pick"]] = r["n"]
    return out


def _open(it, now):
    """새로 심을 수 있나: 결과 전 · 경기는 시작 10분 전까지 · 유력 기사가 '발표'(오피셜)로 바뀌거나 '무산' 기사가 나면 마감
    (발표된 건 사실상 답이 나온 것. 이미 심은 사람은 리그피디아에 반영되면 수확·폭발)."""
    if it["result"] is not None or "발표" in (it.get("tag") or "") or "무산" in (it.get("tag") or ""):
        return False
    return not it["lock_at"] or it["lock_at"] > now


DONE_MAX = 15            # 결과 내역에 보일 최근 판 수


def board(ids=(), cid: str = "") -> dict:
    """{"open": [열린 판], "mine": {내가 심은 판 id: 판}, "done": [결과 난 최근 판]}.
    민심(tally)은 결과가 났거나 그 브라우저(cid)가 이미 심은 판만 공개. 아직 안 심은 판은 참여 인원(n)만(심기 전엔 비율 비공개)."""
    sync()
    now = _now().isoformat()
    ids = [i for i in ids if isinstance(i, str) and len(i) < 120][:200]
    with db() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM farm_items ORDER BY COALESCE(published,'') DESC")]
        mine = {r["id"]: r for r in rows if r["id"] in ids}
        # 시즌엔 경기 판을 먼저(가까운 경기부터), 그다음 유력
        opn = _dedupe([r for r in rows if _open(r, now)])
        opn = (sorted((r for r in opn if r["kind"] == "match"), key=lambda r: r["published"]) + [r for r in opn if r["kind"] == "rumor"])[:OPEN_MAX]
        done = sorted(_dedupe([r for r in rows if r["result"]]), key=lambda r: r["resolved_at"] or "", reverse=True)[:DONE_MAX]
        t = _tally(c, list({r["id"] for r in opn + done} | set(mine)))
        my = ({r["item"]: r["pick"] for r in c.execute("SELECT item, pick FROM farm_picks WHERE cid=?", (cid,))}
              if _CID.match(cid or "") else {})
        voted = set(my)
    intl = schedule.get(schedule.INTL).get("teams") or {}
    short = lambda k: TEAMS.get(k, {}).get("short") or (intl.get(k) or {}).get("short") or (k or "").upper()  # noqa: E731

    def pub(r):
        tl = t.get(r["id"], {})
        show = bool(r["result"]) or r["id"] in voted
        return {k: r[k] for k in ("id", "kind", "nick", "a", "b", "a_label", "b_label", "title", "url", "outlet", "published",
                                   "lock_at", "result", "tag", "resolved_at")} | {
            "tally": tl if show else {}, "n": sum(tl.values()), "open": _open(r, now),
            "a_short": short(r["a"]), "b_short": short(r["b"])}
    # my_picks: 이 브라우저가 아직 열린 판에 심은 쪽(브라우저 저장값이 지워져도 '심음' 상태를 되살리게). 결과 난 판은 빼서
    # 저장값을 지우고 다시 수확하는 일은 없게 함
    out = {"open": [pub(r) for r in opn], "mine": {i: pub(r) for i, r in mine.items()}, "done": [pub(r) for r in done],
           "my_picks": {r["id"]: my[r["id"]] for r in opn if r["id"] in my}}
    if not opn:                                   # 심을 판이 하나도 없는 날: 오늘의 로스터 퀴즈
        out["quiz"] = daily_quiz()
    return out


QUIZ_POS = {"Top": "탑", "Jungle": "정글", "Mid": "미드", "Bot": "원딜", "Support": "서폿"}   # views.FA_POS와 같은 말


def _eun(word: str) -> str:
    """받침이 있으면 '은', 없으면 '는'(탑은 · 미드는)."""
    ch = word[-1]
    return "은" if "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 else "는"


def daily_quiz(today=None):
    """오늘의 로스터 퀴즈(3지선다 1문제): 'T1의 지금 미드는?'. 날짜가 같으면 누구에게나 같은 문제(날짜로 고름).
    지금 LCK 로스터 표에서 그 자리 선수 1명 + 다른 팀 같은 자리 선수 2명. 문제를 낼 수 없으면 None."""
    today = today or datetime.now(KST).date()
    with db() as c:
        rows = [dict(r) for r in c.execute("SELECT team, role, nick FROM roster WHERE league='lck' AND nick != '' ORDER BY team, role, nick")]
    rows = [r for r in rows if r["role"] in QUIZ_POS and r["team"] in TEAMS]
    rng = random.Random(int(hashlib.sha256(f"quiz:{today.isoformat()}".encode()).hexdigest()[:12], 16))
    # 한 팀·한 자리에 한 명만 있는 칸만(두 명이면 정답이 둘)
    seats = {}
    for r in rows:
        seats.setdefault((r["team"], r["role"]), []).append(r["nick"])
    seats = sorted(k for k, v in seats.items() if len(v) == 1)
    rng.shuffle(seats)
    for team, role in seats:
        answer = next(r["nick"] for r in rows if (r["team"], r["role"]) == (team, role))
        others = sorted({r["nick"] for r in rows if r["role"] == role and r["team"] != team and r["nick"].lower() != answer.lower()})
        if len(others) < 2:
            continue
        options = [answer] + rng.sample(others, 2)
        rng.shuffle(options)
        return {"date": today.isoformat(), "id": f"quiz:{today.isoformat()}",
                "question": f"지금 {TEAMS[team]['name']}의 {QUIZ_POS[role]}{_eun(QUIZ_POS[role])} 누구?", "team": team,
                "options": options, "answer": options.index(answer)}
    return None


def plant(item: str, pick: str, cid: str):
    """심기(한 사람 한 번, 바꿀 수 없음) → (오류 문구 또는 '', 심기 전 집계, 역배 여부)."""
    if not _CID.match(cid or ""):
        return "잘못된 요청이에요", {}, False
    t = time.time()
    with _LOCK:                                    # 도배 방지: 한 브라우저 1분에 20번까지
        sent = [x for x in _SENT.get(cid, []) if t - x < 60]
        if len(sent) >= 20:
            return "잠시 뒤에 다시 눌러 주세요", {}, False
        _SENT[cid] = sent + [t]
    sync()
    with db() as c:
        it = c.execute("SELECT * FROM farm_items WHERE id=?", (item,)).fetchone()
        if not it:
            return "심을 수 없는 판이에요", {}, False
        if not _open(dict(it), _now().isoformat()):
            return "이미 결과가 났거나 마감됐어요", {}, False
        ok = ("o", "x") if it["kind"] == "rumor" else ("a", "b")
        if pick not in ok:
            return "고를 수 없는 쪽이에요", {}, False
        before = _tally(c, [item])[item]
        n = sum(before.values())
        bonus = n >= BONUS_MIN and before.get(pick, 0) / n < BONUS_UNDER
        cur = c.execute("INSERT OR IGNORE INTO farm_picks(item, cid, pick, at) VALUES(?,?,?,?)",
                        (item, cid, pick, _now().isoformat()))
        if not cur.rowcount:
            return "이미 심었어요", before, False
        after = _tally(c, [item])[item]
    return "", after, bonus
