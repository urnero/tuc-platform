#!/usr/bin/env bash
# Собирает sites/<стенд>.caddy из site.caddy.tmpl по доменам из .env и применяет к Caddy.
# Запускать можно сколько угодно раз — результат одинаковый. Зовут bootstrap.sh и deploy.sh.
# RENDER_ONLY=1 — только записать файлы, Caddy не трогать (так проверяет CI).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

[ -f .env ] || { echo "нет deploy/edge/.env — скопируйте .env.example и заполните" >&2; exit 1; }
set -a
# shellcheck source=/dev/null
. ./.env
set +a
: "${PROD_DOMAIN:?PROD_DOMAIN пуст в deploy/edge/.env}"

render() { # render <стенд> <домен> <доп. строки внутри блока>
	sed -e "s/__DOMAIN__/$2/g" -e "s/__STACK__/$1/g" -e "s|__EXTRA__|$3|" site.caddy.tmpl > "sites/$1.caddy"
	echo "sites/$1.caddy → $2"
}

mkdir -p sites
render prod "$PROD_DOMAIN" ""
if [ -n "${STAGING_DOMAIN:-}" ]; then
	# тестовый стенд не должен попасть в поисковики
	render staging "$STAGING_DOMAIN" '\theader X-Robots-Tag "noindex, nofollow"'
else
	rm -f sites/staging.caddy
fi

[ "${RENDER_ONLY:-}" = 1 ] && exit 0

# Поднять Caddy (если ещё не запущен) и перечитать конфигурацию без разрыва соединений.
docker compose up -d
for _ in 1 2 3 4 5; do
	if docker compose exec -T -w /etc/caddy caddy caddy reload --config /etc/caddy/Caddyfile; then
		exit 0
	fi
	sleep 2
done
echo "Caddy не перечитал конфигурацию, смотрите: docker compose logs caddy" >&2
exit 1
