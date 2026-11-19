"""가짜 데이터로 화면을 띄우는 개발용 서버 (인터넷 수집 없음, 실제 DB 안 건드림).

    python tools/dev_server.py            # http://127.0.0.1:8099
    PORT=8100 python tools/dev_server.py
DB는 임시 폴더에 만들고 끌 때 지워요.
"""
import os, sys, time, random, tempfile, shutil, atexit
from datetime import datetime, timedelta, timezone
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="teemofarm-dev-")
atexit.register(shutil.rmtree, _TMP, True)
os.environ["DB_PATH"] = os.path.join(_TMP, "dev.db")
os.environ["MANUAL_COOLDOWN_SEC"] = os.environ.get("MANUAL_COOLDOWN_SEC", "20")
sys.path.insert(0, ROOT)
from tracker import core, fa as fam, jobs, config  # noqa: E402
from tracker.web import server  # noqa: E402
class _A: pass
app = _A()
app.init_db = core.init_db; app.save = core.save; app.set_status = core.set_status; app.TEAMS = config.TEAMS
app.COLLECT_LOCK = jobs.COLLECT_LOCK; app.MANUAL = jobs.MANUAL

app.init_db()
now = datetime.now(timezone.utc)
rows = []
samples = [
    ("hle", "news", "[오피셜] 한화생명e스포츠, 정글러 '피넛' 재계약 발표", "스포츠조선", 0.5),
    ("t1", "news", "T1, '페이커' 이상혁과 2029년까지 계약 연장…오피셜", "인벤", 1.2),
    ("lck", "news", "T1, '페이커' 이상혁과 2029년까지 계약 연장…오피셜", "인벤", 1.2),  # 중복 → 합쳐짐
    ("geng", "wiki", "Roster change: Chovy re-signed through 2027 (contract extension)", "Leaguepedia · Tolmar", 2.5),
    ("dk", "news", "디플러스 기아, 신임 감독 선임…'새 시즌 리빌딩 본격화'", "OSEN", 5),
    ("kt", "news", "kt 롤스터 스토브리그 전망: 탑 라이너 보강이 관건", "데일리e스포츠", 7),
    ("ns", "news", "농심 레드포스, 서포터 영입 오피셜 발표", "포모스", 20),
    ("bfx", "wiki", "Updated player table formatting", "Leaguepedia · Ryn", 26),
    ("drx", "news", "키움 DRX, 2군 출신 미드 라이너 1군 콜업 (promoted)", "스포츠경향", 30),
    ("dns", "news", "DN 수퍼스, 코치진 계약 종료 공식 발표", "이데일리", 52),
    ("bro", "news", "한진 브리온, 원딜 FA 영입 완료", "뉴시스", 75),
    ("lck", "news", "LCK 스토브리그 FA 시장 개장…대어급 선수 행방은", "MK스포츠", 90),
    ("t1", "wiki", "Moved Zeus to former members (left team)", "Leaguepedia · Mirelia", 140),
    ("hle", "news", "한화생명 팬미팅 일정 공개", "스포츠서울", 160),
    ("t1", "news", "[오피셜] 디플러스 기아, FC 온라인팀 운영 종료... LoL은?", "인벤", 40),
    ("t1", "news", "거물급 FA 쏟아진다, 역대급 스토브리그 개막 [LCK]", "스포츠Q", 16),
    ("kt", "news", "e스포츠 market 동향 리포트", "테스트", 17),
    ("dns", "news", "DN 수퍼스, '커즈' 문우찬 영입 발표", "인벤", 15),
    ("kt", "news", "kt 롤스터, 문우찬과 결별", "OSEN", 22),
    ("hle", "news", "[단독] 한화생명e스포츠, '손스타·라이프' 코치 합류 유력", "인벤", 11),
    ("t1", "news", "'롤드컵 패배' T1 탑 도란 재계약 불발 인터뷰 실제 발언 공개", "아티브뉴스", 150),
    ("hle", "news", "[오피셜] '옴므' 떠난 한화생명, '모글리' 이재하 감독 승격", "OSEN", 1),
    ("hle", "news", "[단독] 한화생명, '기인' 김기인 영입", "국민일보", 3),
    ("t1", "news", "[소식통] '제우스' 최우제, T1과 3년 계약 합의", "인벤", 2),
    ("dns", "news", "[단독] DN 수퍼스, '쇼메이커' 허수 영입 근접", "포모스", 4),
    ("geng", "news", "[소식통] '시우' 전시우, 2027 LCK 시즌 젠지 합류 예정", "Sheep Esports", 1.5),
    ("t1", "news", "T1 '페이커', 젠지전 승리…합류 후 100승", "스포츠서울", 6),
]
for i, (team, src, title, outlet, hrs) in enumerate(samples):
    pub = now - timedelta(hours=hrs)
    rows.append({"id": f"{src}:fake{i if not (title.startswith('T1,') ) else 'dup'}{team if src=='wiki' else ''}",
                 "team": team, "source": src, "title": title,
                 "url": "https://example.com/" + str(i), "outlet": outlet,
                 "published": pub.isoformat()})
