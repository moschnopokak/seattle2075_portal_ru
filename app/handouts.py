"""Раздатки: HTML-файлы, которые мастер выдаёт персонажам.

Файл хранится в базе в сжатом виде (gzip), поэтому попадает в резервные копии.
Общий объём сжатых файлов ограничен HANDOUT_QUOTA_MB, размер одного загружаемого файла HANDOUT_MAX_UPLOAD_MB.
HTML отдаётся по случайному токену с заголовком Content-Security-Policy: sandbox. Браузер
открывает такую страницу в «песочнице» с отдельным пустым источником, поэтому скрипты раздатки
не видят ни входа в портал, ни его данных, даже если открыть ссылку отдельно.
"""
import gzip
import secrets

from . import config, db

SANDBOX = ("sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox allow-modals allow-forms "
           "allow-downloads; frame-ancestors 'self'")


class HandoutError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.message, self.code = message, code


def quota_bytes():
    return int(config.HANDOUT_QUOTA_MB * 1024 * 1024)


def upload_limit_bytes():
    return int(config.HANDOUT_MAX_UPLOAD_MB * 1024 * 1024)


def check(raw):
    """Проверяет, что это текст HTML, и возвращает его сжатым."""
    if not raw or not raw.strip():
        raise HandoutError("Файл пустой.")
    if b"\x00" in raw[:65536]:
        raise HandoutError("Это не HTML-файл. Загрузите страницу с расширением .html.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HandoutError("Файл не в кодировке UTF-8. Пересохраните его в UTF-8.")
    head = text[:20000].lower()
    if "<" not in head or not any(t in head for t in ("<!doctype", "<html", "<body", "<head", "<div", "<main", "<section", "<p", "<svg")):
        raise HandoutError("Не похоже на HTML: нет разметки страницы.")
    return gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0), len(text.encode("utf-8"))


def usage():
    with db.lock:
        row = db.conn().execute("SELECT COALESCE(SUM(bytes),0) AS b FROM handout_files").fetchone()
    return {"used": int(row["b"]), "quota": quota_bytes(), "limit": upload_limit_bytes()}


def item_bytes(item_id):
    with db.lock:
        row = db.conn().execute("SELECT COALESCE(SUM(bytes),0) AS b FROM handout_files WHERE item_id=?", (item_id,)).fetchone()
    return int(row["b"])


def store(item_id, packed, raw_bytes):
    token = secrets.token_hex(16)
    with db.tx() as c:
        c.execute("DELETE FROM handout_files WHERE item_id=?", (item_id,))
        c.execute("INSERT INTO handout_files(token,item_id,data,bytes,raw_bytes) VALUES(?,?,?,?,?)",
                  (token, item_id, packed, len(packed), raw_bytes))
    return token


def rotate(item_id):
    """Новый токен для файла раздатки: прежняя ссылка перестаёт открываться. None, если файла нет."""
    token = secrets.token_hex(16)
    with db.tx() as c:
        changed = c.execute("UPDATE handout_files SET token=? WHERE item_id=?", (token, item_id)).rowcount
    return token if changed else None


def remove(item_id):
    with db.tx() as c:
        c.execute("DELETE FROM handout_files WHERE item_id=?", (item_id,))


def get(token):
    with db.lock:
        row = db.conn().execute("SELECT data FROM handout_files WHERE token=?", (token,)).fetchone()
    return bytes(row["data"]) if row else None
