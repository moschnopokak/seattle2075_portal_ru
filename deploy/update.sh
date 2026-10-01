#!/usr/bin/env bash
# Обновление портала «Сиэтл 2075» с защитой базы данных.
#
# Запускается из папки НОВОЙ версии (там, где лежит этот файл в deploy/), а обновляет уже работающий портал:
#     sudo bash deploy/update.sh --rehearse-only     только репетиция, ничего не меняется
#     sudo bash deploy/update.sh                     обновление
#
# Что делает, по порядку:
#   1. Копия базы работающего портала средствами SQLite (портал не останавливается) и её проверка.
#   2. Собирает новую версию и прогоняет на этой КОПИИ настоящий запуск: миграция, целостность, «ничего не пропало»,
#      все игроки и мастер получают своё состояние. Если что-то не так, останавливается, ничего не изменено.
#   3. На время обновления останавливает портал и делает полную холодную копию папки data (база, ключ входа, картинки),
#      копию кода и настроек, метку старого образа. Копия лежит ВНЕ папки портала, по умолчанию в /opt/portal-backups/<время>/.
#   4. Заменяет код (ваши .env, config/players.toml, config/campaign.json и data не трогаются), запускает портал.
#   5. Ждёт, пока он станет здоровым, и сверяет базу с копией: ничего не должно пропасть.
#   6. Если на шагах 4–5 что-то пошло не так, сам откатывается: возвращает код и базу из копии.
# Откат вручную: sudo bash /opt/portal-backups/<время>/rollback.sh
set -Eeuo pipefail
trap '' HUP          # оборвалась связь с сервером (SSH): скрипт всё равно дойдёт до конца, а не бросит портал на полпути

INSTALL=/opt/seattle2075-portal
BACKUPS=/opt/portal-backups
ASSUME_YES=0
REHEARSE_ONLY=0
SKIP_PUBLIC=0
HEALTH_WAIT=180
DOCKER=${DOCKER:-docker}
PYTHON=${PYTHON:-python3}
CURL=${CURL:-curl}
CHOWN=${CHOWN:-chown}
PUBLIC_PAUSE=${PUBLIC_CHECK_PAUSE:-5}   # DOCKER, PYTHON, CURL, CHOWN, PUBLIC_CHECK_PAUSE и ASSUME_ROOT нужны только тестам скрипта (с заглушкой docker)
NEW=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

usage() {
  sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  echo
  echo "Параметры: --install-dir ПАПКА (по умолчанию $INSTALL), --backups-dir ПАПКА (по умолчанию $BACKUPS),"
  echo "           --yes (не спрашивать), --rehearse-only, --skip-public-check, --health-wait СЕКУНД"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --install-dir) INSTALL=$2; shift 2 ;;
    --backups-dir) BACKUPS=$2; shift 2 ;;
    --yes) ASSUME_YES=1; shift ;;
    --rehearse-only) REHEARSE_ONLY=1; shift ;;
    --skip-public-check) SKIP_PUBLIC=1; shift ;;
    --health-wait) HEALTH_WAIT=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Неизвестный параметр: $1"; usage; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
ask() {
  [ "$ASSUME_YES" = 1 ] && return 0
  read -r -p "$1 [y/N] " reply
  case "$reply" in y|Y|yes|д|Д|да) return 0 ;; *) echo "Отменено, ничего не изменено."; exit 0 ;; esac
}
dc() { (cd "$INSTALL" && "$DOCKER" compose "$@"); }
# Файлы в data должны принадлежать пользователю контейнера (uid 1000). Чиним только то, что создал root: остальное и группы не трогаем.
fix_owner() { find "$INSTALL/data" ! -user 1000 -exec "$CHOWN" 1000:1000 {} + 2>/dev/null || true; }

PHASE=safe        # safe: ничего не менялось; downtime: портал остановлен, но данные и код ещё целы; copied: полная копия готова, дальше можно откатываться
BK=""
STAMP=""