app.save(rows)
for k in app.TEAMS:
    app.set_status(k, "news", True, "새 항목 0건")
    if app.TEAMS[k].get("wiki"):
        app.set_status(k, "wiki", True, "새 항목 0건")
app.set_status("bfx", "wiki", False, "HTTP Error 503: Service Unavailable")
app.set_status("dns", "news", False, "timed out")


def fake_collect():
    with app.COLLECT_LOCK:
        try:
            time.sleep(4)
            app.save([{"id": f"news:new{time.time()}", "team": "geng", "source": "news",
                       "title": "[오피셜] 젠지, 새 원거리 딜러 영입 (조회로 새로 들어온 기사)",
                       "url": "https://example.com/new", "outlet": "가짜뉴스통신",
                       "published": datetime.now(timezone.utc).isoformat()}])
        finally:
            app.MANUAL["running"] = False
            app.MANUAL["last_done"] = datetime.now(timezone.utc).isoformat()
            app.set_status("geng", "news", True, "새 항목 1건")


def R(d, p, dirn, t, role): return {"D": f"2026-{d} 00:00:00", "Player": p, "Direction": dirn, "Team": t, "Role": role}
rc = [R("11-15","Edo (Park Jun-seok)","Leave","BNK FEARX","Head Coach"), R("11-15","Edo (Park Jun-seok)","Join","BNK FEARX","Director of Esports"),
      R("11-15","Rather","Leave","BNK FEARX","Coach"), R("11-15","Rather","Join","BNK FEARX","Head Coach"),
      R("11-16","VicLa","Leave","BNK FEARX","Mid"), R("11-16","VicLa","Join","BNK FEARX","Mid"),
      R("11-16","Kiin","Leave","Gen.G","Top"), R("11-16","Crazy (Kim Jae-hee)","Leave","Nongshim RedForce","Coach"),
      R("11-16","Crazy (Kim Jae-hee)","Join","DN SOOPers","Coach"), R("11-16","Ggoong","Leave","DN SOOPers","Interim Head Coach"),
      R("11-16","Ggoong","Join","DN SOOPers","Head Coach"), R("11-17","Cuzz","Leave","KT Rolster","Jungle"),
      R("11-17","Cuzz","Join","DN SOOPers","Jungle"), R("11-16","Scout","Leave","Nongshim RedForce","Mid"),
      R("11-16","Millimas","Leave","DN SOOPers","Strategy Analyst")]
exp = [{"ID":"Zeus","P":"Zeus","Team":"Hanwha Life Esports","Role":"Top","Contract":"2026-11-16","N":"Choi Woo-je (최우제)"},
       {"ID":"ShowMaker","P":"ShowMaker","Team":"Dplus Kia","Role":"Mid","Contract":"2026-11-16","N":"Heo Su (허수)"},
       {"ID":"Edo","P":"Edo (Park Jun-seok)","Team":"BNK FEARX","Role":"Coach","Contract":"2026-11-16","N":"Park Jun-seok (박준석)"}]
