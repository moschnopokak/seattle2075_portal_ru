"""Раздатки: файлы, которые мастер выдаёт персонажам. HTML-страницы, картинки, PDF и аудио.

Тип файла определяется по содержимому (первым байтам), а не по расширению и не по тому, что назвал браузер.
HTML хранится в базе в сжатом виде (gzip), остальное как есть: картинки, PDF и звук уже сжаты. Всё лежит в базе,
поэтому попадает в резервные копии. Общий объём ограничен HANDOUT_QUOTA_MB, размер одного загружаемого файла HANDOUT_MAX_UPLOAD_MB.

HTML отдаётся по случайному токену с заголовком Content-Security-Policy: sandbox. Браузер открывает такую страницу
в «песочнице» с отдельным пустым источником, поэтому скрипты раздатки не видят ни входа в портал, ни его данных,
даже если открыть ссылку отдельно. Картинки перекодируются (так пропадают метаданные, в том числе координаты съёмки,
и скрытый в файле лишний код); PDF и звук отдаются с точным типом и запретом угадывания типа (nosniff).
"""
import gzip
import io
import secrets
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from . import config, db

SANDBOX = ("sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox allow-modals allow-forms "
           "allow-downloads; frame-ancestors 'self'")
MAX_PIXELS = 60_000_000        # больше этого картинку не берём: ни памяти, ни смысла
FULL_OPTIMIZE_PIXELS = 12_000_000
IMAGE_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
M4A_BRANDS = (b"M4A ", b"M4B ", b"mp42", b"mp41", b"isom", b"iso2")
KIND_NAMES = {"html": "страница", "image": "картинка", "pdf": "PDF", "audio": "аудио"}
DEFAULT_NAMES = {"html": "раздатка.html", "image": "картинка", "pdf": "раздатка.pdf", "audio": "запись"}


class HandoutError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.message, self.code = message, code


def quota_bytes():
    return int(config.HANDOUT_QUOTA_MB * 1024 * 1024)


def upload_limit_bytes():
    return int(config.HANDOUT_MAX_UPLOAD_MB * 1024 * 1024)


# ---------- определение типа по содержимому ----------

def _mp3(raw):
    if raw[:3] == b"ID3":
        return True
    if len(raw) > 4 and raw[0] == 0xFF and raw[1] & 0xE0 == 0xE0:
        version, layer, bitrate, rate = (raw[1] >> 3) & 3, (raw[1] >> 1) & 3, raw[2] >> 4, (raw[2] >> 2) & 3
        return version != 1 and layer != 0 and bitrate != 15 and rate != 3
    return False


def sniff(raw):
    """Что это за файл: ('pdf'|'image'|'audio', mime) или None, если это не один из бинарных видов (тогда считаем HTML)."""
    if raw.lstrip(b"\xef\xbb\xbf\r\n\t ")[:5] == b"%PDF-":
        return "pdf", "application/pdf"
    head = raw[:16]
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image", "image/png"
    if head[:3] == b"\xff\xd8\xff":
        return "image", "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image", "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image", "image/webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio", "audio/wav"
    if head[:4] == b"OggS":
        return "audio", "audio/ogg"
    if head[:4] == b"fLaC":
        return "audio", "audio/flac"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "audio", "audio/webm"
    if head[4:8] == b"ftyp" and raw[8:12] in M4A_BRANDS:
        return "audio", "audio/mp4"
    if _mp3(raw):
        return "audio", "audio/mpeg"
    return None


# ---------- проверка и подготовка ----------

def check(raw):
    """Проверяет, что это текст HTML, и возвращает его сжатым."""
    if not raw or not raw.strip():
        raise HandoutError("Файл пустой.")
    if b"\x00" in raw[:65536]:
        raise HandoutError("Не удалось определить тип файла. Подходят HTML-страницы, картинки (PNG, JPEG, GIF, WebP), PDF и аудио (MP3, M4A, OGG, WAV, FLAC).")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HandoutError("Файл не в кодировке UTF-8. Пересохраните его в UTF-8.")
    head = text[:20000].lower()
    if "<" not in head or not any(t in head for t in ("<!doctype", "<html", "<body", "<head", "<div", "<main", "<section", "<p", "<svg")):
        raise HandoutError("Не похоже на HTML: нет разметки страницы.")
    return gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0), len(text.encode("utf-8"))


