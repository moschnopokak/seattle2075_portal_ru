"""Уведомления через Telegram Bot API. Отправка идёт в фоне: сбой Telegram не ломает сайт.

Личные сообщения доходят только тем, кто хотя бы раз нажал «Запустить» (/start) у бота.
"""
import json
import logging
import re
import secrets
import threading
import urllib.error
import urllib.request

from . import db, outbox
from .config import BOT_TOKEN, NOTIFY_DM, SITE_URL, TG_CHAT_ID, TG_WEBHOOK, people

log = logging.getLogger("portal.notify")
LINK_RE = re.compile(r"\[\[([^\[\]\n|]{1,60})(?:\|([^\[\]\n]{1,60}))?\]\]")      # [[Имя]] и [[Имя|подпись]], как в static/js/links.js


def strip_links(text):
    """В сообщении бота ссылки на карточки досье становятся просто именем."""
    return LINK_RE.sub(lambda m: (m.group(2) or "").strip() or m.group(1).strip(), text)


_pin_lock = threading.Lock()


class TelegramError(RuntimeError):
    """Ответ Telegram с ошибкой: код (403 бот заблокирован, 429 слишком часто и т. д.) и тело ответа."""

    def __init__(self, code, body, retry_after=None):
        super().__init__(f"Telegram {code}: {body}")
        self.code, self.body, self.retry_after = code, body, retry_after


