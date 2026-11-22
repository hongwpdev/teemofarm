# 티모의 버섯농장

LoL 리그별 소식·로스터·이적을 한 화면에 모아 보여줍니다. 소식·로스터·이적은 지금 **LCK**만 켜져 있고,
LPL·LEC·LCS·LCP·CBLOL은 **일정·결과**(`/lpl/schedule` 등)만 보이고 나머지 메뉴는 '곧 추가'로 보입니다.

- **소식** `/lck` — 리그피디아 팀 페이지 편집 기록(5분마다) + 구글 뉴스 RSS 검색(10분마다)
- **로스터** `/lck/roster` — 리그피디아 계약 기준 현재 선수 5포지션 + 감독(30분마다)
- **이적·FA** `/lck/fa` — 이번 스토브리그에 계약이 끝난 선수·코치와 이적·잔류·미정 상태(30분마다)
- **일정·결과** `/lck/schedule` — 리그피디아 경기 일정·결과·순위표(경기 날 5분마다, 평소 30분마다). 지금 시즌 일정이 아직 없으면(스토브리그) 지난 시즌 마지막 결과를 보여 주고,
  새 시즌 일정이 올라오면 저절로 바뀌어요. 팀 탭으로 거르기, 내 팀 경기 강조, '스포 방지'를 켜면 점수를 가려요. JSON: `/api/schedule?league=lpl`
  끝난 경기를 누르면 **경기 상세 팝업**: 세트별 밴픽, 선수 10명의 챔피언·KDA·CS·골드·피해량, 오브젝트, 다시보기(리그피디아 기록,
  누를 때만 받아 DB에 저장). 선수 이름을 누르면 선수 프로필(커리어·관련 소식)로 넘어가고 '← 경기 기록으로'로 돌아와요. 챔피언 한국어 이름·아이콘은 라이엇 Data Dragon(하루 한 번). JSON: `/api/match?league=lck&id=<MatchId>`
- 예전 주소 `/`, `/fa`는 `/lck`, `/lck/fa`로 넘어가요(쿼리 그대로).

## 실행
```bash
docker compose up -d --build      # 코드를 바꾼 뒤에는 꼭 --build
# 브라우저: http://<서버>:8088
```
로컬 테스트: `DB_PATH=./data/stove.db PORT=8088 python app.py` (파이썬 3.10+, 표준 라이브러리만 사용)
테스트: `python -m unittest discover -s tests` (GitHub에 push하면 Actions에서도 자동으로 돌아요)

**서버 자동 반영(`update.sh`, 1분마다 크론)**: GitHub `main`에 새 커밋이 오면
1. 테스트를 먼저 돌려서(도커 `python:3.12-slim`) 실패하면 반영하지 않아요.
2. 반영 후 2분 안에 주요 화면(`/healthz`·`/lck`·로스터·이적·일정)이 열리지 않으면 직전 코드로 되돌려요.
3. 실패한 커밋은 `.deploy_bad`에 적어 두고 다시 시도하지 않아요. 고친 커밋을 올리면 다시 반영해요.
커밋 메시지에 `[restart]`가 있으면 코드가 그대로여도 다시 띄워요.
4. 결과를 디스코드 운영 채널로 알려요(`tools/ops_notify.py`): 재시작·반영 실패(되돌림, 테스트 기록 끝부분 포함)·반영 성공.
   성공하면 Cloudflare 캐시를 비우고, 실제 주소의 주요 화면과 데이터 점검(`/api/integrity`·`/api/rumor-audit`) 결과를 한 번에 보내요.
   설정은 서버의 `.env`(저장소에는 넣지 않음): `DISCORD_OPS_WEBHOOK`(운영 채널), `CF_ZONE_ID`·`CF_API_TOKEN`(Cache Purge 권한),
   `SITE_BASE_URL`(기본 `https://teemofarm.com`). 없으면 그 부분만 건너뛰고 `data/update.log`에만 남아요.

**자동 재시작**: `python app.py`로 직접 띄우면 app.py가 감독 역할만 하고 서버를 따로 띄워요.
`tracker/` 아래 파일이 바뀌면 3~5초 안에 서버를 알아서 다시 띄우고, 서버가 죽어도 5초 뒤 다시 띄워요.
끌 때는 그 창에서 Ctrl+C 한 번. 끄고 싶지 않으면 `RELOAD=0` (도커 이미지는 RELOAD=0으로 돌아요).

