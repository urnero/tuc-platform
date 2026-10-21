#!/usr/bin/env bash
# Пользователь БД только для чтения (B11) — чтобы подключать Superset, DBeaver, pandas к заказам,
# не рискуя что-то изменить. Запуск на сервере из папки стенда (или локально, где есть Docker):
#   cd /srv/tuc/prod && bash deploy/readonly-user.sh
# Пароль берёт из .env (POSTGRES_RO_PASSWORD); если там пусто — придумывает и дописывает в .env.
# Повторный запуск безопасен: роль не пересоздаётся, пароль и права обновляются (deploy/readonly-user.sql).
#
# Снаружи БД видна только на 127.0.0.1 сервера (порт POSTGRES_LOCAL_PORT, см. compose.server.yml).
# С ноутбука — через SSH-туннель:  ssh -N -L 5433:127.0.0.1:5433 deploy@<домен>
# и тогда в Superset/DBeaver: host 127.0.0.1, port 5433, db tuc, user tuc_ro, пароль из .env.
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$DIR"
[ -f .env ] || { echo "Нет .env в $DIR" >&2; exit 1; }

env_get() { grep -E "^$1=" .env | head -n1 | cut -d= -f2- | awk '{print $1}'; }

PG_USER=$(env_get POSTGRES_USER); PG_USER=${PG_USER:-tuc}
PG_DB=$(env_get POSTGRES_DB); PG_DB=${PG_DB:-tuc}
RO_USER=$(env_get POSTGRES_RO_USER); RO_USER=${RO_USER:-tuc_ro}
RO_PASS=$(env_get POSTGRES_RO_PASSWORD)
if [ -z "$RO_PASS" ]; then
	RO_PASS=$(head -c 64 /dev/urandom | base64 | tr -d '/+=\n' | cut -c1-24)
	if grep -q '^POSTGRES_RO_PASSWORD=' .env; then
		sed -i "s|^POSTGRES_RO_PASSWORD=.*|POSTGRES_RO_PASSWORD=$RO_PASS|" .env
	else
		printf '\n# --- read-only пользователь БД для Superset (B11, добавил readonly-user.sh) ---\nPOSTGRES_RO_USER=%s\nPOSTGRES_RO_PASSWORD=%s\n' "$RO_USER" "$RO_PASS" >> .env
	fi
	echo "Пароль придуман и записан в .env (POSTGRES_RO_PASSWORD)."
fi

docker compose exec -T postgres psql -q -v ON_ERROR_STOP=1 \
	-U "$PG_USER" -d "$PG_DB" \
	-v ro_user="$RO_USER" -v ro_pass="$RO_PASS" -v db="$PG_DB" -v owner="$PG_USER" \
	< deploy/readonly-user.sql

PORT=$(env_get POSTGRES_LOCAL_PORT); PORT=${PORT:-5433}
echo "Готово: пользователь $RO_USER читает базу $PG_DB."
echo "Подключение с ноутбука: ssh -N -L $PORT:127.0.0.1:$PORT deploy@<домен>, затем host 127.0.0.1, port $PORT, db $PG_DB, user $RO_USER."
