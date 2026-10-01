"""Очередь личных уведомлений: склейка, тихие часы, сводка, повторы при сбоях.

Каждое уведомление сначала попадает в таблицу outbox с временем отправки (send_after), которое зависит от настроек
получателя: тихие часы переносят отправку на их конец, режим сводки на заданный час. Фоновый планировщик
раз в несколько секунд забирает всё, что пора отправлять, и объединяет несколько сообщений одному человеку в одно.
Новые сообщения в обсуждении одной записи склеиваются в «N новых сообщений» и уходят одним уведомлением.
"""
import json
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import db
from .config import CHAT_NOTIFY_DELAY, DEFAULT_TZ

MAX_ATTEMPTS = 3
TEXT_LIMIT = 3800          # у Telegram предел 4096 знаков
MAX_BUTTON_ROWS = 8
TZ_RE = re.compile(r"^[A-Za-z0-9_+\-/]{1,64}$")
FIELDS = ("tz", "quiet_on", "quiet_from", "quiet_to", "digest_on", "digest_hour", "chat_notify")


# ---------- настройки пользователя ----------

def defaults() -> dict:
    return {"tz": DEFAULT_TZ, "quiet_on": 0, "quiet_from": 23, "quiet_to": 8, "digest_on": 0, "digest_hour": 9, "chat_notify": 1}


def zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return ZoneInfo("UTC")


def prefs(tg_id) -> dict:
    with db.lock:
        row = db.conn().execute("SELECT * FROM user_prefs WHERE tg_id=?", (tg_id,)).fetchone()
    base = defaults()
    if row:
        base.update({k: row[k] for k in FIELDS})
    return base


def _hour(value, label):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}: нужен час от 0 до 23.") from None
    if isinstance(value, bool) or not 0 <= number <= 23:
        raise ValueError(f"{label}: нужен час от 0 до 23.")
    return number


def save_prefs(tg_id, data) -> dict:
    """Проверяет и сохраняет настройки. ValueError с понятным текстом, если что-то не так."""
    if not isinstance(data, dict):
        raise ValueError("Некорректные настройки.")
    tz = str(data.get("tz") or DEFAULT_TZ).strip()
    if not TZ_RE.match(tz):
        raise ValueError("Неизвестный часовой пояс.")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError("Неизвестный часовой пояс.") from None
    quiet_on = 1 if data.get("quiet_on") else 0
    quiet_from, quiet_to = _hour(data.get("quiet_from", 23), "Тихие часы, начало"), _hour(data.get("quiet_to", 8), "Тихие часы, конец")
    if quiet_on and quiet_from == quiet_to:
        raise ValueError("Начало и конец тихих часов не должны совпадать.")
    digest_on = 1 if data.get("digest_on") else 0
    digest_hour = _hour(data.get("digest_hour", 9), "Час сводки")
    chat_notify = 0 if data.get("chat_notify") is False or data.get("chat_notify") == 0 else 1
    with db.lock:
        db.conn().execute(
            "INSERT INTO user_prefs(tg_id,tz,quiet_on,quiet_from,quiet_to,digest_on,digest_hour,chat_notify,updated) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(tg_id) DO UPDATE SET tz=excluded.tz,quiet_on=excluded.quiet_on,quiet_from=excluded.quiet_from,quiet_to=excluded.quiet_to,"
            "digest_on=excluded.digest_on,digest_hour=excluded.digest_hour,chat_notify=excluded.chat_notify,updated=excluded.updated",
            (tg_id, tz, quiet_on, quiet_from, quiet_to, digest_on, digest_hour, chat_notify, time.time()))
    return prefs(tg_id)


def next_allowed(p, now) -> float:
    """Ближайший момент (секунды Unix, не раньше now), когда этому человеку можно писать.

    Сводка: ближайший следующий час сводки по его часовому поясу. Тихие часы: конец тихих часов, если сейчас они идут."""
    local = datetime.fromtimestamp(now, zone(p["tz"]))
    if p["digest_on"]:
        target = local.replace(hour=p["digest_hour"], minute=0, second=0, microsecond=0)
        if target <= local:
            target += timedelta(days=1)
        return target.timestamp()
    if p["quiet_on"] and p["quiet_from"] != p["quiet_to"]:
        a, b, h = p["quiet_from"], p["quiet_to"], local.hour
        inside = (a <= h < b) if a < b else (h >= a or h < b)
        if inside:
            end = local.replace(hour=b, minute=0, second=0, microsecond=0)
            if end <= local:
                end += timedelta(days=1)
            return end.timestamp()
    return now


# ---------- очередь ----------