rollback_now() {
  if [ -n "$BK" ] && [ -f "$BK/rollback.sh" ]; then
    warn "Откатываюсь к состоянию до обновления…"
    bash "$BK/rollback.sh" --yes --install-dir "$INSTALL" || warn "Автоматический откат не удался. Выполните вручную: sudo bash $BK/rollback.sh"
  fi
}
on_error() {
  local code=$? line=$1
  printf '\n  \033[31m✗ Сбой на строке %s (код %s).\033[0m\n' "$line" "$code" >&2
  trap - ERR INT TERM
  case "$PHASE" in
    safe) echo "  Портал не останавливался и не менялся, ваши данные нетронуты." >&2 ;;
    downtime)
      echo "  Данные и код не менялись. Запускаю портал обратно…" >&2
      dc start app >/dev/null 2>&1 || dc up -d >/dev/null 2>&1 || echo "  Не получилось. Запустите вручную: cd $INSTALL && sudo docker compose up -d" >&2 ;;
    *) rollback_now ;;
  esac
  exit "$code"
}
trap 'on_error $LINENO' ERR INT TERM

# ---------------------------------------------------------------- 0. проверки
say "0. Проверки"
[ "${ASSUME_ROOT:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "Запускайте через sudo."
command -v "$DOCKER" >/dev/null || die "Не найден docker."
command -v "$PYTHON" >/dev/null || die "Не найден python3 (нужен для копии базы). Установите: sudo apt install -y python3"
for f in docker-compose.yml .env config/players.toml data/portal.db; do
  [ -e "$INSTALL/$f" ] || die "В $INSTALL нет $f. Это точно папка работающего портала? Другая папка: --install-dir ПАПКА"
done
[ -f "$NEW/app/preflight.py" ] || die "В $NEW нет app/preflight.py: запускайте скрипт из распакованной НОВОЙ версии."
[ "$(cd "$INSTALL" && pwd)" != "$NEW" ] || die "Скрипт запущен из самой папки портала. Распакуйте новую версию в отдельную папку (например /opt/portal-new)."
ok "Работающий портал: $INSTALL, новая версия: $NEW"
need_kb=$(( $(du -sk "$INSTALL/data" | cut -f1) * 3 + 600000 ))
free_kb=$(df -Pk "$INSTALL" | awk 'NR==2 {print $4}')
[ "$free_kb" -ge "$need_kb" ] || die "Мало места на диске: свободно $((free_kb/1024)) МБ, нужно не меньше $((need_kb/1024)) МБ (три копии базы и сборка образа)."
ok "Места хватает: свободно $((free_kb/1024)) МБ"

STAMP=$(date +%Y%m%d-%H%M%S)
BK="$BACKUPS/$STAMP"
umask 077
mkdir -p "$BK"
chmod 700 "$BACKUPS" "$BK"
cp "$NEW/deploy/rollback.sh" "$BK/rollback.sh"
printf '%s\n' "$INSTALL" > "$BK/install-dir"
ok "Копии будут лежать здесь: $BK"

# Новая версия заменяет app/ и static/ целиком. Если вы правили там что-то вручную, скажем об этом до остановки портала.
KNOWN="$INSTALL/.installed-files.sha256"                      # отпечатки, записанные прошлым обновлением
[ -f "$KNOWN" ] || KNOWN="$NEW/deploy/known-files.txt"        # иначе: отпечатки всех прежних версий портала
[ -f "$KNOWN" ] && [ -f "$NEW/deploy/filehash.py" ] || die "В $NEW/deploy нет filehash.py или known-files.txt: распакуйте новую версию заново."
edited=$("$PYTHON" "$NEW/deploy/filehash.py" "$INSTALL" --unknown "$KNOWN")
if [ -n "$edited" ]; then
  warn "В app/ или static/ есть файлы, которых нет ни в одной известной версии портала (вы правили их вручную или ставили отдельно):"
  printf '%s\n' "$edited" | head -20 | sed 's/^/      /'
  warn "Новая версия заменит их своими. Ваши варианты сохранятся в $BK/code-before.tgz."
  [ "$REHEARSE_ONLY" = 1 ] || ask "Всё равно обновлять?"
else
  ok "Код на сервере соответствует известной версии портала, ручных правок нет"
fi

# ---------------------------------------------------------------- 1. копия живой базы
say "1. Копия базы работающего портала (портал не останавливается)"
"$PYTHON" - "$INSTALL/data/portal.db" "$BK/portal-live.db" <<'PY'
import sqlite3, sys
from urllib.parse import quote
src = sqlite3.connect("file:" + quote(sys.argv[1]) + "?mode=ro", uri=True)    # только чтение: живую базу не трогаем
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.execute("PRAGMA journal_mode=DELETE")                                     # копия одним файлом, без WAL: её читает контейнер с диском «только чтение»
status = dst.execute("PRAGMA integrity_check").fetchone()[0]
rows = dst.execute("SELECT COUNT(*) FROM entries").fetchone()[0], dst.execute("SELECT COUNT(*) FROM items").fetchone()[0]
src.close(); dst.close()
if status != "ok":
    sys.exit("копия не прошла проверку целостности: " + status)
print(f"  копия проверена: целостность ok, записей календаря {rows[0]}, элементов {rows[1]}")
PY
fix_owner
ok "База скопирована: $BK/portal-live.db"

# ---------------------------------------------------------------- 2. репетиция
say "2. Репетиция: новая версия на КОПИИ вашей базы"
IMG=seattle2075-portal-rehearsal
"$DOCKER" build -q -t "$IMG" "$NEW" >/dev/null
ok "Новая версия собрана"
if ! "$DOCKER" run --rm --user 0:0 --network none -v "$BK/portal-live.db:/work/portal.db:ro" -v "$INSTALL/config:/app/config:ro" "$IMG" \
     python -m app.preflight --db /work/portal.db; then
  die "Репетиция нашла проблемы (см. выше). Портал не менялся. Пришлите вывод этой команды тому, кто сопровождает портал."
fi
if [ "$REHEARSE_ONLY" = 1 ]; then
  say "Готово: репетиция прошла, ничего не изменено."
  echo "  Для настоящего обновления запустите ту же команду без --rehearse-only."
  exit 0
fi

# ---------------------------------------------------------------- 3. остановка и холодная копия
say "3. Остановка портала и полная копия"
echo "  Портал будет недоступен несколько минут (обычно 2–3)."
ask "Обновлять сейчас?"
PHASE=downtime
dc stop app
ok "Портал остановлен"
cp -a "$INSTALL/data" "$BK/data"
"$PYTHON" - "$BK/data/portal.db" "$BK/portal-before.db" <<'PY'
import sqlite3, sys
from urllib.parse import quote
src = sqlite3.connect("file:" + quote(sys.argv[1]) + "?mode=ro", uri=True)    # копию data не меняем ни на байт
status = src.execute("PRAGMA integrity_check").fetchone()[0]
if status != "ok":
    sys.exit("холодная копия не прошла проверку: " + status)
dst = sqlite3.connect(sys.argv[2])                                            # «снимок до» для итоговой сверки: учтено всё, что было в журнале WAL
with dst:
    src.backup(dst)
dst.execute("PRAGMA journal_mode=DELETE")
src.close(); dst.close()
PY
ok "Холодная копия папки data сделана и проверена: $BK/data"
tar -C "$INSTALL" --exclude=./data -czf "$BK/code-before.tgz" .
ok "Копия кода и настроек: $BK/code-before.tgz"
old_image=$(dc images -q app 2>/dev/null | head -1 || true)
if [ -n "$old_image" ]; then
  "$DOCKER" tag "$old_image" "seattle2075-portal-before-update:$STAMP" && ok "Старый образ сохранён с меткой seattle2075-portal-before-update:$STAMP"
fi

# ---------------------------------------------------------------- 4. замена кода
say "4. Замена кода (ваши .env, список игроков, структура кампании и data не трогаются)"
PHASE=copied
rm -rf "$INSTALL/app" "$INSTALL/static"
tar -C "$NEW" --exclude=./.git --exclude=./node_modules --exclude=./tests --exclude=./.github --exclude=./data --exclude=./.env \
    --exclude=./config/players.toml --exclude=./config/campaign.json --exclude=./venv --exclude=./.venv -cf - . | tar -C "$INSTALL" -xf -
fix_owner
chmod 600 "$INSTALL/.env"
"$PYTHON" "$NEW/deploy/filehash.py" "$INSTALL" > "$INSTALL/.installed-files.sha256"      # отпечатки: в следующий раз по ним найдём ручные правки
ok "Новый код на месте"
dc up -d --build --force-recreate
ok "Портал запущен, жду, пока он станет здоровым (до $HEALTH_WAIT с)"

# ---------------------------------------------------------------- 5. проверки после запуска
cid=$(dc ps -q app | head -1)
status=none
for _ in $(seq 1 $((HEALTH_WAIT / 3))); do
  status=$("$DOCKER" inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo none)
  [ "$status" = healthy ] && break
  [ "$status" = unhealthy ] && break
  [ "$("$DOCKER" inspect -f '{{.State.Running}}' "$cid" 2>/dev/null || echo false)" = true ] || break
  sleep 3
done
if [ "$status" != healthy ]; then
  dc logs --tail 40 app || true
  false
fi
ok "Контейнер здоров"

say "5. Сверка базы: после запуска не должно пропасть ничего из того, что было"
"$PYTHON" - "$INSTALL/data/portal.db" "$BK/portal-after.db" <<'PY'
import sqlite3, sys
from urllib.parse import quote
src = sqlite3.connect("file:" + quote(sys.argv[1]) + "?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.execute("PRAGMA journal_mode=DELETE")
src.close(); dst.close()
PY
"$DOCKER" run --rm --user 0:0 --network none -v "$BK:/work:ro" "$IMG" python -m app.preflight --compare /work/portal-before.db /work/portal-after.db
ok "Сверка прошла"

if [ "$SKIP_PUBLIC" = 0 ]; then
  domain=$(grep -E '^DOMAIN=' "$INSTALL/.env" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
  if [ -n "$domain" ]; then
    reached=0
    for _ in 1 2 3 4 5 6; do
      if "$CURL" -fsS --max-time 15 "https://$domain/healthz" >"$BK/healthz.json" 2>/dev/null; then reached=1; break; fi
      sleep "$PUBLIC_PAUSE"
    done
    if [ "$reached" = 1 ]; then ok "Портал отвечает снаружи: https://$domain/healthz $(cat "$BK/healthz.json")"
    else warn "Снаружи https://$domain/healthz пока не открывается. Внутри портал здоров, возможно, Caddy ещё получает сертификат. Проверьте через минуту: sudo docker compose logs --tail 30 caddy"; fi
  fi
fi

# ---------------------------------------------------------------- итог
say "Готово: портал обновлён"
if [ -f "$INSTALL/.env.example" ]; then
  missing=$(grep -oE '^#? ?[A-Z][A-Z0-9_]+=' "$INSTALL/.env.example" | tr -d '# =' | sort -u | while read -r key; do grep -qE "^#? ?$key=" "$INSTALL/.env" || echo "$key"; done | tr '\n' ' ')
  [ -z "$missing" ] || echo "  Новые необязательные настройки, которых нет в вашем .env (смотрите .env.example): $missing"
fi
echo "  Копия до обновления: $BK (храните не меньше двух недель)."
echo "  Если что-то не так: sudo bash $BK/rollback.sh"
echo "  Не забудьте про регулярные копии базы: раздел 13 в ЗАПУСК.md."
