"""Резервные копии: создание, проверка, восстановление, отправка в Telegram."""
import gzip
import os
import re
import sqlite3
import subprocess
import sys

import pytest

from app import backup, config, db, notify


@pytest.fixture
def copy_dir(tmp_path):
    return tmp_path / "copies"


def test_backup_is_valid_unique_and_pruned(started, copy_dir):
    made = [backup.backup(keep=2, target_dir=copy_dir) for _ in range(4)]
    assert len({p.name for p in made}) == 4                      # имена не совпадают даже в одну секунду
    assert sorted(p.name for p in copy_dir.glob("portal-*.db")) == sorted(p.name for p in made[-2:])
    info = backup.verify(made[-1])
    assert info["dossier"] == 3 and info["places"] == 3 and info["version"] > 0


def test_verify_rejects_bad_files(tmp_path):
    with pytest.raises(backup.BackupError, match="не найден"):
        backup.verify(tmp_path / "нет.db")
    junk = tmp_path / "junk.db"
    junk.write_bytes("это не база".encode() * 100)
    with pytest.raises(backup.BackupError, match="не открывается"):
        backup.verify(junk)
    alien = tmp_path / "alien.db"
    sqlite3.connect(alien).execute("CREATE TABLE other (x)").connection.close()
    with pytest.raises(backup.BackupError, match="не копия портала"):
        backup.verify(alien)


def test_restore_roundtrip_keeps_a_safety_copy(started, gm, tmp_path, monkeypatch):
    from helpers import entry, ok
    monkeypatch.setattr(backup, "folder", lambda: tmp_path)
    data = ok(gm.post("/api/entries", json=entry(title="Было при копии", who=["rig"])))
    saved = backup.backup(target_dir=tmp_path / "c")
    ok(gm.post("/api/entries", json=entry(title="Появилось после копии", who=["rig"])))
    # «боевая» база для восстановления: копия текущей
    target = tmp_path / "live.db"
    sqlite3.connect(db.DB_PATH).backup(sqlite3.connect(target))
    before = sqlite3.connect(target).execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    safety = backup.restore(saved, target=target)
    after = sqlite3.connect(target).execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    assert after == before - 1                                   # запись, сделанная после копии, исчезла
    titles = [json_title for (json_title,) in sqlite3.connect(target).execute("SELECT json_extract(data,'$.title') FROM entries")]
    assert "Было при копии" in titles and "Появилось после копии" not in titles
    assert safety.exists() and sqlite3.connect(safety).execute("SELECT COUNT(*) FROM entries").fetchone()[0] == before
    # чистка: удалить созданные записи в рабочей базе
    for e in gm.get("/api/state").json()["entries"]:
        if e["title"] in ("Было при копии", "Появилось после копии"):
            gm.post(f"/api/entries/{e['id']}/act", json={"act": "del"})
    assert data["msg"]


def test_restore_refuses_a_bad_copy_and_leaves_the_base_intact(tmp_path):
    target = tmp_path / "live.db"
    sqlite3.connect(target).execute("CREATE TABLE keep (x)").connection.close()
    bad = tmp_path / "bad.db"
    bad.write_bytes("мусор".encode() * 50)
    with pytest.raises(backup.BackupError):
        backup.restore(bad, target=target)
    assert sqlite3.connect(target).execute("SELECT name FROM sqlite_master").fetchone()[0] == "keep"