pl = [{"ID":"Cuzz","P":"Cuzz","Team":"DN SOOPers","Role":"Jungle","Contract":"","N":"Moon Woo-chan (문우찬)"},
      {"ID":"Crazy","P":"Crazy (Kim Jae-hee)","Team":"DN SOOPers","Role":"Coach","Contract":"2027-11-15","N":"Kim Jae-hee (김재희)"},
      {"ID":"VicLa","P":"VicLa","Team":"BNK FEARX","Role":"Mid","Contract":"2027-11-15","N":"Lee Dae-kwang (이대광)"},
      {"ID":"Rather","P":"Rather","Team":"BNK FEARX","Role":"Coach","Contract":"2028-11-20","N":"Shin Hyeong-seop (신형섭)"},
      {"ID":"Ggoong","P":"Ggoong","Team":"DN SOOPers","Role":"Coach","Contract":"2028-11-20","N":"Yu Byeong-jun (유병준)"},
      {"ID":"Kiin","P":"Kiin","Team":"","Role":"Top","Contract":"","N":"Kim Gi-in (김기인)"},
      {"ID":"Scout","P":"Scout","Team":"Team Liquid","Role":"Mid","Contract":"2027-11-30","N":"Lee Ye-chan (이예찬)"},
      {"ID":"Millimas","P":"Millimas","Team":"","Role":"Analyst","Contract":"","N":"Kim Geon-woo (김건우)"}]

TEN = [("Longzhu Gaming","2016-11-30","2017-01-11"),("Longzhu Gaming","2017-01-11","2018-01-07"),("Kingzone DragonX","2018-01-07","2019-10-09"),
       ("DragonX","2019-10-09","2019-11-17"),("T1","2019-12-08","2021-07-15"),("T1","2021-07-15","2021-11-15"),("KT Rolster","2021-11-19","2023-11-20"),
       ("Kwangdong Freecs","2023-12-05","2024-11-18"),("KT Rolster","2024-11-20","2026-11-17"),("DN SOOPers","2026-11-17","")]
CALLS = []
def fake_cargo(gap, **p):
    CALLS.append(p["tables"])
    if p["tables"] == "Tenures":
        return [{"Player":"Cuzz","Team":t,"DateJoin":a,"DateLeave":b} for t,a,b in TEN] if '"Cuzz"' in p["where"] else []
    if p["tables"] == "RosterChanges": return rc
    if "Contract<" in p["where"]: return exp
    if p["where"].startswith("Team IN"):
        return ROSTER_PL
    return [x for x in pl if '"' + x["P"] + '"' in p["where"]]
WN = {"hle":"Hanwha Life Esports","t1":"T1","geng":"Gen.G","dk":"Dplus Kia","kt":"KT Rolster","bfx":"BNK FEARX","dns":"DN SOOPers","bro":"HANJIN BRION"}
ROSTER_PL = [{"ID":n,"P":n,"Team":WN[k],"Role":r,"Contract":c,"N":""} for k,r,n,c in [
  ("bfx","Mid","VicLa","2027-11-15"),("dns","Bot","deokdam","2027-11-15"),("dns","Top","DuDu","2028-11-20"),("dns","Jungle","Cuzz",""),
  ("dk","Jungle","Lucid","2027-11-15"),("dk","Support","Career","2027-11-15"),("dk","Top","Siwoo","2027-11-15"),
  ("geng","Bot","Ruler","2027-11-15"),("geng","Support","Duro","2027-11-15"),("geng","Mid","Chovy","2027-11-15"),
  ("bro","Support","Namgung","2027-11-15"),("bro","Top","Casting","2027-11-15"),("bro","Jungle","GIDEON","2027-11-15"),("bro","Mid","Roamer","2027-11-15"),("bro","Bot","Teddy","2027-11-15"),
  ("hle","Bot","Gumayusi","2027-11-15"),("hle","Mid","Zeka","2027-11-15"),("hle","Support","Delight","2027-11-15"),
  ("kt","Mid","Bdd","2028-11-20"),("kt","Top","PerfecT","2028-11-20"),
  ("t1","Support","Keria","2029-11-19"),("t1","Mid","Faker","2029-11-19"),("t1","Bot","Peyz","2028-11-20"),("t1","Jungle","Oner","2028-11-20"),
  ("t1","Coach","Tom","2026-11-16"),("hle","Streamer","Someone","")]]
fam.cargo = fake_cargo
fam.REQUEST_GAP = 0
fam.poll_fa(0)
_orig = fake_collect
def fake_collect2():
    fam.poll_fa(0)
    _orig()
jobs.manual_collect = fake_collect2  # request_manual가 부르는 함수만 가짜로 바꿈
server.chat.init()
server.player_extra.init()
server.maint.init()
server.share.init()
server.riot.start()
server.load_static()
port = int(os.environ.get("PORT", "8099"))
print(f"dev server: http://127.0.0.1:{port}/lck", flush=True)
server.ThreadingHTTPServer(("127.0.0.1", port), server.Handler).serve_forever()
