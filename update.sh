#!/bin/sh
# 클라우드 서버에서 1분마다 실행 (crontab)
#  1) 사이트가 멈춰 있으면(Docker 헬스체크 unhealthy) 컨테이너 재시작
#  2) GitHub main에 새 코드가 올라왔으면 받아서 반영
#     - 반영 전: tests/ 테스트를 먼저 돌려서 실패하면 반영하지 않음
#     - 반영 후: 주요 화면이 2분 안에 열리지 않으면 직전 코드로 되돌림
#     - 실패한 커밋은 .deploy_bad 에 적어 두고 다시 시도하지 않음(새 커밋이 올라오면 다시 시도)
#     커밋 메시지에 [restart]가 있으면 코드가 그대로여도 재시작
cd "$(dirname "$0")" || exit 1
NAME=lck-stove-tracker
BAD=.deploy_bad
HEALTH_WAIT=${HEALTH_WAIT:-120}          # 반영 후 화면이 열릴 때까지 기다리는 최대 초
HEALTH_PATHS="/healthz /lck /lck/roster /lck/fa /lck/schedule"
TEST_IMAGE=${TEST_IMAGE:-python:3.12-slim}
log() { echo "$(date '+%F %T') $*"; }
docker_on() { docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$NAME"; }

# 1분 안에 끝나지 않은 앞 실행(반영·확인 중)과 겹치지 않게
if command -v flock >/dev/null 2>&1; then
  exec 9>"${TMPDIR:-/tmp}/teemofarm-update.lock"
  flock -n 9 || exit 0
fi

if docker_on && [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$NAME" 2>/dev/null)" = unhealthy ]; then
  log "응답 없음 → 재시작"
  docker restart "$NAME" >/dev/null
fi

git fetch -q origin main || exit 1
OLD=$(git rev-parse HEAD); NEW=$(git rev-parse origin/main)
[ "$OLD" = "$NEW" ] && exit 0
[ -f "$BAD" ] && [ "$(cat "$BAD")" = "$NEW" ] && exit 0          # 이미 실패한 커밋: 새 커밋을 기다림

run_tests() {
  [ -d tests ] || return 0
  docker run --rm -v "$PWD:/src:ro" -w /src -e DB_PATH=/tmp/test.db -e PYTHONDONTWRITEBYTECODE=1 \
    "$TEST_IMAGE" python -m unittest discover -s tests >/tmp/teemofarm-test.log 2>&1
}

healthy() {
  end=$(( $(date +%s) + HEALTH_WAIT ))
  while [ "$(date +%s)" -lt "$end" ]; do
    sleep 5
    docker exec "$NAME" python -c "
import sys, urllib.request
for p in sys.argv[1:]:
    urllib.request.urlopen('http://127.0.0.1:8080' + p, timeout=10).read()
" $HEALTH_PATHS >/dev/null 2>&1 && return 0
  done
  return 1
}

fail() {   # $1: 이유. 코드를 OLD로 되돌리고, 컨테이너가 이미 바뀌었으면 OLD로 다시 띄움
  echo "$NEW" > "$BAD"
  git reset -q --hard "$OLD"
  if [ "$2" = rebuild ]; then
    docker compose up -d --build --force-recreate >/dev/null 2>&1
    if healthy; then log "되돌림 완료: $(git log -1 --format='%h %s')"; else log "되돌렸지만 아직 응답 없음 — 서버를 직접 확인해 주세요"; fi
  fi
  log "반영 실패($1) → $(git rev-parse --short "$NEW") 건너뜀, $(git rev-parse --short "$OLD") 유지"
  exit 1
}

git reset -q --hard "$NEW"
if docker_on; then
  if ! run_tests; then
    tail -20 /tmp/teemofarm-test.log
    fail "테스트 실패"
  fi
  if git log --format=%s "$OLD..$NEW" | grep -q '\[restart\]'; then
    log "재시작 요청 → 다시 띄움"
    docker compose up -d --build --force-recreate || fail "빌드 실패" rebuild
  else
    docker compose up -d --build || fail "빌드 실패" rebuild
  fi
  healthy || fail "${HEALTH_WAIT}초 안에 화면이 열리지 않음" rebuild
fi
rm -f "$BAD"
log "반영: $(git log -1 --format='%h %s')"
