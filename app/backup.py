"""Резервные копии базы.

    python -m app.backup [N]            копия в data/backups (хранятся последние N, по умолчанию 14);
                                        при BACKUP_TELEGRAM=1 ещё и отправка мастеру в Telegram
    python -m app.backup --verify [F]   проверить копию F (по умолчанию самую свежую): целостность и состав
    python -m app.backup --restore F    восстановить базу из копии F (портал должен быть остановлен)

Код возврата: 0 всё хорошо; 1 копия не сделана или не прошла проверку; 2 копия сделана,
но отправить её в Telegram не удалось (для cron: письмо об ошибке придёт, а локальная копия есть).
"""
import argparse
import gzip
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from .config import BACKUP_TELEGRAM, BOT_TOKEN, DATA_DIR
from .db import DB_PATH

TELEGRAM_LIMIT = 49 * 1024 * 1024  # Bot API принимает файлы до 50 МБ; оставляем запас
KEEP = 14


class BackupError(Exception):
    pass


def folder() -> Path:
    path = DATA_DIR / "backups"
    path.mkdir(exist_ok=True)
    return path


def _counts(conn) -> dict:
    """Что лежит в базе: по этим числам видно, что копия не пустая."""
    def one(sql):
        return conn.execute(sql).fetchone()[0]
    row = conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()
    return {
        "entries": one("SELECT COUNT(*) FROM entries"),
        "messages": one("SELECT COUNT(*) FROM messages"),
        "dossier": one("SELECT COUNT(*) FROM items WHERE kind='dossier'"),
        "places": one("SELECT COUNT(*) FROM items WHERE kind='places'"),
        "handouts": one("SELECT COUNT(*) FROM handout_files"),
        "portraits": one("SELECT COUNT(DISTINCT card_id) FROM portraits"),
        "version": int(row[0] or 0) if row else 0,
    }


def verify(path) -> dict:
    """Проверяет файл копии: открывается, целостность в порядке, таблицы на месте. Возвращает состав."""
    path = Path(path)
    if not path.is_file():
        raise BackupError(f"Файл не найден: {path}")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise BackupError(f"{path.name}: база повреждена ({result})")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = {"meta", "items", "entries", "messages", "portraits", "handout_files"} - tables
            if missing:
                raise BackupError(f"{path.name}: это не копия портала, нет таблиц: {', '.join(sorted(missing))}")
            return _counts(conn)
        finally:
            conn.close()
    except sqlite3.DatabaseError as ex:
        raise BackupError(f"{path.name}: не открывается как база ({ex})") from None


def backup(keep=KEEP, source=None, target_dir=None) -> Path:
    """Копия базы средствами SQLite (безопасна при работающем портале). Проверяется сразу после создания."""
    source = Path(source or DB_PATH)
    target_dir = Path(target_dir) if target_dir else folder()
    target_dir.mkdir(exist_ok=True)
    target = target_dir / f"portal-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.db"
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    try:
        verify(target)
    except BackupError:
        target.unlink(missing_ok=True)
        raise
    for old in sorted(target_dir.glob("portal-*.db"))[:-keep]:
        old.unlink()
    return target


def latest(target_dir=None) -> Path:
    copies = sorted((Path(target_dir) if target_dir else folder()).glob("portal-*.db"))
    if not copies:
        raise BackupError("Копий пока нет. Сначала сделайте: python -m app.backup")
    return copies[-1]


def _save_current(target: Path):
    """Сохраняет текущую базу рядом с копиями перед заменой. Повреждённую базу (а восстанавливают чаще всего именно её)
    SQLite скопировать не может: тогда файл копируется как есть вместе с журналом."""
    if not target.exists():
        return None
    safety = folder() / f"before-restore-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.db"
    try:
        src, dst = sqlite3.connect(target), sqlite3.connect(safety)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
            src.close()
    except sqlite3.DatabaseError:
        safety.unlink(missing_ok=True)
        shutil.copy2(target, safety)
        wal = Path(str(target) + "-wal")
        if wal.exists():
            shutil.copy2(wal, Path(str(safety) + "-wal"))
    return safety


