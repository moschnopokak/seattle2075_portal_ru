"""Кнопки в личных сообщениях бота: приём нажатий через webhook Telegram.

Под приглашением в запись бот показывает «Принять» и «Отклонить», мастеру под заявкой на развитие «Подтвердить» и «Отклонить».
Нажатие приходит на /api/telegram/webhook, выполняется теми же правилами, что и ответ на портале (logic.entry_action), от имени
того, кто нажал: чужого персонажа ответить нельзя. После нажатия кнопки этой записи пропадают из сообщения.

Включается TG_WEBHOOK=1 (нужен SITE_URL с https). Управление из командной строки:
    python -m app.telegram_bot set | delete | info
"""
import hashlib
import hmac
import json
import logging
import sys
import urllib.error

from fastapi import HTTPException

from . import config, logic, notify

log = logging.getLogger("portal.bot")

ACTS = {"y": ("ans", "да"), "n": ("ans", "нет"), "ok": ("approve", None), "no": ("reject", None)}


def secret() -> str:
    """Секрет, который Telegram присылает в заголовке каждого запроса. Получается из ключа портала, хранить отдельно не нужно."""
    return hmac.new(config.SECRET_KEY, b"telegram-webhook-v1", hashlib.sha256).hexdigest()


def check_secret(header) -> bool:
    return hmac.compare_digest((header or "").encode(), secret().encode())


def webhook_url() -> str:
    return notify.SITE_URL + "/api/telegram/webhook"


def register():
    return notify._call("setWebhook", {"url": webhook_url(), "secret_token": secret(), "allowed_updates": ["callback_query"],
                                       "max_connections": 10})


def unregister():
    return notify._call("deleteWebhook", {})


def info():
    return notify._call("getWebhookInfo", {})


def parse(data):
    """«e:y:<запись>:<персонаж>» → ('y', запись, персонаж). Всё непонятное даёт None."""
    parts = data.split(":") if isinstance(data, str) else []
    if len(parts) < 3 or parts[0] != "e" or parts[1] not in ACTS or not parts[2]:
        return None
    char = ":".join(parts[3:]) or None
    if parts[1] in ("y", "n") and not char:
        return None
    return parts[1], parts[2], char


def _press(cq):
    """Выполнить нажатие. Возвращает (текст для всплывающего ответа, показать окном, убрать ли кнопки)."""
    sender = cq.get("from") if isinstance(cq.get("from"), dict) else {}
    tg_id, username = sender.get("id"), sender.get("username") or ""
    parsed = parse(cq.get("data"))
    if not isinstance(tg_id, int) or isinstance(tg_id, bool) or not parsed:
        return "Эта кнопка больше не работает. Откройте портал.", True, False
    role = config.resolve(tg_id, username)
    if not role:
        return "Вашего Telegram нет в списке игроков.", True, False
    viewer = logic.Viewer(role[0], role[1], tg_id, username)
    code, entry_id, char = parsed
    act, val = ACTS[code]
    if act in ("approve", "reject") and not viewer.gm:
        return "Развитие подтверждает только мастер.", True, False
    body = {"act": act, "char": char}
    if val:
        body["v"] = val
    try:
        return logic.entry_action(viewer, entry_id, body), False, True
    except HTTPException as ex:
        detail = ex.detail
        text = detail if isinstance(detail, str) else (detail or {}).get("message", "Не получилось.")
        return text, True, ex.status_code != 403            # чужие кнопки не трогаем, остальное устарело и убирается


def _strip(cq, parsed):
    """Убрать из сообщения кнопки этой записи (и этого персонажа), остальные оставить."""
    msg = cq.get("message") if isinstance(cq.get("message"), dict) else {}
    chat = msg.get("chat") if isinstance(msg.get("chat"), dict) else {}
    markup = msg.get("reply_markup") if isinstance(msg.get("reply_markup"), dict) else {}
    rows, chat_id, message_id = markup.get("inline_keyboard"), chat.get("id"), msg.get("message_id")
    if not isinstance(rows, list) or chat_id is None or message_id is None:
        return
    _code, entry_id, char = parsed

    def same(button):
        other = parse(button.get("callback_data")) if isinstance(button, dict) else None
        return bool(other) and other[1] == entry_id and other[2] == char

    keep = [row for row in ([b for b in r if not same(b)] for r in rows if isinstance(r, list)) if row]
    notify._call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": keep}})


def handle_update(update) -> str:
    """Разобрать одно обновление Telegram. Никогда не бросает исключение: Telegram повторял бы запрос бесконечно."""
    cq = update.get("callback_query") if isinstance(update, dict) else None
    if not isinstance(cq, dict):
        return "ignored"
    try:
        text, alert, strip = _press(cq)
    except Exception:  # noqa: BLE001
        log.exception("Сбой при обработке нажатия кнопки")
        text, alert, strip = "Не получилось. Попробуйте на портале.", True, False
    try:
        notify._call("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": text[:190], "show_alert": alert})
        if strip:
            _strip(cq, parse(cq.get("data")))
    except urllib.error.HTTPError as ex:
        log.warning("Telegram %s: %s", ex.code, ex.read().decode(errors="replace")[:200])
    except Exception as ex:  # noqa: BLE001
        log.warning("Ответ на нажатие не отправлен: %s", ex)
    return "alert" if alert else "ok"


def main(argv=None):
    cmd = (argv or sys.argv[1:] or [""])[0]
    if not notify.BOT_TOKEN:
        print("BOT_TOKEN не задан.")
        return 1
    try:
        if cmd == "set":
            if not notify.SITE_URL.startswith("https://"):
                print("Нужен SITE_URL с https://")
                return 1
            print(json.dumps(register(), ensure_ascii=False))
        elif cmd == "delete":
            print(json.dumps(unregister(), ensure_ascii=False))
        elif cmd == "info":
            print(json.dumps(info(), ensure_ascii=False, indent=2))
        else:
            print("Использование: python -m app.telegram_bot set | delete | info")
            return 1
    except urllib.error.HTTPError as ex:
        print(f"Telegram {ex.code}: {ex.read().decode(errors='replace')}")
        return 1
    except OSError as ex:
        print(f"Нет связи с Telegram: {ex}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
