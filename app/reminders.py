"""Напоминания о неотвеченных приглашениях.

Когда игрока приглашают в запись (или меняют её даты и просят подтвердить), здесь запоминается время приглашения.
Если через REMIND_DAYS дней ответа нет, ему уходит напоминание, потом ещё одно (всего не больше REMIND_MAX). Напоминания идут через
очередь уведомлений, поэтому тихие часы и сводка получателя действуют и на них; отключить их можно в «Уведомлениях».
Напоминание не отправляется, если запись закрыта, прошла по игровому времени, удалена или человек уже ответил.
"""
import time

from . import db, notify
from .config import REMIND_DAYS, REMIND_MAX

DAY = 86400


def asked(entry_id, chars, now=None):
    """Запомнить: этих персонажей только что пригласили (или спросили заново). Счётчик напоминаний начинается с нуля."""
    now = time.time() if now is None else now
    with db.lock:
        for c in chars:
            db.conn().execute(
                "INSERT INTO invite_clock(entry_id,char,asked,reminded,last) VALUES(?,?,?,0,?) "
                "ON CONFLICT(entry_id,char) DO UPDATE SET asked=excluded.asked,reminded=0,last=excluded.last",
                (entry_id, c, now, now))


def clocks() -> dict:
    with db.lock:
        rows = db.conn().execute("SELECT * FROM invite_clock").fetchall()
    return {(r["entry_id"], r["char"]): dict(r) for r in rows}


def purge_orphans():
    """Убрать записи о приглашениях удалённых записей (после восстановления из корзины отсчёт начнётся заново)."""
    with db.lock:
        db.conn().execute("DELETE FROM invite_clock WHERE entry_id NOT IN (SELECT id FROM entries)")


def due(now=None) -> list:
    """Что пора напомнить: [(запись, [персонажи])]. Ничего не меняет."""
    from . import logic  # поздний импорт: logic сам использует этот модуль
    now = time.time() if now is None else now
    if REMIND_DAYS <= 0 or REMIND_MAX <= 0:
        return []
    today, _ = logic.now()
    clock = clocks()
    result = []
    for e in db.entries():
        if e.get("type") == "grow" or not logic.is_active(e, today):
            continue
        chars = []
        for c, answer in e.get("answers", {}).items():
            if answer != "ждёт" or c not in e.get("who", []):
                continue
            row = clock.get((e["id"], c))
            last = row["last"] if row else e.get("created", now)
            reminded = row["reminded"] if row else 0
            if reminded < REMIND_MAX and now - last >= REMIND_DAYS * DAY:
                chars.append(c)
        if chars:
            result.append((e, chars))
    return result


def run(now=None) -> int:
    """Поставить в очередь все созревшие напоминания. Возвращает, сколько приглашений напомнено."""
    from . import logic
    now = time.time() if now is None else now
    todo = due(now)
    count = 0
    for e, chars in todo:
        names = logic.char_map()
        author = names.get(e["author"], {}).get("name", "Мастер")
        text = (f"Напоминание: вы ещё не ответили на приглашение в запись «{e['title']}», {logic.ffull(e['from'])}. "
                f"Приглашает {author}. Ответить можно на портале.")
        with db.lock:
            for c in chars:
                row = db.conn().execute("SELECT reminded FROM invite_clock WHERE entry_id=? AND char=?", (e["id"], c)).fetchone()
                db.conn().execute(
                    "INSERT INTO invite_clock(entry_id,char,asked,reminded,last) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(entry_id,char) DO UPDATE SET reminded=excluded.reminded,last=excluded.last",
                    (e["id"], c, e.get("created", now), (row["reminded"] if row else 0) + 1, now))
        notify.to_characters(chars, text, "now", kind="remind", now=now)
        count += len(chars)
    return count
