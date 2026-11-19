# 티모의 버섯농장 — 작업 안내 (Claude용)

LoL 리그(지금은 LCK) 소식·로스터·이적·로스터 짜기를 보여 주는 개인 팬 사이트. 도메인 `teemofarm.com`.
기능·화면 설명은 `README.md`를 볼 것.

## 꼭 지킬 것
- **파이썬 표준 라이브러리만** 쓴다. pip 패키지, 프런트 프레임워크·빌드 도구를 들이지 않는다.
- **`data/`(DB·백업·아카이브)는 저장소에 없고, 넣지도 않는다.** 서버마다 따로 쌓인다.
- 임시·시험 파일을 저장소 안에 만들지 않는다. 필요하면 `/tmp` 등 밖에 만들고 끝나면 지운다.
- 화면 문구는 한국어, 짧고 친근하게. 새 화면·큰 UI 변경은 **시안(캡처)을 먼저 보여 주고** 확인받은 뒤 구현한다.
- 사용자에게 설명할 때도 한국어로.

## 구조 (요약)
- `app.py`: 감독 프로세스. `tracker/` 파일이 바뀌면 서버를 다시 띄운다(Docker에서는 `RELOAD=0`).
- `tracker/`: 수집(`wiki.py`, `news.py`, `fa.py`, `cargo.py`, `archive.py`, `player_extra.py`, `maint.py`), 판정(`filters.py`, `cluster.py`, `insight.py`, `classify.py`), 기타(`chat.py`, `share.py`, `riot.py`)
- `tracker/web/server.py`: 주소·API, `tracker/web/views.py`: HTML, `tracker/web/static/`: CSS·JS
- 정적 파일 주소의 `?v=`는 파일 내용 해시로 자동으로 바뀐다(캐시 걱정 없음).
- 설정 데이터: `tracker/site.json`(후원·제휴 링크), `leagues.json`, `team_profiles.json`

## 확인 방법 (수정 후 반드시, 셋 다 통과해야 함)
```bash
python -m unittest discover -s tests          # 단위 테스트 + 자바스크립트 함수 이름 겹침 검사(tests/test_jscheck.py)
python tools/dev_server.py &                  # 가짜 데이터 서버 http://127.0.0.1:8099 (인터넷 수집 없음, 일정·결과 가짜 경기 포함)
node tools/smoke.js http://127.0.0.1:8099     # 모든 페이지 열기: 휴대폰·태블릿·PC × 라이트·다크
node tools/flows.js http://127.0.0.1:8099     # 사용 흐름: 메뉴·하위 탭·팀 탭·팝업·토글·투표를 실제로 눌러 봄
```
- `flows.js`는 같은 흐름을 **처음 온 사람**(저장소 비어 있음)과 **써 본 사람**(내 팀·지난 시즌 선택·필터 기억·스포 방지 등이 이미 켜짐) 두 번 돌린다.
  "페이지가 열린다"만으로는 부족하다. 예전에 빠져나간 버그: 팀 탭을 누르면 빈 팝업(함수 이름 겹침), 메뉴마다 시즌이 다름(필터 기억이 시즌까지 기억).
- 같은 점검이 GitHub에 push할 때마다 자동으로 돈다(.github/workflows/test.yml의 browser 작업). 빨간불이면 고치고 다시 올린다.
- 바꾼 화면은 smoke.js가 출력하는 캡처 폴더의 캡처를 직접 열어 본다.
- 실제 데이터(뉴스·로스터)는 시험 서버에 없다. 반영 후 `teemofarm.com`에서 한 번 더 본다.

## 새 기능을 만들 때 규칙
- **브라우저에 무언가를 기억시키는 기능**(localStorage·sessionStorage·쿠키)을 만들거나 바꾸면, `tools/flows.js`의 '써 본 사람' 저장값에 그 값을 넣고,
  그 값이 남아 있을 때 다른 메뉴·시즌·팀 화면이 이상해지지 않는지 흐름을 추가한다. 기억한 값끼리 섞이지 않는지(예: 시즌 + 필터)도 본다.
- **누르는 것**(탭·버튼·팝업)을 새로 만들면 flows.js에 눌러 보는 흐름을 추가한다. 눌렀을 때 화면이 바뀌는지, 빈 팝업이 안 뜨는지 확인한다.
- 자바스크립트는 파일 하나가 즉시 실행 함수 하나로 감싸져 있어 이름이 겹치기 쉽다. 새 함수는 기존 이름과 겹치지 않게 짓는다(test_jscheck가 잡아 줌).

## 배포
- `main`에 들어가면 클라우드 서버의 `update.sh`(cron, 1분마다)가 받아서 Docker 이미지를 새로 만들어 반영한다.
- 작업은 브랜치 → PR → 사용자가 Merge. `main`에 직접 올리지 않는다.
- 코드 변경 없이 서버만 다시 띄우려면 커밋 메시지에 `[restart]`를 넣은 빈 커밋을 올린다.
- 사이트가 응답하지 않으면(헬스체크 unhealthy) `update.sh`가 알아서 재시작한다. 기록은 서버의 `data/update.log`.

## 외부 데이터 주의
- 리그피디아 Cargo API는 요청 한도가 빡빡하다. 요청 간격(`CARGO_GAP_SEC`)을 줄이거나 반복 호출을 늘리지 않는다.
- 구글 뉴스 RSS는 429가 나면 막힌다. `news.py`의 전역 간격·차단 로직을 유지한다.
