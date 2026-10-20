#!/usr/bin/env bash
# Бэкап базы стенда: pg_dump → /srv/tuc/backups/<стенд>-ГГГГ-ММ-ДД.sql.gz, хранит 14 дней.
# Ставится в cron для прода скриптом bootstrap.sh (03:15 каждую ночь). Можно запустить руками.
# Восстановление: zcat файл.sql.gz | docker compose exec -T postgres psql -U tuc -d tuc
# Загруженные модели (data/) в бэкап не входят — они большие; при переезде копируйте папку data/.
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$DIR"
STACK=$(basename "$DIR")
OUT=${BACKUP_DIR:-/srv/tuc/backups}
KEEP_DAYS=${KEEP_DAYS:-14}
mkdir -p "$OUT"

PG_USER=$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2 | awk '{print $1}')
PG_DB=$(grep -E '^POSTGRES_DB=' .env | cut -d= -f2 | awk '{print $1}')
FILE="$OUT/$STACK-$(date +%F).sql.gz"

docker compose exec -T postgres pg_dump -U "${PG_USER:-tuc}" -d "${PG_DB:-tuc}" | gzip > "$FILE.tmp"
mv "$FILE.tmp" "$FILE"
find "$OUT" -name "$STACK-*.sql.gz" -mtime +"$KEEP_DAYS" -delete
echo "$(date '+%F %T') $FILE $(du -h "$FILE" | cut -f1)"
