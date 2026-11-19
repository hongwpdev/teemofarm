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

## 확인 방법 (수정 후 반드시)
```bash
python tools/dev_server.py &                 # 가짜 데이터 서버 http://127.0.0.1:8099 (인터넷 수집 없음)
node tools/smoke.js http://127.0.0.1:8099    # 휴대폰·태블릿·PC × 라이트·다크로 주요 페이지 점검, 실패 0건이어야 함
```
- `smoke.js`는 Playwright가 필요하다. 캡처 폴더 경로를 출력하니, 바꾼 화면은 캡처를 직접 열어 확인한다.
- 실제 데이터(뉴스·로스터)는 시험 서버에 없다. 반영 후 `teemofarm.com`에서 한 번 더 본다.

## 배포
- `main`에 들어가면 클라우드 서버의 `update.sh`(cron, 1분마다)가 받아서 Docker 이미지를 새로 만들어 반영한다.
- 작업은 브랜치 → PR → 사용자가 Merge. `main`에 직접 올리지 않는다.
- 코드 변경 없이 서버만 다시 띄우려면 커밋 메시지에 `[restart]`를 넣은 빈 커밋을 올린다.
- 사이트가 응답하지 않으면(헬스체크 unhealthy) `update.sh`가 알아서 재시작한다. 기록은 서버의 `data/update.log`.

## 외부 데이터 주의
- 리그피디아 Cargo API는 요청 한도가 빡빡하다. 요청 간격(`CARGO_GAP_SEC`)을 줄이거나 반복 호출을 늘리지 않는다.
- 구글 뉴스 RSS는 429가 나면 막힌다. `news.py`의 전역 간격·차단 로직을 유지한다.
