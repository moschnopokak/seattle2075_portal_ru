"""Картинки досье: сжатие до фиксированного размера и общий лимит хранилища.

Загруженный файл никогда не сохраняется как есть. Он перекодируется в два квадратных WebP:
480x480 для карточки и 96x96 для списка. Метаданные (в том числе координаты съёмки) отбрасываются.
Картинки лежат в той же базе SQLite, поэтому попадают в резервные копии.
Общий объём ограничен переменной PORTRAIT_QUOTA_MB, размер загружаемого файла ограничен
PORTRAIT_MAX_UPLOAD_MB.
"""
import io
import secrets
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from . import config, db

FULL_PX = 480
THUMB_PX = 96
FULL_MAX_BYTES = 90 * 1024
THUMB_MAX_BYTES = 10 * 1024
MIN_SIDE = 64
MAX_PIXELS_JPEG = 40_000_000   # JPEG читается уменьшенным, память почти не тратится
MAX_PIXELS_OTHER = 16_000_000  # PNG, WebP и GIF читаются целиком
FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
NEUTRAL_BG = (236, 238, 240)

Image.MAX_IMAGE_PIXELS = MAX_PIXELS_JPEG


class PortraitError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.message, self.code = message, code


def quota_bytes():
    return int(config.PORTRAIT_QUOTA_MB * 1024 * 1024)


def upload_limit_bytes():
    return int(config.PORTRAIT_MAX_UPLOAD_MB * 1024 * 1024)


def mb(n):
    """Размер в мегабайтах для сообщений: до 10 МБ с двумя знаками, дальше с одним."""
    return (f"{n / 1048576:.2f}" if n < 10 * 1048576 else f"{n / 1048576:.1f}").replace(".", ",")


def _square(im):
    """Квадрат по короткой стороне. У вертикальных кадров окно сдвинуто выше центра, чтобы не срезать лица."""
    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top = int((h - side) * 0.2) if h > w else 0
    return im.crop((left, top, left + side, top + side))


def _encode(im, px, limit):
    """Кодирует в WebP, снижая качество и размер, пока результат не уложится в лимит."""
    best = None
    for scale in (1.0, 0.9, 0.8, 0.7):
        size = max(int(px * scale), 32)
        small = im.resize((size, size), Image.LANCZOS)
        for quality in (84, 76, 68, 60, 52, 46):
            buf = io.BytesIO()
            small.save(buf, "WEBP", quality=quality, method=6)
            data = buf.getvalue()
            best = data
            if len(data) <= limit:
                return data
    return best


def process(raw):
    """Проверяет и перекодирует картинку. Возвращает (крупная, миниатюра) в виде байтов WebP."""
    if not raw:
        raise PortraitError("Файл пустой.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            probe = Image.open(io.BytesIO(raw))
            fmt, (w, h) = probe.format, probe.size
            probe.verify()
    except Image.DecompressionBombError:
        raise PortraitError("У картинки слишком большое разрешение. Уменьшите её или обрежьте перед загрузкой.")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise PortraitError("Не удалось прочитать картинку. Подойдут JPEG, PNG и WebP.")
    if fmt not in FORMATS:
        raise PortraitError("Этот формат не поддерживается. Подойдут JPEG, PNG и WebP.")
    if min(w, h) < MIN_SIDE:
        raise PortraitError(f"Картинка слишком маленькая: нужно хотя бы {MIN_SIDE} точек по короткой стороне.")
    if w * h > (MAX_PIXELS_JPEG if fmt == "JPEG" else MAX_PIXELS_OTHER):
        raise PortraitError("У картинки слишком большое разрешение. Уменьшите её или обрежьте перед загрузкой.")
    try:
        im = Image.open(io.BytesIO(raw))
        if fmt == "JPEG":
            im.draft("RGB", (FULL_PX * 2, FULL_PX * 2))
        im.load()
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            bg = Image.new("RGBA", rgba.size, NEUTRAL_BG + (255,))
            bg.alpha_composite(rgba)
            im = bg
        im = _square(im.convert("RGB"))
        full = _encode(im, FULL_PX, FULL_MAX_BYTES)
        thumb = _encode(im, THUMB_PX, THUMB_MAX_BYTES)
    except PortraitError:
        raise
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError, MemoryError):
        raise PortraitError("Файл повреждён или не открывается.")
    return full, thumb


# ---------- хранение ----------

def usage():
    with db.lock:
        row = db.conn().execute(
            "SELECT COALESCE(SUM(bytes),0) AS b, COUNT(DISTINCT card_id) AS n FROM portraits").fetchone()
    return {"used": int(row["b"]), "quota": quota_bytes(), "count": int(row["n"])}


def card_bytes(card_id):
    with db.lock:
        row = db.conn().execute(
            "SELECT COALESCE(SUM(bytes),0) AS b FROM portraits WHERE card_id=?", (card_id,)).fetchone()
    return int(row["b"])


def store(card_id, full, thumb):
    """Сохраняет новую картинку карточки и удаляет прежнюю. Возвращает токен нового изображения."""
    token = secrets.token_hex(16)
    with db.tx() as c:
        c.execute("DELETE FROM portraits WHERE card_id=?", (card_id,))
        for size, data in (("f", full), ("t", thumb)):
            c.execute("INSERT INTO portraits(token,size,card_id,data,bytes) VALUES(?,?,?,?,?)",
                      (token, size, card_id, data, len(data)))
    return token


def remove(card_id):
    with db.tx() as c:
        c.execute("DELETE FROM portraits WHERE card_id=?", (card_id,))


def get(token, size):
    with db.lock:
        row = db.conn().execute("SELECT data FROM portraits WHERE token=? AND size=?", (token, size)).fetchone()
    return bytes(row["data"]) if row else None