## 파일 구성
```
app.py                 시작 파일
tracker/config.py      설정(환경변수)·리그·팀 목록·판정 단어
tracker/core.py        HTTP·DB·날짜 도우미     tracker/classify.py  기사 성격·팀 판정·위키 요약 한국어
tracker/cargo.py       리그피디아 Cargo 조회(간격·한도 재시도)
tracker/wiki.py        수집: 편집 기록        tracker/news.py      수집: 뉴스(팀 검색어 + FA 본명)
tracker/fa.py          수집: FA·로스터·선수 프로필
tracker/schedule.py    수집: 리그별 경기 일정·결과·순위(data/schedule_<리그>.json 에도 저장)
tracker/matchinfo.py   경기 상세(세트별 밴픽·선수 기록)      tracker/champs.py    챔피언 한국어 이름·아이콘(Data Dragon)
tracker/teamlogos.py   해외 팀 로고(리그피디아에서 64px로 한 번 받아 data/logos/ 에 저장, /tlogo/<팀> 으로 내보냄).
                       선수 커리어에서 처음 본 팀은 뒤에서 2분마다 40팀씩 받아 둠
tracker/jobs.py        수집 일정·[조회]
tracker/logos.py       팀 로고(배경 없는 PNG)
tracker/web/views.py   화면 HTML              tracker/web/server.py 주소·API·시작
tracker/web/static/    base.css, common.js, news.js, fa.js, roster.js, player.js
```

## 화면
- **보기**: 전체(기본) / 오피셜 / +루머. 기사마다 성격 배지(오피셜 · 단독·유력 · 전망·분석)가 붙어요.
  판정 단어는 `HOT_WORDS`·`NOT_HOT_WORDS`·`RUMOR_WORDS`·`VIEW_WORDS` 환경변수(쉼표 구분)로 바꿀 수 있어요.
- **필터**(접힘): 기간(전체·오늘·어제·최근 3일·최근 7일·직접 선택), 출처(모든 출처·뉴스만·리그피디아만), [조회], 자동 조회
- **내 팀**: 팀 탭을 고르고 '내 팀으로 정하기' → 다음에 들어오면 그 팀이 먼저 보이고, 로스터에서도 맨 앞에 와요(브라우저마다 기억)
- 리그피디아 편집 요약은 '로스터 변경: Zeus 이탈'처럼 한국어 한 줄로 보여 주고, 표 정리·오타 같은 사소한 편집은 숨겨요.
- 선수 이름(이적·FA, 로스터)을 누르면 프로필 팝업: 커리어, 관련 소식, 리그피디아 바로가기(선수 사진은 넣지 않음)
- PC(1100px 이상)에서는 오른쪽에 스토브리그 현황과 고른 팀 로스터 요약
- **[조회]**: 소식 화면은 위키·뉴스·FA 전부(2분 쿨다운, `MANUAL_COOLDOWN_SEC`), 로스터·이적 화면은 FA·로스터만(30초, `FA_COOLDOWN_SEC`)
- JSON: `/api/items`, `/api/player?page=<리그피디아 문서 이름>`

## 팀·검색어 바꾸기
`teams.example.json`(기본값과 같음)을 `data/teams.json`으로 복사·수정하고 compose의 `TEAMS_FILE` 주석을 풀어 주세요.
`short`는 탭에 보일 짧은 이름, `aliases`는 제목에서 그 팀을 찾을 이름(영문은 단어 단위), `color`·`logo`도 넣을 수 있어요.

## 리그 추가(예정)
`tracker/config.py`의 `LEAGUES`에서 리그를 `enabled: True`로 바꾸고 `teams`를 채우는 방식으로 늘릴 예정이에요.
DB의 `items`·`fa`에는 이미 `league` 칸이 있어요(기존 데이터는 `lck`).

## 요청량
- 뉴스: 한 바퀴에 팀 검색어 23건 + FA 본명 검색(5명씩 묶음), 요청 사이 1.5초(`REQUEST_GAP_SEC`)
- 리그피디아(Cargo·편집 기록·로고 정보 모두): 요청 사이 최소 2초(`CARGO_GAP_SEC`, 모든 수집이 함께 지킴), 한도에 걸리면 20초 뒤 한 번 더
  - 위키 편집 기록(5분마다): 10팀 문서의 마지막 편집 번호를 한 번에 확인(1번)하고 바뀐 팀만 받음. 본 번호는 DB에 저장
  - FA·로스터(30분마다): 이적 기록(1번)이 그대로면 나머지를 건너뜀. 3시간마다(수동 [조회]는 30분 지났으면) 전부 새로
  - 선수 커리어는 하루에 한 번만 새로(`PROFILE_MAX_AGE_SEC`), 일정은 비시즌 3시간·경기 앞뒤 5분
  - 대략 시간당 15~20번(예전 130번 안팎)

## 한계
- 구단 X(트위터)를 직접 읽지 않아서, 오피셜 직후 수십 분 늦을 수 있어요(구글 뉴스 반영 지연 포함).
- 리그피디아는 편집자가 반영해야 잡혀요. 로스터·FA 상태도 그 기준이에요.
- 구글 뉴스 RSS는 비공식 엔드포인트라 형식이 바뀔 수 있어요.
