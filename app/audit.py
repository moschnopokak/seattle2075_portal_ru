"""Журнал изменений: кто, когда и что менял. Читает только мастер.

Для правок хранятся состояния «до» и «после» (JSON), по ним видно, какие поля изменились, и можно откатить правку.
"""
import json
import time

from . import db
from .config import AUDIT_DAYS

# Поля, которые в сравнении не показываются: служебные или меняющиеся сами по себе
IGNORED = {"chat", "created", "img", "file", "size", "fname", "uploaded", "id"}
VALUE_LIMIT = 400
RECORD_LIMIT = 200


def _dump(value):
    return None if value is None else json.dumps(value, ensure_ascii=False)


def actor_of(v):
    """(id, имя, роль) того, кто действует. v=None: система (фоновые задачи)."""
    if v is None:
        return None, "Система", "system"
    return v.tg_id, ("Мастер" if v.gm else v.name), ("gm" if v.gm else "player")


def record(v, action, kind, item_id="", title="", before=None, after=None):
    """Добавляет запись в журнал. Вызывать внутри db.lock вместе с самим изменением."""
    actor_id, actor, role = actor_of(v)
    with db.lock:
        db.conn().execute(
            "INSERT INTO audit(ts,actor_id,actor,role,action,kind,item_id,title,before,after) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (time.time(), actor_id, actor, role, action, kind, str(item_id), str(title or "")[:200], _dump(before), _dump(after)))


def _short(value):
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = "" if value is None else str(value)
    return text if len(text) <= VALUE_LIMIT else text[:VALUE_LIMIT] + "…"


def changes(before, after):
    """Что изменилось между двумя состояниями: [{field, before, after}] без служебных полей."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return []
    out = []
    for key in sorted(set(before) | set(after)):
        if key in IGNORED or before.get(key) == after.get(key):
            continue
        out.append({"field": key, "before": _short(before.get(key)), "after": _short(after.get(key))})
    return out[:30]


def _row(r, with_changes=True):
    before = json.loads(r["before"]) if r["before"] else None
    after = json.loads(r["after"]) if r["after"] else None
    item = {"id": r["id"], "ts": int(r["ts"] * 1000), "actor": r["actor"], "role": r["role"], "action": r["action"],
            "kind": r["kind"], "item_id": r["item_id"], "title": r["title"]}
    if with_changes:
        item["changes"] = changes(before, after) if r["action"] == "edit" or (before and after) else []
    return item


def listing(limit=50, before_id=None, kind="", item_id="", query=""):
    """Последние записи, новые сверху. Фильтры: вид, номер элемента, подстрока в названии или имени."""
    sql, args = "SELECT * FROM audit WHERE 1=1", []
    if before_id:
        sql += " AND id<?"
        args.append(int(before_id))
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    if item_id:
        sql += " AND item_id=?"
        args.append(item_id)
    if query:
        sql += " AND (title LIKE ? ESCAPE '\\' OR actor LIKE ? ESCAPE '\\')"
        like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        args += [like, like]
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(int(limit), RECORD_LIMIT)))
    with db.lock:
        rows = db.conn().execute(sql, args).fetchall()
    return [_row(r) for r in rows]


def get(audit_id):
    with db.lock:
        r = db.conn().execute("SELECT * FROM audit WHERE id=?", (audit_id,)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "action": r["action"], "kind": r["kind"], "item_id": r["item_id"], "title": r["title"],
            "before": json.loads(r["before"]) if r["before"] else None, "after": json.loads(r["after"]) if r["after"] else None}


def purge_old(days=None):
    days = AUDIT_DAYS if days is None else days
    if days <= 0:
        return 0
    with db.tx() as c:
        return c.execute("DELETE FROM audit WHERE ts<?", (time.time() - days * 86400,)).rowcount
