#!/usr/bin/env bash
# Первичная настройка чистого VPS (Ubuntu 24.04) под платформу ТУЦ. Запускать один раз от root:
#
#   scp deploy/bootstrap.sh root@<IP>:   # с ноутбука, из клона репозитория
#   ssh root@<IP> bash bootstrap.sh tuc3d.ru staging.tuc3d.ru you@mail.ru
#
# Аргументы: <боевой домен> [тестовый домен или "-"] <почта для Let's Encrypt>
# Что делает (подробно — docs/DEPLOY.md):
#   1. ставит Docker, git, ufw; включает файрвол (22, 80, 443); добавляет swap 2 ГБ;
#   2. создаёт пользователя deploy (в группе docker), с ним работают GitHub Actions;
#   3. делает два SSH-ключа: для чтения репозитория с GitHub и для входа Actions на сервер;
#   4. клонирует репозиторий в /srv/tuc/prod (ветка main) и /srv/tuc/staging (ветка dev);
#   5. пишет .env стендов (случайные пароли БД и админки) и общего Caddy;
#   6. поднимает Caddy с HTTPS и оба стенда; ставит ночной бэкап БД прода.
# Скрипт можно запускать повторно: готовые шаги он пропускает.
set -euo pipefail

PROD_DOMAIN="${1:-}"
STAGING_DOMAIN="${2:-}"
ACME_EMAIL="${3:-}"
[ "$STAGING_DOMAIN" = "-" ] && STAGING_DOMAIN=""
if [ -z "$PROD_DOMAIN" ] || [ -z "$ACME_EMAIL" ]; then
	echo "использование: bash bootstrap.sh <боевой домен> [тестовый домен | -] <почта для Let's Encrypt>" >&2
	exit 1
fi
[ "$(id -u)" = 0 ] || { echo "запускать от root" >&2; exit 1; }

REPO="${REPO:-git@github.com:urnero/tuc-platform.git}"
ROOT=/srv/tuc
DEPLOY_USER=deploy
ACTIONS_KEY=$ROOT/.actions_key   # приватный ключ для GitHub Secrets → DEPLOY_SSH_KEY

step() { echo; echo "=== $*"; }

# --- 1. пакеты, Docker, файрвол, swap ---------------------------------------------------------
step "Пакеты и Docker"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
# docker.io и docker-compose-v2 — из репозитория Ubuntu 24.04: без сторонних ключей и зеркал
apt-get install -y -q ca-certificates curl git ufw cron docker.io docker-compose-v2
systemctl enable --now docker
docker compose version

step "Файрвол: 22, 80, 443"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 443/udp >/dev/null
ufw --force enable >/dev/null
ufw status | head -n 8

if [ ! -f /swapfile ]; then
	step "Swap 2 ГБ (сборка web и слайсер любят память)"
	fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
	echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

# --- 2. пользователь deploy --------------------------------------------------------------------
step "Пользователь $DEPLOY_USER"
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
	adduser --disabled-password --gecos "" "$DEPLOY_USER"
fi
usermod -aG docker "$DEPLOY_USER"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
# владелец заходит на сервер тем же ключом, что и root
if [ -f /root/.ssh/authorized_keys ]; then
	cat /root/.ssh/authorized_keys >> "/home/$DEPLOY_USER/.ssh/authorized_keys"
fi
install -d -m 755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$ROOT" "$ROOT/backups"

as_deploy() { sudo -u "$DEPLOY_USER" -H bash -c "$*"; }

# --- 3. ключи ----------------------------------------------------------------------------------
step "SSH-ключи"
GH_KEY="/home/$DEPLOY_USER/.ssh/id_ed25519"
if [ ! -f "$GH_KEY" ]; then
	as_deploy "ssh-keygen -q -t ed25519 -N '' -C 'tuc-vps-readonly' -f $GH_KEY"
fi
as_deploy "ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null"
if [ ! -f "$ACTIONS_KEY" ]; then
	ssh-keygen -q -t ed25519 -N '' -C 'github-actions-deploy' -f "$ACTIONS_KEY"
	cat "$ACTIONS_KEY.pub" >> "/home/$DEPLOY_USER/.ssh/authorized_keys"
fi
sort -u -o "/home/$DEPLOY_USER/.ssh/authorized_keys" "/home/$DEPLOY_USER/.ssh/authorized_keys"  # без дублей при повторном запуске
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh/authorized_keys"
chmod 600 "/home/$DEPLOY_USER/.ssh/authorized_keys" "$ACTIONS_KEY"

