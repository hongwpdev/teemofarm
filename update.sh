#!/bin/sh
# 클라우드 서버에서 1분마다 실행: GitHub에 새 코드가 올라왔으면 받아서 반영
cd "$(dirname "$0")" || exit 1
git fetch -q origin main || exit 1
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && exit 0
git reset -q --hard origin/main
# Docker로 돌고 있으면 이미지를 새로 만들어 재시작 (직접 실행 중이면 app.py가 알아서 다시 읽음)
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx lck-stove-tracker; then
  docker compose up -d --build
fi
echo "$(date '+%F %T') 반영: $(git log -1 --format='%h %s')"
