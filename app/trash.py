"""Корзина: удалённые записи и карточки хранятся TRASH_DAYS дней и могут быть восстановлены мастером.

Картинки и файлы раздаток остаются в базе (помечены как «в корзине»: по ссылке не открываются и в лимит не входят),
через TRASH_DAYS дней всё удаляется окончательно.
"""
import json
import time

from . import db, handouts, portraits
from .config import TRASH_DAYS


def put(kind, item_id, title, data, extra=None, by=""):
    with db.lock:
        cur = db.conn().execute(
            "INSERT INTO trash(kind,item_id,title,data,extra,deleted_at,deleted_by) VALUES(?,?,?,?,?,?,?)",
            (kind, str(item_id), str(title or "")[:200], json.dumps(data, ensure_ascii=False),
             json.dumps(extra, ensure_ascii=False) if extra is not None else None, time.time(), by))
        return cur.lastrowid


def listing():
    with db.lock:
        rows = db.conn().execute("SELECT id,kind,item_id,title,deleted_at,deleted_by FROM trash ORDER BY id DESC").fetchall()
    now = time.time()
    return [{"id": r["id"], "kind": r["kind"], "item_id": r["item_id"], "title": r["title"], "ts": int(r["deleted_at"] * 1000),
             "by": r["deleted_by"], "days_left": max(0, int(TRASH_DAYS - (now - r["deleted_at"]) / 86400))} for r in rows]


def count():
    with db.lock:
        return db.conn().execute("SELECT COUNT(*) FROM trash").fetchone()[0]


def get(trash_id):
    with db.lock:
        r = db.conn().execute("SELECT * FROM trash WHERE id=?", (trash_id,)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "kind": r["kind"], "item_id": r["item_id"], "title": r["title"], "data": json.loads(r["data"]),
            "extra": json.loads(r["extra"]) if r["extra"] else None, "deleted_at": r["deleted_at"]}


def latest_for(kind, item_id):
    with db.lock:
        r = db.conn().execute("SELECT id FROM trash WHERE kind=? AND item_id=? ORDER BY id DESC LIMIT 1", (kind, str(item_id))).fetchone()
    return r["id"] if r else None


def _drop_blobs(kind, item_id):
    if kind == "dossier":
        portraits.remove(item_id)
    elif kind == "handouts":
        handouts.remove(item_id)


def remove(trash_id, drop_blobs=True):
    """Окончательно убрать запись из корзины вместе с её картинкой или файлом."""
    row = get(trash_id)
    if not row:
        return False
    with db.tx() as c:
        c.execute("DELETE FROM trash WHERE id=?", (trash_id,))
    if drop_blobs:
        _drop_blobs(row["kind"], row["item_id"])
    return True


def empty():
    n = 0
    for row in listing():
        n += remove(row["id"])
    return n


def purge_expired(days=None):
    days = TRASH_DAYS if days is None else days
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    with db.lock:
        ids = [r["id"] for r in db.conn().execute("SELECT id FROM trash WHERE deleted_at<?", (cutoff,)).fetchall()]
    return sum(remove(i) for i in ids)