if ! as_deploy "git ls-remote -q $REPO HEAD >/dev/null 2>&1"; then
	echo
	echo "Репозиторий приватный: добавьте этот ключ в GitHub → репозиторий → Settings → Deploy keys"
	echo "(Add deploy key, название 'VPS', галочку Allow write access НЕ ставить):"
	echo
	cat "$GH_KEY.pub"
	echo
	read -r -p "Добавили? Нажмите Enter, чтобы продолжить… "
	as_deploy "git ls-remote -q $REPO HEAD >/dev/null" || { echo "GitHub не пускает. Проверьте ключ и запустите скрипт снова." >&2; exit 1; }
fi

# --- 4–5. клоны и .env -------------------------------------------------------------------------
rand() { # случайная строка из букв и цифр длиной $1
	local s
	s=$(head -c 64 /dev/urandom | base64 | tr -d '/+=\n')
	echo "${s:0:$1}"
}

make_stand() { # make_stand <стенд> <ветка> <домен>
	local stack=$1 branch=$2 domain=$3 dir=$ROOT/$1
	step "Стенд $stack: $dir (ветка $branch, https://$domain)"
	if [ ! -d "$dir/.git" ]; then
		as_deploy "git clone -q -b $branch $REPO $dir"
	fi
	if [ ! -f "$dir/.env" ]; then
		local pg_pass admin_pass
		pg_pass=$(rand 24); admin_pass=$(rand 20)
		as_deploy "cp $dir/.env.example $dir/.env"
		sed -i \
			-e "s|^APP_ENV=.*|APP_ENV=$stack|" \
			-e "s|^SITE_URL=.*|SITE_URL=https://$domain|" \
			-e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$pg_pass|" \
			-e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg://tuc:$pg_pass@postgres:5432/tuc|" \
			-e "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$admin_pass|" \
			"$dir/.env"
		cat >> "$dir/.env" <<-EOF

		# --- сервер (B10, добавил bootstrap.sh) ---
		COMPOSE_PROJECT_NAME=tuc-$stack          # имена контейнеров tuc-$stack-<сервис>-1 — их ждёт общий Caddy
		COMPOSE_FILE=docker-compose.yml:deploy/compose.server.yml
		EOF
		chown "$DEPLOY_USER:$DEPLOY_USER" "$dir/.env"
		chmod 600 "$dir/.env"
		echo "  .env создан. Пароль админки ($domain/admin, логин admin): $admin_pass"
		echo "  Он же лежит в $dir/.env (ADMIN_PASSWORD). Туда же впишите токены Telegram и ЮKassa."
	else
		echo "  .env уже есть — не трогаю"
	fi
}

make_stand prod main "$PROD_DOMAIN"
if [ -n "$STAGING_DOMAIN" ]; then
	make_stand staging dev "$STAGING_DOMAIN"
fi

# --- 6. общий Caddy, стенды, бэкап ----------------------------------------------------------
EDGE=$ROOT/prod/deploy/edge
step "Общий Caddy (HTTPS): $EDGE"
if [ ! -f "$EDGE/.env" ]; then
	as_deploy "printf 'ACME_EMAIL=%s\nPROD_DOMAIN=%s\nSTAGING_DOMAIN=%s\n' '$ACME_EMAIL' '$PROD_DOMAIN' '$STAGING_DOMAIN' > $EDGE/.env"
fi
as_deploy "bash $EDGE/render-sites.sh"

as_deploy "bash $ROOT/prod/deploy/deploy.sh"
if [ -n "$STAGING_DOMAIN" ]; then
	as_deploy "bash $ROOT/staging/deploy/deploy.sh"
fi

step "Ночной бэкап БД прода (03:15, /srv/tuc/backups, 14 дней)"
echo "15 3 * * * $DEPLOY_USER bash $ROOT/prod/deploy/backup.sh >> $ROOT/backups/backup.log 2>&1" > /etc/cron.d/tuc-backup
chmod 644 /etc/cron.d/tuc-backup

# --- итог --------------------------------------------------------------------------------------
step "Готово"
cat <<EOF
Сайт:      https://$PROD_DOMAIN   (админка https://$PROD_DOMAIN/admin)
${STAGING_DOMAIN:+Тестовый:  https://$STAGING_DOMAIN   (ветка dev, обновляется после каждого ночного пуша)}

Осталось в GitHub → репозиторий → Settings → Secrets and variables → Actions → New repository secret:
  DEPLOY_SSH_HOST = $PROD_DOMAIN   (или IP сервера)
  DEPLOY_SSH_KEY  = содержимое ниже целиком, включая строки BEGIN/END
--------------------------------------------------------------------------------
$(cat "$ACTIONS_KEY")
--------------------------------------------------------------------------------
Ключ сохранён в $ACTIONS_KEY (его можно удалить после того, как вставите в GitHub).
Дальше: docs/DEPLOY.md, раздел «После bootstrap».
EOF
