#!/usr/bin/env bash
# Обновляет один стенд до последнего коммита его ветки и перезапускает контейнеры.
# Лежит внутри стенда (/srv/tuc/prod или /srv/tuc/staging), стенд определяет по своему пути.
# Запускают: GitHub Actions после зелёного CI (.github/workflows/deploy.yml), bootstrap.sh,
# или владелец руками: ssh deploy@сервер bash /srv/tuc/prod/deploy/deploy.sh
# Необязательный аргумент — коммит, который нужно развернуть (Actions передают проверенный CI);
# без него берётся последний коммит ветки.
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$DIR"
STACK=$(basename "$DIR")                         # prod | staging
BRANCH=$(git rev-parse --abbrev-ref HEAD)        # main | dev — та, с которой клонировали
TARGET=${1:-origin/$BRANCH}
[ -f .env ] || { echo "нет $DIR/.env — сначала bootstrap.sh" >&2; exit 1; }

echo "=== $STACK: обновляю код (ветка $BRANCH)"
git fetch -q origin "$BRANCH"
git reset -q --hard "$TARGET"                    # на сервере код не правят — всё через git
echo "    $(git log -1 --format='%h %s')"

echo "=== $STACK: собираю образы и перезапускаю контейнеры"
docker compose up -d --build --remove-orphans

echo "=== $STACK: жду api (/health)"
API=$(docker compose ps -q api)
for _ in $(seq 1 40); do                         # до ~2 минут: миграции + старт
	status=$(docker inspect --format '{{.State.Health.Status}}' "$API" 2>/dev/null || echo none)
	[ "$status" = healthy ] && break
	sleep 3
done
if [ "$status" != healthy ]; then
	echo "api не поднялся (статус: $status). Логи:" >&2
	docker compose logs --tail=50 api >&2
	exit 1
fi
SITE_URL=$(grep -E '^SITE_URL=' .env | cut -d= -f2 | awk '{print $1}')
if [ -n "$SITE_URL" ] && curl -fsS --max-time 10 "$SITE_URL/health" >/dev/null 2>&1; then
	echo "    $SITE_URL/health отвечает"
else
	echo "    снаружи $SITE_URL/health пока не отвечает — проверьте DNS и логи Caddy (не ошибка на первом запуске)"
fi

# Общий Caddy живёт в стенде prod: после обновления прода перечитываем домены.
if [ -f deploy/edge/.env ]; then
	echo "=== $STACK: общий Caddy"
	bash deploy/edge/render-sites.sh
fi

docker image prune -f >/dev/null                 # старые слои образов, чтобы диск не кончился
echo "=== $STACK готов: $(git log -1 --format='%h')"
