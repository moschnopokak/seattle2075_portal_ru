#!/usr/bin/env bash
# Откат обновления: возвращает код и базу к состоянию ДО обновления.
#
# Копия этого файла лежит в папке резервной копии, которую делает update.sh (/opt/portal-backups/<время>/rollback.sh):
#     sudo bash /opt/portal-backups/<время>/rollback.sh
#
# Важно: всё, что игроки и мастер записали в портал ПОСЛЕ обновления, при откате пропадёт (базу заменяет копия до обновления).
# Но и эти данные не уничтожаются: текущая папка data переименовывается в data.after-update-<время> рядом с порталом.
set -Eeuo pipefail

BK=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
INSTALL=""
ASSUME_YES=0
HEALTH_WAIT=180
DOCKER=${DOCKER:-docker}
CHOWN=${CHOWN:-chown}              # эта переменная и ASSUME_ROOT нужны только тестам скрипта

while [ $# -gt 0 ]; do
  case "$1" in
    --install-dir) INSTALL=$2; shift 2 ;;
    --yes) ASSUME_YES=1; shift ;;
    --health-wait) HEALTH_WAIT=$2; shift 2 ;;
    -h|--help) sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Неизвестный параметр: $1"; exit 2 ;;
  esac
done
[ -n "$INSTALL" ] || INSTALL=$(cat "$BK/install-dir" 2>/dev/null || echo /opt/seattle2075-portal)

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
die() { printf '  \033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
dc()  { (cd "$INSTALL" && "$DOCKER" compose "$@"); }

[ "${ASSUME_ROOT:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "Запускайте через sudo."
[ -f "$BK/data/portal.db" ] || die "В $BK нет data/portal.db: это не папка резервной копии update.sh."
[ -f "$BK/code-before.tgz" ] || die "В $BK нет code-before.tgz."
[ -d "$INSTALL" ] || die "Нет папки портала $INSTALL."

say "Откат портала в $INSTALL к копии $BK"
echo "  Всё, что записано в портал после обновления, пропадёт (текущая data будет сохранена рядом)."
if [ "$ASSUME_YES" != 1 ]; then
  read -r -p "Откатывать? [y/N] " reply
  case "$reply" in y|Y|yes|д|Д|да) ;; *) echo "Отменено."; exit 0 ;; esac
fi

AFTER="$INSTALL/data.after-update-$(date +%Y%m%d-%H%M%S)"
dc stop app || true
ok "Портал остановлен"
if [ -d "$INSTALL/data" ]; then
  mv "$INSTALL/data" "$AFTER"
  ok "Текущая папка data сохранена: $AFTER"
fi
cp -a "$BK/data" "$INSTALL/data"
"$CHOWN" -R 1000:1000 "$INSTALL/data"
ok "База и вся папка data возвращены из копии"

rm -rf "$INSTALL/app" "$INSTALL/static"
tar -xzf "$BK/code-before.tgz" -C "$INSTALL" --exclude=./.env --exclude=./config/players.toml --exclude=./config/campaign.json
ok "Старый код возвращён"

dc up -d --build --force-recreate
cid=$(dc ps -q app | head -1)
status=none
for _ in $(seq 1 $((HEALTH_WAIT / 3))); do
  status=$("$DOCKER" inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo none)
  [ "$status" = healthy ] && break
  [ "$("$DOCKER" inspect -f '{{.State.Running}}' "$cid" 2>/dev/null || echo false)" = true ] || break
  sleep 3
done
if [ "$status" = healthy ]; then
  ok "Старая версия работает"
else
  dc logs --tail 40 app || true
  die "Старая версия не стала здоровой. Данные целы (копия: $BK/data). Не паникуйте и пришлите вывод выше тому, кто сопровождает портал."
fi
say "Откат выполнен"
echo "  Данные, записанные после обновления: $AFTER (удалить, когда они не понадобятся)."
