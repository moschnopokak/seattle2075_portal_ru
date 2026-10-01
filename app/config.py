"""Настройки портала: переменные окружения и файлы в config/."""
import logging
import os
import secrets
import threading
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

log = logging.getLogger("portal.config")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
CONFIG_DIR = Path(os.getenv("CONFIG_DIR", BASE_DIR / "config"))
STATIC_DIR = BASE_DIR / "static"

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
SITE_URL = os.getenv("SITE_URL", "").strip().rstrip("/")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()
NOTIFY_DM = os.getenv("NOTIFY_DM", "1") == "1"
BACKUP_TELEGRAM = os.getenv("BACKUP_TELEGRAM", "0") == "1"
# Адрес «пульса» для healthchecks.io (или своего healthchecks): после каждой копии туда уходит сигнал, а если сигнала нет, сервис пишет вам
HEALTHCHECKS_URL = os.getenv("HEALTHCHECKS_URL", "").strip().rstrip("/")
# Политика безопасности содержимого (CSP): off | report-only (только сообщает о нарушениях) | enforce (блокирует)
CSP_MODE = os.getenv("CSP_MODE", "report-only").strip().lower()
if CSP_MODE not in ("off", "report-only", "enforce"):
    CSP_MODE = "report-only"
# Как кнопка входа Telegram передаёт результат: redirect (переход на /auth/telegram) | callback (старый способ, нужен eval)
TG_WIDGET_MODE = "callback" if os.getenv("TG_WIDGET_MODE", "redirect").strip().lower() == "callback" else "redirect"
VERSION = os.getenv("PORTAL_VERSION", "dev").strip() or "dev"  # подставляется при сборке образа (хеш коммита)
DEV_LOGIN_REQUESTED = os.getenv("DEV_LOGIN", "0") == "1"
# Вход без Telegram только для проверки у себя. Если задан токен бота, это рабочий сервер: режим выключен.
DEV_LOGIN = DEV_LOGIN_REQUESTED and not BOT_TOKEN
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1") == "1"
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "30"))
PORTRAIT_QUOTA_MB = float(os.getenv("PORTRAIT_QUOTA_MB", "40"))
PORTRAIT_MAX_UPLOAD_MB = float(os.getenv("PORTRAIT_MAX_UPLOAD_MB", "8"))
HANDOUT_QUOTA_MB = float(os.getenv("HANDOUT_QUOTA_MB", "100"))
HANDOUT_MAX_UPLOAD_MB = float(os.getenv("HANDOUT_MAX_UPLOAD_MB", "15"))

DATA_DIR.mkdir(parents=True, exist_ok=True)


def _secret_key() -> bytes:
    """Ключ подписи сессий: из SECRET_KEY или из data/secret.key (создаётся один раз)."""
    env = os.getenv("SECRET_KEY", "").strip()
    if env:
        return env.encode()
    path = DATA_DIR / "secret.key"
    if not path.exists():
        key = secrets.token_hex(32)
        try:
            # Сразу с правами 0600: ключ не должен хоть на миг оказаться читаемым для всех.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(key)
            return key.encode()
        except FileExistsError:  # параллельный запуск успел раньше
            pass
    return path.read_text().strip().encode()


SECRET_KEY = _secret_key()

# ---------- Игроки и персонажи (config/players.toml) ----------

_people = None
_people_mtime = None
_people_lock = threading.Lock()


def _norm_names(values):
    return {str(v).strip().lstrip("@").lower() for v in values or [] if str(v).strip()}


def _parse_people(raw: bytes) -> dict:
    data = tomllib.loads(raw.decode("utf-8"))
    chars = []
    for c in data.get("characters", []):
        chars.append({"id": str(c["id"]), "name": str(c["name"]), "gen": str(c.get("gen", c["name"]))})
    known = {c["id"] for c in chars}
    gm = data.get("gm", {})
    gm_obj = {
        "name": str(gm.get("name", "Мастер")),
        "ids": {int(x) for x in gm.get("telegram_ids", [])},
        "usernames": _norm_names(gm.get("telegram_usernames", [])),
    }
    players = []
    for i, p in enumerate(data.get("players", [])):
        unknown = [c for c in p.get("characters", []) if c not in known]
        if unknown:
            log.warning("players.toml: у игрока %s неизвестные персонажи %s", p.get("name"), unknown)
        players.append({
            "id": f"p{i + 1}",
            "name": str(p["name"]),
            "ids": {int(x) for x in p.get("telegram_ids", [])},
            "usernames": _norm_names(p.get("telegram_usernames", [])),
            "chars": [c for c in p.get("characters", []) if c in known],
        })
    return {"gm": gm_obj, "players": players, "characters": chars}


def people() -> dict:
    """Список игроков. Файл перечитывается при изменении, перезапуск не нужен."""
    global _people, _people_mtime
    path = CONFIG_DIR / "players.toml"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        if _people is not None:  # файл пропал на ходу: работаем по прежнему списку
            log.error("players.toml не найден, остаётся прежняя версия")
            return _people
        raise FileNotFoundError(
            f"Нет файла {path}. Скопируйте config/players.example.toml в config/players.toml и впишите игроков.") from None
    with _people_lock:
        if _people is None or mtime != _people_mtime:
            try:
                _people = _parse_people(path.read_bytes())
                _people_mtime = mtime
            except Exception:
                if _people is None:
                    raise
                log.exception("players.toml не прочитан, остаётся прежняя версия")
        return _people


def resolve(tg_id: int, username: str):
    """Кто вошёл: ('gm', данные) или ('player', данные) или None."""
    p = people()
    uname = (username or "").lower()

    def match(obj):
        return tg_id in obj["ids"] or (uname and uname in obj["usernames"])

    if match(p["gm"]):
        return "gm", p["gm"]
    for player in p["players"]:
        if match(player):
            return "player", player
    return None
