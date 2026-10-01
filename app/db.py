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


# Версионные миграции. SCHEMA выше это исходная схема (версия 1); всё новое добавляется сюда, и каждая миграция
# выполняется один раз (номер хранится в PRAGMA user_version). Новая база и старая приходят к одной схеме.
def _m2_audit_and_trash(c):
    c.execute("""CREATE TABLE IF NOT EXISTS audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor_id INTEGER, actor TEXT NOT NULL, role TEXT NOT NULL,
        action TEXT NOT NULL, kind TEXT NOT NULL, item_id TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
        before TEXT, after TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS audit_ts ON audit(ts)")
    c.execute("CREATE INDEX IF NOT EXISTS audit_item ON audit(kind, item_id)")
    c.execute("""CREATE TABLE IF NOT EXISTS trash (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, item_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
        data TEXT NOT NULL, extra TEXT, deleted_at REAL NOT NULL, deleted_by TEXT NOT NULL DEFAULT '')""")
    c.execute("ALTER TABLE portraits ADD COLUMN trashed INTEGER NOT NULL DEFAULT 0")
    c.execute("ALTER TABLE handout_files ADD COLUMN trashed INTEGER NOT NULL DEFAULT 0")


def _m3_outbox_and_prefs(c):
    c.execute("""CREATE TABLE IF NOT EXISTS outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
        section TEXT, buttons TEXT, key TEXT, count INTEGER NOT NULL DEFAULT 1, meta TEXT,
        created REAL NOT NULL, send_after REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0)""")
    c.execute("CREATE INDEX IF NOT EXISTS outbox_due ON outbox(send_after)")
    c.execute("CREATE INDEX IF NOT EXISTS outbox_key ON outbox(tg_id, key)")
    c.execute("""CREATE TABLE IF NOT EXISTS user_prefs (
        tg_id INTEGER PRIMARY KEY, tz TEXT NOT NULL DEFAULT 'UTC',
        quiet_on INTEGER NOT NULL DEFAULT 0, quiet_from INTEGER NOT NULL DEFAULT 23, quiet_to INTEGER NOT NULL DEFAULT 8,
        digest_on INTEGER NOT NULL DEFAULT 0, digest_hour INTEGER NOT NULL DEFAULT 9,
        chat_notify INTEGER NOT NULL DEFAULT 1, updated REAL)""")


def _m4_invite_clock(c):
    c.execute("""CREATE TABLE IF NOT EXISTS invite_clock (
        entry_id TEXT NOT NULL, char TEXT NOT NULL, asked REAL NOT NULL, reminded INTEGER NOT NULL DEFAULT 0, last REAL NOT NULL,
        PRIMARY KEY (entry_id, char))""")
    c.execute("ALTER TABLE user_prefs ADD COLUMN remind INTEGER NOT NULL DEFAULT 1")


def _m5_handout_media(c):
    """Раздатками могут быть не только HTML-страницы: у файла теперь есть тип и способ хранения (gzip или как есть)."""
    c.execute("ALTER TABLE handout_files ADD COLUMN mime TEXT NOT NULL DEFAULT 'text/html'")
    c.execute("ALTER TABLE handout_files ADD COLUMN encoding TEXT NOT NULL DEFAULT 'gzip'")


MIGRATIONS = [
    (2, "журнал изменений и корзина", _m2_audit_and_trash),
    (3, "очередь уведомлений и настройки пользователей", _m3_outbox_and_prefs),
    (4, "напоминания о неотвеченных приглашениях", _m4_invite_clock),
    (5, "тип файла раздатки (картинки, PDF, аудио)", _m5_handout_media),
]
LATEST = MIGRATIONS[-1][0]


def schema_version() -> int:
    return conn().execute("PRAGMA user_version").fetchone()[0]


def migrate():
    current = schema_version()
    for version, _name, fn in MIGRATIONS:
        if version > current:
            with tx() as c:
                fn(c)
                c.execute(f"PRAGMA user_version={int(version)}")


def init():
    with lock:
        conn().executescript(SCHEMA)
        migrate()


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
        c.execute("DELETE FROM invite_clock WHERE entry_id=?", (entry_id,))
        c.execute("DELETE FROM entries WHERE id=?", (entry_id,))


def add_message(entry_id, author, user_id, text, ts=None):
    with lock:
        conn().execute("INSERT INTO messages(entry_id,author,user_id,text,ts) VALUES(?,?,?,?,?)",
                       (entry_id, author, user_id, text, time.time() if ts is None else ts))


def raw_messages(entry_id):
    """Сообщения обсуждения как есть (для корзины)."""
    with lock:
        rows = conn().execute("SELECT author, user_id, text, ts FROM messages WHERE entry_id=? ORDER BY id", (entry_id,)).fetchall()
    return [{"author": r["author"], "user_id": r["user_id"], "text": r["text"], "ts": r["ts"]} for r in rows]


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