def _call(method, payload):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def send_document(chat_id, filename, data, caption=""):
    """Отправляет файл (до 50 МБ) в чат. Вызов синхронный: нужен для резервных копий из командной строки."""
    boundary = "----portal" + secrets.token_hex(12)
    parts = []
    for name, value in (("chat_id", str(chat_id)), ("caption", caption)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{filename}"\r\n'
                 "Content-Type: application/octet-stream\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument", data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as ex:
        raise RuntimeError(f"Telegram {ex.code}: {ex.read().decode(errors='replace')}") from None


def gm_chat_ids(people_data):
    """Telegram ID мастера: из players.toml и те, кто входил в портал под его именем пользователя."""
    return _ids(people_data["gm"])


def _background(fn, *args):
    def run():
        try:
            fn(*args)
        except urllib.error.HTTPError as ex:
            log.warning("Telegram %s: %s", ex.code, ex.read().decode(errors="replace"))
        except Exception as ex:
            log.warning("Telegram: %s", ex)
    threading.Thread(target=run, daemon=True).start()


SECTIONS = {"now", "cal", "chron", "dossier", "handouts", "map", "maps", "gm"}


def _keyboard():
    """Кнопка в закрепе чата стола. В группах Telegram разрешает только обычную ссылку."""
    if SITE_URL.startswith("https://"):
        return {"inline_keyboard": [[{"text": "Открыть портал", "url": SITE_URL}]]}
    return None


def _dm_keyboard(section=None, buttons=None):
    """Кнопки под личным сообщением: сначала переданные (callback), последней «Открыть портал» (внутри Telegram, сразу с входом)."""
    rows = [list(r) for r in (buttons or [])]
    if SITE_URL.startswith("https://"):
        url = SITE_URL + "/" + (f"?open={section}" if section in SECTIONS else "")
        rows.append([{"text": "Открыть портал", "web_app": {"url": url}}])
    return {"inline_keyboard": rows} if rows else None


def _ids(obj):
    return set(obj["ids"]) | db.login_ids(obj["usernames"])


def _send(chat_id, text, section=None, buttons=None):
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    kb = _dm_keyboard(section, buttons)
    if kb:
        payload["reply_markup"] = kb
    try:
        _call("sendMessage", payload)
    except urllib.error.HTTPError as ex:
        body = ex.read().decode(errors="replace")
        if kb and "BUTTON" in body.upper():
            # старый клиент или запрет кнопок Mini App: отправить без кнопки входа
            if buttons:
                payload["reply_markup"] = {"inline_keyboard": [list(r) for r in buttons]}
            else:
                payload.pop("reply_markup", None)
            _call("sendMessage", payload)
            return
        retry = None
        try:
            retry = json.loads(body).get("parameters", {}).get("retry_after")
        except (ValueError, AttributeError):
            pass
        # тело ответа Telegram объясняет причину (например, «бот не может писать первым»): оно должно попасть в журнал
        raise TelegramError(ex.code, body, retry) from None


def deliver(tg_id, text, section=None, buttons=None):
    """Отправка из очереди (вызывается планировщиком из своего потока, ошибки идут наверх для повтора)."""
    _send(tg_id, text, section, buttons)


def _recipients(char_ids=None, gm=False):
    """Telegram ID людей: игроки, за которыми закреплены эти персонажи, и (по флагу) мастер."""
    data = people()
    ids = set()
    if char_ids:
        wanted = set(char_ids)
        for player in data["players"]:
            if wanted & set(player["chars"]):
                ids |= _ids(player)
    if gm:
        ids |= _ids(data["gm"])
    return ids


def _enabled():
    return bool(BOT_TOKEN and NOTIFY_DM)


def to_characters(char_ids, text, section=None, kind="event", buttons=None, key=None, meta=None, exclude=(), now=None):
    """Написать игрокам, за которыми закреплены эти персонажи. Сообщение встаёт в очередь (см. outbox):
    уйдёт с учётом тихих часов и сводки получателя. section: какой раздел портала открыть кнопкой. buttons: кнопки-ответы."""
    if not _enabled():
        return
    for uid in sorted(_recipients(char_ids) - set(exclude)):
        outbox.enqueue(uid, kind, text, section, buttons, key, meta, now=now)


def to_user(tg_id, text, section=None, kind="event"):
    """Написать одному человеку по его Telegram ID (с учётом тихих часов и сводки)."""
    if not _enabled():
        return
    outbox.enqueue(tg_id, kind, text, section)


# ---------- кнопки-ответы под сообщением ----------
# callback_data: «e:<действие>:<номер записи>[:<персонаж>]», у Telegram предел 64 байта. Разбор и выполнение: telegram_bot.py

def webhook_on():
    """Кнопки работают, только если Telegram присылает нажатия на портал: нужны токен, https-адрес и TG_WEBHOOK=1."""
    return bool(BOT_TOKEN and TG_WEBHOOK and SITE_URL.startswith("https://"))


def _cb(*parts):
    data = ":".join(parts)
    return data if len(data.encode()) <= 64 else None


def _label(prefix, title):
    title = " ".join(str(title).split())
    return f"{prefix} {title[:24] + '…' if len(title) > 25 else title}"


def invite_buttons(entry, char):
    """«Принять» и «Отклонить» под приглашением в запись. None, если кнопки выключены."""
    if not webhook_on():
        return None
    yes, no = _cb("e", "y", entry["id"], char), _cb("e", "n", entry["id"], char)
    if not (yes and no):
        return None
    return [[{"text": _label("✅ Принять:", entry.get("title", "")), "callback_data": yes}],
            [{"text": _label("❌ Отклонить:", entry.get("title", "")), "callback_data": no}]]


def grow_buttons(entry):
    """«Подтвердить» и «Отклонить» мастеру под заявкой на развитие."""
    if not webhook_on():
        return None
    yes, no = _cb("e", "ok", entry["id"]), _cb("e", "no", entry["id"])
    if not (yes and no):
        return None
    return [[{"text": _label("✅ Подтвердить:", entry.get("title", "")), "callback_data": yes}],
            [{"text": _label("❌ Отклонить:", entry.get("title", "")), "callback_data": no}]]


def invite(entry, chars, text, kind="invite", now=None):
    """Приглашение или напоминание по записи: у каждого персонажа свои кнопки (ответ даётся за конкретного персонажа)."""
    names = {c["id"]: c["name"] for c in people()["characters"]}
    for c in chars:
        line = text if len(chars) == 1 else f"{text} Для персонажа: {names.get(c, c)}."
        to_characters([c], line, "now", kind=kind, buttons=invite_buttons(entry, c), now=now)


def to_gm(text, section=None, kind="event", buttons=None, exclude=()):
    if not _enabled():
        return
    for uid in sorted(_recipients(gm=True) - set(exclude)):
        outbox.enqueue(uid, kind, text, section, buttons)


def chat_message(entry, author_label, text, author_tg_id, to_gm_too=True):
    """Новое сообщение в обсуждении записи: участникам и мастеру, кроме автора. Сообщения одной записи склеиваются в одно."""
    if not _enabled():
        return
    chars = set(entry.get("who", [])) | {entry.get("author")}
    chars.discard("gm")
    ids = _recipients(chars, gm=to_gm_too) - {author_tg_id}
    text = strip_links(text)
    preview = text if len(text) <= 140 else text[:140] + "…"
    meta = {"title": entry.get("title", ""), "last": f"{author_label}: {preview}", "entry": entry.get("id")}
    for uid in sorted(ids):
        outbox.enqueue(uid, "chat", "", "now", None, f"chat:{entry.get('id')}", meta, delay=outbox.chat_delay())


def _pin(text):
    with _pin_lock:
        kb = _keyboard()
        mid = db.meta_get("pin_message_id")
        if mid:
            payload = {"chat_id": TG_CHAT_ID, "message_id": int(mid), "text": text}
            if kb:
                payload["reply_markup"] = kb
            try:
                _call("editMessageText", payload)
                return
            except urllib.error.HTTPError as ex:
                body = ex.read().decode(errors="replace")
                if "message is not modified" in body:
                    return
                log.info("Закреп не обновлён (%s), отправляю новый", body)
        payload = {"chat_id": TG_CHAT_ID, "text": text}
        if kb:
            payload["reply_markup"] = kb
        result = _call("sendMessage", payload)
        mid = result["result"]["message_id"]
        db.meta_set("pin_message_id", mid)
        _call("pinChatMessage", {"chat_id": TG_CHAT_ID, "message_id": mid, "disable_notification": True})


def pin_status(text):
    """Обновить закреплённое сообщение со статусом в чате стола."""
    if BOT_TOKEN and TG_CHAT_ID:
        _background(_pin, text)