def restore(path, target=None) -> Path:
    """Заменяет базу копией. Перед этим текущая база сохраняется как before-restore-*.db рядом с копиями.
    Портал на это время должен быть остановлен: иначе он продолжит писать в старый файл."""
    path = Path(path)
    verify(path)
    target = Path(target or DB_PATH)
    safety = _save_current(target)
    tmp = target.with_name(target.name + ".restoring")
    src, dst = sqlite3.connect(f"file:{path}?mode=ro", uri=True), sqlite3.connect(tmp)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    for suffix in ("-wal", "-shm"):
        Path(str(target) + suffix).unlink(missing_ok=True)
    os.replace(tmp, target)
    verify(target)
    return safety


def send_to_telegram(path) -> int:
    """Отправляет сжатую копию в личку мастеру. Возвращает, скольким адресатам ушло."""
    from . import notify
    from .config import people

    if not BOT_TOKEN:
        raise BackupError("BACKUP_TELEGRAM=1, но не задан BOT_TOKEN.")
    path = Path(path)
    packed = gzip.compress(path.read_bytes(), compresslevel=9, mtime=0)
    if len(packed) > TELEGRAM_LIMIT:
        raise BackupError(f"Сжатая копия весит {len(packed) / 1048576:.1f} МБ: больше лимита Telegram (50 МБ). "
                          "Используйте scp или rclone (см. ЗАПУСК.md, раздел 13).")
    chats = sorted(notify.gm_chat_ids(people()))
    if not chats:
        raise BackupError("Не знаю, кому отправить: у мастера нет Telegram ID в players.toml и он ещё не входил в портал.")
    caption = f"Резервная копия портала {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    sent, errors = 0, []
    for chat in chats:
        try:
            notify.send_document(chat, path.name + ".gz", packed, caption)
            sent += 1
        except Exception as ex:  # один адресат недоступен: остальным всё равно отправляем
            errors.append(f"{chat}: {ex}")
    if not sent:
        raise BackupError("Telegram не принял файл: " + "; ".join(errors)
                          + ". Мастеру нужно один раз открыть бота и нажать «Запустить».")
    return sent


def _summary(counts) -> str:
    return (f"записей {counts['entries']}, сообщений {counts['messages']}, карточек досье {counts['dossier']}, "
            f"мест {counts['places']}, раздаток {counts['handouts']}, картинок {counts['portraits']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.backup", description=__doc__.split("\n\n")[0])
    parser.add_argument("keep", nargs="?", type=int, default=KEEP, help="сколько копий хранить (по умолчанию 14)")
    parser.add_argument("--verify", nargs="?", const="latest", metavar="ФАЙЛ", help="проверить копию")
    parser.add_argument("--restore", metavar="ФАЙЛ", help="восстановить базу из копии (портал должен быть остановлен)")
    parser.add_argument("--yes", action="store_true", help="не спрашивать подтверждение при восстановлении")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            path = latest() if args.verify == "latest" else Path(args.verify)
            print(f"{path.name}: всё в порядке. В копии {_summary(verify(path))}.")
            return 0
        if args.restore:
            path = Path(args.restore)
            counts = verify(path)
            print(f"Копия {path.name}: {_summary(counts)}.")
            print(f"Будет заменена база {DB_PATH}. Портал должен быть остановлен.")
            if not args.yes and input("Продолжить? Напишите «да»: ").strip().lower() not in ("да", "yes", "y"):
                print("Отменено.")
                return 1
            safety = restore(path)
            print("База восстановлена." + (f" Прежняя сохранена как {safety.name}." if safety else ""))
            return 0
        target = backup(args.keep)
        print(target)
        if BACKUP_TELEGRAM:
            try:
                n = send_to_telegram(target)
                print(f"Копия отправлена в Telegram ({n} чат.).")
            except BackupError as ex:
                print(f"Внимание: {ex}", file=sys.stderr)
                return 2
        return 0
    except BackupError as ex:
        print(f"Ошибка: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
