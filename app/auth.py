"""Вход через Telegram: виджет на сайте и Mini App внутри Telegram. Сессии подписываются HMAC."""
import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from .config import BOT_TOKEN, SECRET_KEY, SESSION_DAYS

MAX_AUTH_AGE = 86400  # данные входа старше суток не принимаются


class AuthError(Exception):
    pass


def _fresh(fields: dict) -> bool:
    """auth_date не старше суток. Нечисловое значение считается устаревшим, а не ошибкой сервера."""
    try:
        return time.time() - int(fields.get("auth_date", "0")) <= MAX_AUTH_AGE
    except (TypeError, ValueError):
        return False


def _data_check_string(fields: dict) -> str:
    return "\n".join(f"{k}={fields[k]}" for k in sorted(fields))


def check_widget(data: dict) -> dict:
    """Данные от Telegram Login Widget: https://core.telegram.org/widgets/login#checking-authorization"""
    if not BOT_TOKEN:
        raise AuthError("На сервере не задан BOT_TOKEN.")
    received = str(data.get("hash", ""))
    fields = {k: str(v) for k, v in data.items() if k != "hash" and v is not None}
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    calc = hmac.new(secret, _data_check_string(fields).encode(), hashlib.sha256).hexdigest()
    if not received or not hmac.compare_digest(calc.encode(), received.encode()):
        raise AuthError("Подпись Telegram не сошлась.")
    if not _fresh(fields):
        raise AuthError("Данные входа устарели, войдите ещё раз.")
    try:
        tg_id = int(fields["id"])
    except (KeyError, ValueError):
        raise AuthError("В данных входа нет Telegram ID.")
    return {"id": tg_id, "username": fields.get("username", ""), "first_name": fields.get("first_name", "")}


def check_webapp(init_data: str) -> dict:
    """initData из Telegram Mini App: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app"""
    if not BOT_TOKEN:
        raise AuthError("На сервере не задан BOT_TOKEN.")
    try:
        fields = dict(parse_qsl(init_data or "", keep_blank_values=True, strict_parsing=True))
    except ValueError:
        raise AuthError("Повреждённые данные Mini App.")
    received = fields.pop("hash", "")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, _data_check_string(fields).encode(), hashlib.sha256).hexdigest()
    if not received or not hmac.compare_digest(calc.encode(), received.encode()):
        raise AuthError("Подпись Telegram не сошлась.")
    if not _fresh(fields):
        raise AuthError("Данные входа устарели, откройте приложение заново.")
    try:
        user = json.loads(fields["user"])
        tg_id = int(user["id"])
    except (KeyError, ValueError, TypeError):
        raise AuthError("В данных Mini App нет пользователя.")
    return {"id": tg_id, "username": user.get("username", ""), "first_name": user.get("first_name", "")}


def make_token(tg_id: int, username: str) -> str:
    payload = json.dumps({"u": tg_id, "n": username or "", "e": int(time.time()) + SESSION_DAYS * 86400},
                         separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = hmac.new(SECRET_KEY, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_token(token: str):
    """(telegram_id, username) или None, если подпись неверна или срок вышел."""
    try:
        body, sig = token.rsplit(".", 1)
        calc = hmac.new(SECRET_KEY, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, sig):
            return None
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if data["e"] < time.time():
            return None
        return int(data["u"]), data.get("n", "")
    except Exception:
        return None