def _image(raw):
    """Читает картинку целиком и кодирует заново без метаданных. Анимации (GIF, анимированные PNG и WebP) остаются как есть."""
    bad_file = HandoutError("Картинка не читается: файл повреждён или это не картинка.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            im = Image.open(io.BytesIO(raw))
            fmt = im.format
            if fmt not in IMAGE_FORMATS:
                raise HandoutError("Картинки принимаются в форматах PNG, JPEG, GIF и WebP.")
            w, h = im.size
            if w * h > MAX_PIXELS:
                raise HandoutError(f"Картинка слишком большая: {w}×{h}. Допустимо до {MAX_PIXELS // 1_000_000} мегапикселей, уменьшите её.")
            animated = fmt == "GIF" or getattr(im, "n_frames", 1) > 1
            if animated:
                Image.open(io.BytesIO(raw)).verify()
                return IMAGE_FORMATS[fmt], raw
            im = ImageOps.exif_transpose(im)
            out = io.BytesIO()
            if fmt == "JPEG":
                im.convert("RGB").save(out, "JPEG", quality=92, optimize=True, progressive=True)
            elif fmt == "PNG":
                im.save(out, "PNG", optimize=w * h <= FULL_OPTIMIZE_PIXELS)
            else:
                im.save(out, "WEBP", quality=92, method=4)
            return IMAGE_FORMATS[fmt], out.getvalue()
    except HandoutError:
        raise
    except Image.DecompressionBombError:
        raise HandoutError(f"Картинка слишком большая: допустимо до {MAX_PIXELS // 1_000_000} мегапикселей, уменьшите её.") from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError):
        raise bad_file from None


def prepare(raw):
    """Проверяет файл и готовит его к хранению: {'kind', 'mime', 'encoding', 'data', 'raw_bytes'}. HandoutError с понятным текстом при отказе."""
    if not raw or not raw.strip():
        raise HandoutError("Файл пустой.")
    found = sniff(raw)
    if not found:
        packed, size = check(raw)
        return {"kind": "html", "mime": "text/html", "encoding": "gzip", "data": packed, "raw_bytes": size}
    kind, mime = found
    if kind == "pdf":
        if b"%%EOF" not in raw[-65536:]:
            raise HandoutError("PDF обрезан или повреждён: у файла нет конца. Сохраните его заново.")
        return {"kind": "pdf", "mime": mime, "encoding": "raw", "data": raw, "raw_bytes": len(raw)}
    if kind == "image":
        mime, data = _image(raw)
        return {"kind": "image", "mime": mime, "encoding": "raw", "data": data, "raw_bytes": len(data)}
    return {"kind": "audio", "mime": mime, "encoding": "raw", "data": raw, "raw_bytes": len(raw)}


# ---------- хранилище ----------

def usage():
    with db.lock:
        row = db.conn().execute("SELECT COALESCE(SUM(bytes),0) AS b FROM handout_files WHERE trashed=0").fetchone()
    return {"used": int(row["b"]), "quota": quota_bytes(), "limit": upload_limit_bytes()}


def item_bytes(item_id):
    with db.lock:
        row = db.conn().execute("SELECT COALESCE(SUM(bytes),0) AS b FROM handout_files WHERE item_id=? AND trashed=0", (item_id,)).fetchone()
    return int(row["b"])


def store(item_id, prepared):
    token = secrets.token_hex(16)
    with db.tx() as c:
        c.execute("DELETE FROM handout_files WHERE item_id=?", (item_id,))
        c.execute("INSERT INTO handout_files(token,item_id,data,bytes,raw_bytes,mime,encoding) VALUES(?,?,?,?,?,?,?)",
                  (token, item_id, prepared["data"], len(prepared["data"]), prepared["raw_bytes"], prepared["mime"], prepared["encoding"]))
    return token


def rotate(item_id):
    """Новый токен для файла раздатки: прежняя ссылка перестаёт открываться. None, если файла нет."""
    token = secrets.token_hex(16)
    with db.tx() as c:
        changed = c.execute("UPDATE handout_files SET token=? WHERE item_id=?", (token, item_id)).rowcount
    return token if changed else None


def trash(item_id):
    """Раздатка в корзине: файл остаётся в базе, но по ссылке не открывается и в лимит не входит."""
    with db.tx() as c:
        c.execute("UPDATE handout_files SET trashed=1 WHERE item_id=?", (item_id,))


def untrash(item_id):
    with db.tx() as c:
        c.execute("UPDATE handout_files SET trashed=0 WHERE item_id=?", (item_id,))


def trashed_bytes(item_id):
    with db.lock:
        row = db.conn().execute("SELECT COALESCE(SUM(bytes),0) AS b FROM handout_files WHERE item_id=? AND trashed=1", (item_id,)).fetchone()
    return int(row["b"])


def remove(item_id):
    with db.tx() as c:
        c.execute("DELETE FROM handout_files WHERE item_id=?", (item_id,))


def get(token):
    """Файл по токену: {'data', 'mime', 'encoding'} или None."""
    with db.lock:
        row = db.conn().execute("SELECT data, mime, encoding FROM handout_files WHERE token=? AND trashed=0", (token,)).fetchone()
    return {"data": bytes(row["data"]), "mime": row["mime"], "encoding": row["encoding"]} if row else None
