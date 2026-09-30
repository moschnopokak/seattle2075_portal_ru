"""Уведомления через Telegram Bot API. Отправка идёт в фоне: сбой Telegram не ломает сайт.

Личные сообщения доходят только тем, кто хотя бы раз нажал «Запустить» (/start) у бота.
"""
import json
import logging
import threading
import urllib.error
import urllib.request

from . import db
from .config import BOT_TOKEN, NOTIFY_DM, SITE_URL, TG_CHAT_ID, people

log = logging.getLogger("portal.notify")
_pin_lock = threading.Lock()


def _call(method, payload):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def _background(fn, *args):
    def run():
        try:
            fn(*args)
        except urllib.error.HTTPError as ex:
            log.warning("Telegram %s: %s", ex.code, ex.read().decode(errors="replace"))
        except Exception as ex:
            log.warning("Telegram: %s", ex)
    threading.Thread(target=run, daemon=True).start()


SECTIONS = {"now", "cal", "chron", "dossier", "handouts", "map", "gm"}


def _keyboard():
    """Кнопка в закрепе чата стола. В группах Telegram разрешает только обычную ссылку."""
    if SITE_URL.startswith("https://"):
        return {"inline_keyboard": [[{"text": "Открыть портал", "url": SITE_URL}]]}
    return None


def _dm_keyboard(section=None):
    """Кнопка в личном сообщении: открывает портал внутри Telegram (сразу с входом) на нужном разделе."""
    if not SITE_URL.startswith("https://"):
        return None
    url = SITE_URL + "/" + (f"?open={section}" if section in SECTIONS else "")
    return {"inline_keyboard": [[{"text": "Открыть портал", "web_app": {"url": url}}]]}


def _ids(obj):
    return set(obj["ids"]) | db.login_ids(obj["usernames"])


def _send(chat_id, text, section=None):
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    kb = _dm_keyboard(section)
    if kb:
        payload["reply_markup"] = kb
    try:
        _call("sendMessage", payload)
    except urllib.error.HTTPError as ex:
        body = ex.read().decode(errors="replace")
        if kb and "BUTTON" in body.upper():
            # старый клиент или запрет кнопок Mini App: отправить с обычной ссылкой
            payload["reply_markup"] = _keyboard()
            _call("sendMessage", payload)
        else:
            raise urllib.error.HTTPError(ex.url, ex.code, body, ex.headers, None)


def to_characters(char_ids, text, section=None):
    """Написать игрокам, за которыми закреплены эти персонажи. section: какой раздел портала открыть кнопкой."""
    if not (BOT_TOKEN and NOTIFY_DM):
        return
    wanted = set(char_ids)
    for player in people()["players"]:
        if wanted & set(player["chars"]):
            for uid in _ids(player):
                _background(_send, uid, text, section)


def to_gm(text, section=None):
    if not (BOT_TOKEN and NOTIFY_DM):
        return
    for uid in _ids(people()["gm"]):
        _background(_send, uid, text, section)


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
