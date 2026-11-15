#!/usr/bin/env bash
# Сторож стендов (B54): проверяет /health прода и staging и ведёт issue «Прод не отвечает».
#
# Запускает .github/workflows/uptime.yml каждые 30 минут. Можно прогнать руками
# (нужен `gh auth login`):
#   bash deploy/uptime.sh                 # по-настоящему: issue и комментарии в GitHub
#   DRY_RUN=1 bash deploy/uptime.sh       # только напечатать, что бы сделал
#
# Правила:
#   - прод не ответил 200 два запуска подряд → issue «Прод не отвечает с <дата>» с меткой
#     outage (если открытое уже есть — комментарий в него, второе не создаём);
#   - прод лежит дальше — молчим, раз в сутки (48 запусков) напоминание комментарием;
#   - прод ответил → закрыть открытое issue комментарием «Прод ответил <дата>»;
#   - staging отдельного issue не получает: «не отвечает» (2 раза подряд) и «ответил» —
#     комментарием в открытое issue, а если его нет — в последнее issue с меткой outage.
#
# Память между запусками — маленький файл STATE_FILE (в Actions его переносит actions/cache):
#   prod_fails=<сколько раз подряд прод не ответил>
#   prod_since=<когда не ответил впервые>
#   staging_fails=<то же для staging>
set -uo pipefail

REPO="${REPO:-urnero/tuc-platform}"
PROD_URL="${PROD_URL:-https://broprint3d.ru/health}"
STAGING_URL="${STAGING_URL:-https://staging.broprint3d.ru/health}"
STATE_FILE="${STATE_FILE:-.uptime-state}"
LABEL="outage"
FAILS_TO_ALERT=2      # сколько запусков подряд «не ответил», чтобы поднять тревогу
REMIND_EVERY=48       # напоминание в issue раз в 48 запусков (сутки при запуске раз в 30 минут)

now() { TZ=Europe/Moscow date '+%Y-%m-%d %H:%M МСК'; }

# Код ответа /health: 200 — живой; 000 — нет соединения / таймаут.
http_code() {
  curl -s -o /dev/null -w '%{http_code}' -m 15 "$1" || true
}

# Вызов gh; при DRY_RUN=1 только печатаем команду.
run_gh() {
  if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "DRY_RUN: gh $*"
  else
    gh "$@"
  fi
}

# Значение из файла состояния (state_get prod_fails 0).
state_get() {
  local value=""
  if [ -f "$STATE_FILE" ]; then
    value="$(grep -m1 "^$1=" "$STATE_FILE" | cut -d= -f2-)"
  fi
  echo "${value:-$2}"
}

# Номер issue с меткой outage: open_issue — открытого, last_issue — последнего любого.
open_issue() {
  gh api "repos/$REPO/issues?labels=$LABEL&state=open&per_page=1" --jq '.[0].number // empty'
}
last_issue() {
  gh api "repos/$REPO/issues?labels=$LABEL&state=all&per_page=1" --jq '.[0].number // empty'
}

prod_fails="$(state_get prod_fails 0)"
prod_since="$(state_get prod_since "")"
staging_fails="$(state_get staging_fails 0)"

prod_code="$(http_code "$PROD_URL")"
staging_code="$(http_code "$STAGING_URL")"
echo "$(now): прод $PROD_URL → $prod_code; staging $STAGING_URL → $staging_code"

issue="$(open_issue)"

# --- прод ---
if [ "$prod_code" = "200" ]; then
  if [ -n "$issue" ]; then
    run_gh issue close "$issue" -R "$REPO" --comment "Прод ответил $(now) (код 200). Staging: $staging_code."
    issue=""
  fi
  prod_fails=0
  prod_since=""
else
  prod_fails=$((prod_fails + 1))
  [ -n "$prod_since" ] || prod_since="$(now)"
  if [ "$prod_fails" -eq "$FAILS_TO_ALERT" ]; then
    body="Прод $PROD_URL не отвечает: код $prod_code, $FAILS_TO_ALERT проверки подряд (первая — $prod_since). Staging: $staging_code.

Что проверить — docs/DEPLOY.md, раздел «Если что-то не так». Issue закроется само, когда прод снова ответит."
    if [ -n "$issue" ]; then
      run_gh issue comment "$issue" -R "$REPO" --body "$body"
    else
      # метка может ещё не существовать — создаём (--force: если есть, просто обновит цвет)
      run_gh label create "$LABEL" -R "$REPO" --color B60205 --description "Стенд не отвечает (сторож B54)" --force >/dev/null
      run_gh issue create -R "$REPO" --title "Прод не отвечает с $prod_since" --label "$LABEL" --body "$body"
      issue="$(open_issue)"
    fi
  elif [ "$prod_fails" -gt "$FAILS_TO_ALERT" ] && [ $(((prod_fails - FAILS_TO_ALERT) % REMIND_EVERY)) -eq 0 ] && [ -n "$issue" ]; then
    run_gh issue comment "$issue" -R "$REPO" --body "Прод всё ещё не отвечает ($(now), код $prod_code; лежит с $prod_since)."
  fi
fi

# --- staging: только комментарии ---
staging_note=""
if [ "$staging_code" = "200" ]; then
  if [ "$staging_fails" -ge "$FAILS_TO_ALERT" ]; then
    staging_note="Staging ответил $(now) (код 200)."
  fi
  staging_fails=0
else
  staging_fails=$((staging_fails + 1))
  if [ "$staging_fails" -eq "$FAILS_TO_ALERT" ]; then
    staging_note="Staging $STAGING_URL не отвечает ($(now), код $staging_code, $FAILS_TO_ALERT проверки подряд)."
  fi
fi
if [ -n "$staging_note" ]; then
  target="${issue:-$(last_issue)}"
  if [ -n "$target" ]; then
    run_gh issue comment "$target" -R "$REPO" --body "$staging_note"
  else
    echo "::warning::$staging_note (issue с меткой $LABEL нет — комментировать некуда)"
  fi
fi

printf 'prod_fails=%s\nprod_since=%s\nstaging_fails=%s\n' "$prod_fails" "$prod_since" "$staging_fails" > "$STATE_FILE"
echo "Состояние: prod_fails=$prod_fails staging_fails=$staging_fails"