def enqueue(tg_id, kind, text="", section=None, buttons=None, key=None, meta=None, delay=0, now=None):
    """Поставить уведомление в очередь. key склеивает однотипные: второе и следующие с тем же key только увеличивают счётчик."""
    now = time.time() if now is None else now
    p = prefs(tg_id)
    if kind == "chat" and not p["chat_notify"]:
        return None
    send_after = max(now + delay, next_allowed(p, now))
    with db.lock:
        if key:
            row = db.conn().execute("SELECT id FROM outbox WHERE tg_id=? AND key=? ORDER BY id LIMIT 1", (tg_id, key)).fetchone()
            if row:
                db.conn().execute("UPDATE outbox SET count=count+1, meta=? WHERE id=?",
                                  (json.dumps(meta, ensure_ascii=False) if meta is not None else None, row["id"]))
                return row["id"]
        cur = db.conn().execute(
            "INSERT INTO outbox(tg_id,kind,text,section,buttons,key,count,meta,created,send_after) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (tg_id, kind, text, section, json.dumps(buttons, ensure_ascii=False) if buttons else None, key, 1,
             json.dumps(meta, ensure_ascii=False) if meta is not None else None, now, send_after))
        return cur.lastrowid


def chat_delay():
    return CHAT_NOTIFY_DELAY


def pending(tg_id=None):
    with db.lock:
        if tg_id is None:
            rows = db.conn().execute("SELECT * FROM outbox ORDER BY id").fetchall()
        else:
            rows = db.conn().execute("SELECT * FROM outbox WHERE tg_id=? ORDER BY id", (tg_id,)).fetchall()
    return [dict(r) for r in rows]


def _plural(n, one, few, many):
    m10, m100 = n % 10, n % 100
    return one if m10 == 1 and m100 != 11 else few if 2 <= m10 <= 4 and not 12 <= m100 <= 14 else many


def _line(row):
    if row["kind"] == "chat":
        meta = json.loads(row["meta"]) if row["meta"] else {}
        n = row["count"]
        head = f"Обсуждение «{meta.get('title', '')}»: {n} {_plural(n, 'новое сообщение', 'новых сообщения', 'новых сообщений')}"
        return head + (f"\nПоследнее: {meta['last']}" if meta.get("last") else "")
    return row["text"]


def compose(rows):
    """Одно сообщение из нескольких готовых к отправке: (текст, раздел для кнопки, кнопки)."""
    if len(rows) == 1:
        text = _line(rows[0])
    else:
        lines, used = [], 0
        for i, row in enumerate(rows):
            line = "• " + _line(row).replace("\n", "\n  ")
            if used + len(line) > TEXT_LIMIT:
                lines.append(f"…и ещё {len(rows) - i}")
                break
            lines.append(line)
            used += len(line) + 2
        text = f"Новое на портале ({len(rows)}):\n\n" + "\n\n".join(lines)
    buttons = []
    for row in rows:
        if row["buttons"]:
            buttons += json.loads(row["buttons"])
    sections = [r["section"] for r in rows if r["section"]]
    return text[:4000], (sections[0] if len(rows) == 1 or len(set(sections)) == 1 else "now") if sections else None, buttons[:MAX_BUTTON_ROWS]


def flush(send, now=None, limit=500) -> int:
    """Отправить всё, что пора. send(tg_id, text, section, buttons) бросает исключение при сбое.
    Ошибка 400 или 403 (бот заблокирован, чат не найден) означает «писать некуда»: уведомление снимается. Остальные сбои повторяются."""
    now = time.time() if now is None else now
    with db.lock:
        rows = [dict(r) for r in db.conn().execute("SELECT * FROM outbox WHERE send_after<=? ORDER BY tg_id, id LIMIT ?", (now, limit)).fetchall()]
    groups = {}
    for row in rows:
        groups.setdefault(row["tg_id"], []).append(row)
    sent = 0
    for tg_id, items in groups.items():
        ids = [r["id"] for r in items]
        marks = ",".join("?" * len(ids))
        text, section, buttons = compose(items)
        try:
            send(tg_id, text, section, buttons)
        except Exception as ex:  # noqa: BLE001 - любой сбой отправки не должен ронять планировщик
            code = getattr(ex, "code", None)
            if code in (400, 403):
                with db.lock:
                    db.conn().execute(f"DELETE FROM outbox WHERE id IN ({marks})", ids)
                continue
            retry = getattr(ex, "retry_after", None)
            with db.lock:
                for r in items:
                    attempts = r["attempts"] + 1
                    if attempts >= MAX_ATTEMPTS:
                        db.conn().execute("DELETE FROM outbox WHERE id=?", (r["id"],))
                    else:
                        db.conn().execute("UPDATE outbox SET attempts=?, send_after=? WHERE id=?",
                                          (attempts, now + (retry if retry else 60 * attempts), r["id"]))
            continue
        with db.lock:
            db.conn().execute(f"DELETE FROM outbox WHERE id IN ({marks})", ids)
        sent += 1
    return sent


def purge_stale(days=3, now=None) -> int:
    """Уведомления, которые не удалось доставить за несколько дней, больше не нужны."""
    now = time.time() if now is None else now
    with db.tx() as c:
        return c.execute("DELETE FROM outbox WHERE created<?", (now - days * 86400,)).rowcount
