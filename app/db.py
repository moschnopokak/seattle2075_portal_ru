"""Хранилище на SQLite. Одно соединение и общий замок: игроков немного, этого хватает."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from .config import DATA_DIR

DB_PATH = DATA_DIR / "portal.db"
lock = threading.RLock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS items (
    kind TEXT NOT NULL, id TEXT NOT NULL, pos INTEGER NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS entries (id TEXT PRIMARY KEY, data TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id TEXT NOT NULL, author TEXT NOT NULL,
    user_id INTEGER, text TEXT NOT NULL, ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_entry ON messages(entry_id);
CREATE TABLE IF NOT EXISTS portraits (
    token TEXT NOT NULL, size TEXT NOT NULL, card_id TEXT NOT NULL, data BLOB NOT NULL, bytes INTEGER NOT NULL,
    PRIMARY KEY (token, size)
);
CREATE INDEX IF NOT EXISTS portraits_card ON portraits(card_id);
CREATE TABLE IF NOT EXISTS handout_files (
    token TEXT PRIMARY KEY, item_id TEXT NOT NULL, data BLOB NOT NULL, bytes INTEGER NOT NULL, raw_bytes INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS handout_files_item ON handout_files(item_id);
CREATE TABLE IF NOT EXISTS logins (
    telegram_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_seen REAL
);
"""


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
    return _conn


def init():
    with lock:
        conn().executescript(SCHEMA)


@contextmanager
def tx():
    with lock:
        c = conn()
        c.execute("BEGIN")
        try:
            yield c
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise


# ---------- служебные значения ----------

def meta_get(key, default=None):
    with lock:
        row = conn().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def meta_set(key, value):
    with lock:
        conn().execute(
            "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, None if value is None else str(value)),
        )


def bump() -> int:
    """Номер версии данных: клиенты по нему понимают, что пора обновиться."""
    with lock:
        v = int(meta_get("version", "0")) + 1
        meta_set("version", v)
        return v


# ---------- этапы, регулярные события, хроника, план, таймеры ----------

def items(kind):
    with lock:
        rows = conn().execute("SELECT data FROM items WHERE kind=? ORDER BY pos", (kind,)).fetchall()
    return [json.loads(r["data"]) for r in rows]


def set_items(kind, values):
    with tx() as c:
        c.execute("DELETE FROM items WHERE kind=?", (kind,))
        for pos, item in enumerate(values):
            c.execute("INSERT INTO items(kind,id,pos,data) VALUES(?,?,?,?)",
                      (kind, str(item["id"]), pos, json.dumps(item, ensure_ascii=False)))


# ---------- записи и обсуждения ----------

def _chat_for(ids):
    if not ids:
        return {}
    with lock:
        marks = ",".join("?" * len(ids))
        rows = conn().execute(
            f"SELECT entry_id, author, text, ts FROM messages WHERE entry_id IN ({marks}) ORDER BY id", ids
        ).fetchall()
    chat = {}
    for r in rows:
        chat.setdefault(r["entry_id"], []).append({"a": r["author"], "t": r["text"], "ts": int(r["ts"] * 1000)})
    return chat


def entries():
    with lock:
        rows = conn().execute("SELECT data FROM entries ORDER BY created").fetchall()
    result = [json.loads(r["data"]) for r in rows]
    chat = _chat_for([e["id"] for e in result])
    for e in result:
        e["chat"] = chat.get(e["id"], [])
    return result


def entry(entry_id):
    with lock:
        row = conn().execute("SELECT data FROM entries WHERE id=?", (entry_id,)).fetchone()
    if not row:
        return None
    e = json.loads(row["data"])
    e["chat"] = _chat_for([e["id"]]).get(e["id"], [])
    return e


def save_entry(e):
    data = {k: v for k, v in e.items() if k != "chat"}
    with lock:
        conn().execute(
            "INSERT INTO entries(id,data,created) VALUES(?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (e["id"], json.dumps(data, ensure_ascii=False), e.get("created", time.time())),
        )


def delete_entry(entry_id):
    with tx() as c:
        c.execute("DELETE FROM messages WHERE entry_id=?", (entry_id,))
        c.execute("DELETE FROM entries WHERE id=?", (entry_id,))


def add_message(entry_id, author, user_id, text):
    with lock:
        conn().execute("INSERT INTO messages(entry_id,author,user_id,text,ts) VALUES(?,?,?,?,?)",
                       (entry_id, author, user_id, text, time.time()))


# ---------- входы ----------

def remember_login(tg_id, username, first_name):
    with lock:
        conn().execute(
            "INSERT INTO logins(telegram_id,username,first_name,last_seen) VALUES(?,?,?,?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username, "
            "first_name=excluded.first_name, last_seen=excluded.last_seen",
            (tg_id, (username or "").lower(), first_name or "", time.time()),
        )


def login_ids(usernames):
    """Telegram ID тех, кто уже входил под этими именами пользователя."""
    names = [u for u in usernames if u]
    if not names:
        return set()
    with lock:
        marks = ",".join("?" * len(names))
        rows = conn().execute(f"SELECT telegram_id FROM logins WHERE username IN ({marks})", names).fetchall()
    return {r["telegram_id"] for r in rows}