def test_command_line_end_to_end(tmp_path):
    """Настоящие команды на отдельной папке данных: копия, проверка, порча базы, восстановление."""
    env = dict(os.environ, DATA_DIR=str(tmp_path), CONFIG_DIR=str(tmp_path), BACKUP_TELEGRAM="0")
    env.pop("BOT_TOKEN", None)

    def run(*args, stdin=None):
        return subprocess.run([sys.executable, "-m", "app.backup", *args], env=env, capture_output=True, text=True, input=stdin)

    subprocess.run([sys.executable, "-c", "from app import db; db.init(); db.meta_set('version', 7); db.meta_set('mark', 'до')"],
                   env=env, check=True)
    made = run()
    assert made.returncode == 0 and re.search(r"portal-\d{8}-\d{6}-\d{6}\.db", made.stdout)
    checked = run("--verify")
    assert checked.returncode == 0 and "всё в порядке" in checked.stdout
    # портим рабочую базу
    (tmp_path / "portal.db").write_bytes(b"\0" * 4096)
    refused = run("--restore", made.stdout.strip(), stdin="нет\n")
    assert refused.returncode == 1 and "Отменено" in refused.stdout
    restored = run("--restore", made.stdout.strip(), "--yes")
    assert restored.returncode == 0 and "База восстановлена" in restored.stdout
    mark = sqlite3.connect(tmp_path / "portal.db").execute("SELECT value FROM meta WHERE key='mark'").fetchone()[0]
    assert mark == "до"
    kept = list((tmp_path / "backups").glob("before-restore-*.db"))
    assert kept and kept[0].read_bytes() == b"\0" * 4096        # повреждённая база сохранена как есть
    assert run("--verify", str(tmp_path / "нет.db")).returncode == 1


class FakeResponse:
    def __init__(self, body=b'{"ok": true}'):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_telegram_upload_format(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen.update(url=req.full_url, headers=dict(req.header_items()), body=req.data)
        return FakeResponse()

    monkeypatch.setattr(notify, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    notify.send_document(42, "portal.db.gz", b"\x1f\x8bDATA", "подпись")
    assert seen["url"] == "https://api.telegram.org/bot123:ABC/sendDocument"
    boundary = re.search(r"boundary=(\S+)", seen["headers"]["Content-type"]).group(1)
    body = seen["body"]
    assert body.count(b"--" + boundary.encode()) == 4 and body.rstrip().endswith(b"--" + boundary.encode() + b"--")
    assert b'name="chat_id"\r\n\r\n42\r\n' in body
    assert "подпись".encode() in body
    assert b'name="document"; filename="portal.db.gz"' in body and b"\x1f\x8bDATA" in body


def test_send_to_telegram_compresses_and_reaches_the_gm(started, tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(backup, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(notify, "send_document", lambda chat, name, data, caption="": sent.append((chat, name, data, caption)))
    path = backup.backup(target_dir=tmp_path)
    assert backup.send_to_telegram(path) == 1
    chat, name, data, caption = sent[0]
    assert chat == 1 and name == path.name + ".gz" and "Резервная копия" in caption
    restored = tmp_path / "unpacked.db"
    restored.write_bytes(gzip.decompress(data))
    assert backup.verify(restored)["dossier"] == 3               # отправленное действительно открывается


def test_send_to_telegram_failure_modes(started, tmp_path, monkeypatch):
    path = backup.backup(target_dir=tmp_path)
    monkeypatch.setattr(backup, "BOT_TOKEN", "")
    with pytest.raises(backup.BackupError, match="BOT_TOKEN"):
        backup.send_to_telegram(path)
    monkeypatch.setattr(backup, "BOT_TOKEN", "123:ABC")

    def refuse(*a, **k):
        raise RuntimeError("Telegram 403: бот не может писать первым")

    monkeypatch.setattr(notify, "send_document", refuse)
    with pytest.raises(backup.BackupError, match="нажать «Запустить»"):
        backup.send_to_telegram(path)
    monkeypatch.setattr(backup, "TELEGRAM_LIMIT", 10)
    with pytest.raises(backup.BackupError, match="лимита Telegram"):
        backup.send_to_telegram(path)


def test_cli_returns_2_when_telegram_fails_but_copy_exists(tmp_path):
    env = dict(os.environ, DATA_DIR=str(tmp_path), CONFIG_DIR=str(tmp_path), BACKUP_TELEGRAM="1", BOT_TOKEN="1:x")
    subprocess.run([sys.executable, "-c", "from app import db; db.init()"], env=env, check=True)
    (tmp_path / "players.toml").write_text('[gm]\nname="М"\ntelegram_ids=[]\ntelegram_usernames=[]\n', encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "app.backup"], env=env, capture_output=True, text=True)
    assert result.returncode == 2 and "Не знаю, кому отправить" in result.stderr
    assert list((tmp_path / "backups").glob("portal-*.db"))      # локальная копия всё равно сделана


def test_config_flag_defaults_off():
    assert config.BACKUP_TELEGRAM is False
