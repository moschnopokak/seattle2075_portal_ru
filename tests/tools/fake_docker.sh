#!/usr/bin/env bash
# Заглушка docker для тестов deploy/update.sh и deploy/rollback.sh (настоящего docker в тестах нет).
# Делает ровно то, что от docker нужно скриптам: «запускает» preflight и «портал» на настоящем коде и настоящей базе, но без контейнеров.
#
# Настройка через переменные окружения:
#   STUB_DIR      папка состояния и журнала вызовов (calls.log)
#   STUB_CODE     папка НОВОЙ версии: оттуда «контейнер» репетиции запускает python -m app.preflight
#   STUB_PYTHON   какой python использовать
# Поведение переключается файлами в STUB_DIR: fail_health (новая версия никогда не станет здоровой), fail_up (docker compose up
# падает на новой версии), break_data (после запуска новой версии из базы пропадают сообщения), fail_old_up (падает и старая).
set -u
echo "$*" >> "$STUB_DIR/calls.log"
cmd=${1:-}
[ $# -gt 0 ] && shift

is_new_code() { [ -f "$PWD/app/preflight.py" ]; }
install_dir() { cat "$STUB_DIR/install-dir"; }

case "$cmd" in
  build) echo "sha256:stub"; exit 0 ;;
  tag) exit 0 ;;
  inspect)
    state=$(cat "$STUB_DIR/state" 2>/dev/null || echo stopped)
    fmt=$2
    case "$fmt" in
      *Health*)
        if [ "$state" != running ]; then echo none
        elif [ -f "$STUB_DIR/fail_health" ] && [ -f "$(install_dir)/app/preflight.py" ]; then echo unhealthy
        else echo healthy; fi ;;
      *Running*) [ "$state" = running ] && echo true || echo false ;;
    esac
    exit 0 ;;
  run)
    maps=()
    while [ $# -gt 0 ]; do
      case "$1" in
        --rm) shift ;;
        --user|--network) shift 2 ;;
        -v)
          spec=$2; host=${spec%%:*}; rest=${spec#*:}; cont=${rest%%:*}
          maps+=("$cont=$host"); shift 2 ;;
        *) break ;;
      esac
    done
    shift                                    # имя образа
    args=(); config=""
    for m in ${maps[@]+"${maps[@]}"}; do
      [ "${m%%=*}" = /app/config ] && config=${m#*=}
    done
    for a in "$@"; do
      for m in ${maps[@]+"${maps[@]}"}; do
        cont=${m%%=*}; host=${m#*=}
        case "$a" in "$cont"|"$cont"/*) a="$host${a#"$cont"}" ;; esac
      done
      args+=("$a")
    done
    cd "$STUB_CODE" || exit 1
    exec env ${config:+CONFIG_DIR="$config"} PYTHONPATH="$STUB_CODE" PYTHONDONTWRITEBYTECODE=1 "$STUB_PYTHON" "${args[@]:1}" ;;
  compose)
    sub=${1:-}
    [ $# -gt 0 ] && shift
    case "$sub" in
      stop) echo stopped > "$STUB_DIR/state"; exit 0 ;;
      start) echo running > "$STUB_DIR/state"; exit 0 ;;
      images) echo "sha256:oldimage"; exit 0 ;;
      ps) echo "cid-app"; exit 0 ;;
      logs) echo "(журнал заглушки)"; exit 0 ;;
      up)
        if [ -f "$STUB_DIR/fail_old_up" ] || { is_new_code && [ -f "$STUB_DIR/fail_up" ]; }; then
          echo "stub: compose up failed" >&2
          exit 1
        fi
        echo running > "$STUB_DIR/state"
        if is_new_code; then
          echo new > "$STUB_DIR/running_code"
          # «Контейнер» стартует: настоящий код портала делает настоящие миграции на настоящей папке data.
          env DATA_DIR="$PWD/data" CONFIG_DIR="$PWD/config" PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 "$STUB_PYTHON" -c \
            "from app import startup; startup.prepare_data()" || exit 1
          if [ -f "$STUB_DIR/break_data" ]; then
            "$STUB_PYTHON" -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('DELETE FROM messages'); c.commit()" "$PWD/data/portal.db"
          fi
        else
          echo old > "$STUB_DIR/running_code"
        fi
        exit 0 ;;
    esac
    exit 0 ;;
esac
exit 0
