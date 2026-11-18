#!/bin/sh
# 클라우드 서버에서 1분마다 실행 (crontab)
#  1) 사이트가 멈춰 있으면(Docker 헬스체크 unhealthy) 컨테이너 재시작
#  2) GitHub에 새 코드가 올라왔으면 받아서 반영
#     커밋 메시지에 [restart]가 있으면 코드가 그대로여도 재시작
cd "$(dirname "$0")" || exit 1
NAME=lck-stove-tracker
log() { echo "$(date '+%F %T') $*"; }
docker_on() { docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$NAME"; }

if docker_on && [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$NAME" 2>/dev/null)" = unhealthy ]; then
  log "응답 없음 → 재시작"
  docker restart "$NAME" >/dev/null
fi

git fetch -q origin main || exit 1
OLD=$(git rev-parse HEAD); NEW=$(git rev-parse origin/main)
[ "$OLD" = "$NEW" ] && exit 0
git reset -q --hard origin/main
if docker_on; then
  if git log --format=%s "$OLD..$NEW" | grep -q '\[restart\]'; then
    log "재시작 요청 → 다시 띄움"
    docker compose up -d --build --force-recreate
  else
    docker compose up -d --build
  fi
fi
log "반영: $(git log -1 --format='%h %s')"
