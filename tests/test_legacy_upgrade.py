"""Обновление базы, созданной ПЕРВОЙ версией портала (так выглядит база на вашем сервере).

tests/fixtures/legacy_v1.sql это дамп настоящей базы, которую наполнил код самой первой версии (коммит f9785e9) через его же
интерфейс: записи и ответы, обсуждения, развитие, план мастера с маской, хроника, места, досье с картинкой и сведениями, раздатка
с файлом, районы, время. legacy_v1.json хранит то, что тот код отдавал каждому игроку, и его же подписанные входные cookie.
Сборка: tests/tools/make_legacy_db.py. Новая версия обязана открыть эту базу, ничего не потерять и продолжить работать.
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.db import LATEST

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
META = json.loads((FIXTURES / "legacy_v1.json").read_text(encoding="utf-8"))


def make_data(tmp_path, name="data"):
    data = tmp_path / name
    data.mkdir()
    conn = sqlite3.connect(data / "portal.db")
    conn.executescript((FIXTURES / "legacy_v1.sql").read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    (data / "secret.key").write_text(META["secret_key"])
    return data


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_python(args, data, **env):
    full = dict(os.environ, DATA_DIR=str(data), CONFIG_DIR=str(FIXTURES), PYTHONPATH=str(ROOT), DEV_LOGIN="0", COOKIE_SECURE="0", SCHEDULER="0", **env)
    return subprocess.run([sys.executable, *args], env=full, capture_output=True, text=True, cwd=ROOT, timeout=600)


@pytest.fixture(scope="module")
def upgraded(tmp_path_factory):
    """Новая версия запущена на базе старой версии: отчёт о том, что она отдаёт и что умеет."""
    data = make_data(tmp_path_factory.mktemp("legacy"))
    result = run_python([str(ROOT / "tests" / "tools" / "legacy_check.py"), str(FIXTURES / "legacy_v1.json")], data)
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1]), data


# ---------------------------------------------------------------- репетиция

def test_fixture_is_really_a_first_version_database():
    assert META["user_version"] == 0                                              # первая версия не вела номер схемы
    assert set(META["counts"]) == {"meta", "items", "entries", "messages", "portraits", "handout_files", "logins"}
    assert META["counts"]["entries"] >= 8 and META["counts"]["portraits"] == 2 and META["counts"]["handout_files"] == 1


def test_rehearsal_passes_and_leaves_the_original_file_untouched(tmp_path):
    data = make_data(tmp_path)
    before = sha(data / "portal.db")
    r = run_python(["-m", "app.preflight", "--db", str(data / "portal.db")], tmp_path / "unused")
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert f"Миграция прошла: схема 0 → {LATEST}" in out and "Все данные на месте" in out and "можно обновлять" in out
    assert "Мастер и игроки (6)" in out and "Картинки и раздатки" in out
    assert sha(data / "portal.db") == before                                      # репетиция работала с копией
    assert sqlite3.connect(data / "portal.db").execute("PRAGMA user_version").fetchone()[0] == 0
    assert not list(data.glob("portal.db-*"))                                     # и следов (wal, shm) не оставила


def test_rehearsal_reports_the_counts(tmp_path):
    data = make_data(tmp_path)
    out = run_python(["-m", "app.preflight", "--db", str(data / "portal.db")], tmp_path / "unused").stdout
    assert "entries 9→9" in out and "messages 3→3" in out and "portraits 2→2" in out and "handout_files 1→1" in out and "items 26→31" in out


# ---------------------------------------------------------------- новая версия поверх старой базы

def test_schema_is_migrated_on_start(upgraded):
    report, data = upgraded
    assert report["user_version"][0] == report["user_version"][1] == LATEST
    assert sqlite3.connect(data / "portal.db").execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_every_viewer_gets_exactly_the_same_data_as_before(upgraded):
    report, _ = upgraded
    assert set(report["viewers"]) == {"gm", "rig", "gate", "hag", "max"}
    for who, v in report["viewers"].items():
        assert v["status"] == 200, who                                            # входные cookie старой версии принимаются: никто не разлогинен
        assert v["missing"] == [], (who, v)                                       # ни один раздел не пропал
        assert v["changed"] == [], (who, v)                                       # ни один элемент не изменился (версия данных растёт, это нормально)
        assert set(v["extra"]) <= {"contacts", "factions", "money", "horizon", "locmaps", "recap", "recap_mode", "recap_open", "recap_ready", "standing", "trash", "travel"}, (who, v["extra"])


def test_anonymous_still_needs_login(upgraded):
    assert upgraded[0]["anonymous"] == 401


def test_portrait_and_handout_files_are_served_byte_for_byte(upgraded):
    for name, (status, size, expected) in upgraded[0]["files"].items():
        assert status == 200 and size == expected, name


def test_the_new_version_can_write_on_top_of_the_old_data(upgraded):
    w = upgraded[0]["writes"]
    assert w["new_entry"] == w["dice_in_old_entry"] == w["message_in_old_entry"] == w["money"] == w["past"] == 200
    assert w["answer_old_invite"] == 200
    assert w["replace_handout_with_pdf"] == 200
    assert w["diary_pdf"] == [200, "%PDF-"]
    assert w["delete_card_to_trash"] == 200 and w["trash_has_card"] is True and w["restore_card"] == 200
    assert w["old_entry_chat"] == [4]                                             # было 2 сообщения, прибавились кубы и сообщение
    assert w["portrait_after_restore"] is True                                    # картинка карточки пережила корзину и восстановление


def test_secret_key_is_kept_so_sessions_survive(upgraded):
    assert (upgraded[1] / "secret.key").read_text().strip() == META["secret_key"]


def test_invitations_already_waiting_get_their_reminder_clock_from_the_update_moment(tmp_path):
    """Приглашения без ответа, созданные давным-давно, не должны получить напоминание в первую же минуту после обновления."""
    data = make_data(tmp_path)
    conn = sqlite3.connect(data / "portal.db")
    month_ago = time.time() - 30 * 86400
    waiting = []
    for entry_id, raw in conn.execute("SELECT id, data FROM entries").fetchall():
        entry = json.loads(raw)
        entry["created"] = month_ago
        conn.execute("UPDATE entries SET data=? WHERE id=?", (json.dumps(entry, ensure_ascii=False), entry_id))
        waiting += [(entry_id, char) for char, answer in entry.get("answers", {}).items() if answer == "ждёт"]
    conn.commit()
    conn.close()
    assert len(waiting) >= 2                                                       # в базе первой версии есть приглашения без ответа
    script = (
        "import json,time\nfrom app import db, reminders, startup\nstartup.prepare_data()\n"
        "now=time.time()\n"
        "rows=[(r['entry_id'],r['char'],now-r['asked']<60) for r in db.conn().execute('SELECT * FROM invite_clock').fetchall()]\n"
        "print(json.dumps({'rows':rows,'due_now':[(e['id'],c) for e,c in reminders.due()],"
        "'due_in_3_days':sorted((e['id'],c) for e,cs in reminders.due(now=now+3*86400) for c in cs)}))\n")
    r = run_python(["-c", script], data)
    assert r.returncode == 0, r.stderr[-1500:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert sorted((e, c) for e, c, fresh in out["rows"] if fresh) == sorted(waiting)
    assert out["due_now"] == []                                                    # сразу после обновления напоминать не о чем
    assert set(map(tuple, out["due_in_3_days"])) <= set(waiting) and out["due_in_3_days"]   # а через срок напоминания работают


# ---------------------------------------------------------------- старый код на новой базе (запасной путь отката)

@pytest.mark.skipif(subprocess.run(["git", "cat-file", "-e", "f9785e9"], cwd=ROOT, capture_output=True).returncode != 0, reason="нет истории git")
def test_the_original_code_still_runs_on_the_migrated_database(tmp_path):
    """Если откатить только код (без возврата базы), старая версия на новой базе должна работать: миграции только добавляют.
    (Файлы раздаток в новых форматах, PDF/картинки/аудио, старая версия открыть не умеет: она знает только HTML. Для них и нужен полный откат.)"""
    work = tmp_path / "work"
    work.mkdir()
    data = make_data(work, "data")
    migrated = run_python(["-c", "from app import startup; startup.prepare_data()"], data)
    assert migrated.returncode == 0, migrated.stderr[-1500:]
    assert sqlite3.connect(data / "portal.db").execute("PRAGMA user_version").fetchone()[0] == LATEST
    old_code = tmp_path / "old"
    old_code.mkdir()
    archive = subprocess.run(["git", "archive", "f9785e9"], cwd=ROOT, capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(old_code)], input=archive, check=True)
    script = (
        "import json,sys;from fastapi.testclient import TestClient;from app.main import app\n"
        "meta=json.load(open(sys.argv[1],encoding='utf-8'))\n"
        "with TestClient(app,raise_server_exceptions=False) as boot:\n"
        "    out={}\n"
        "    for who,t in meta['cookies'].items():\n"
        "        c=TestClient(app,raise_server_exceptions=False);c.cookies.set('session',t);r=c.get('/api/state');out[who]=[r.status_code,len(r.json().get('entries',[]))]\n"
        "    c=TestClient(app,raise_server_exceptions=False);c.cookies.set('session',meta['cookies']['rig'])\n"
        "    out['msg']=c.post('/api/entries/'+meta['ids']['e1']+'/messages',json={'char':'rig','text':'из старой версии'}).status_code\n"
        "    out['file']=c.get(sys.argv[2],headers={'Accept-Encoding':'identity'}).status_code\n"
        "print(json.dumps(out))\n")
    env = dict(os.environ, DATA_DIR=str(data), CONFIG_DIR=str(FIXTURES), PYTHONPATH=str(old_code), DEV_LOGIN="0", COOKIE_SECURE="0")
    token = sqlite3.connect(data / "portal.db").execute("SELECT token FROM handout_files").fetchone()[0]
    r = subprocess.run([sys.executable, "-c", script, str(FIXTURES / "legacy_v1.json"), f"/handout/{token}/view"], env=env, capture_output=True, text=True, cwd=old_code, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert all(out[w][0] == 200 for w in ("gm", "rig", "gate", "hag", "max")) and out["msg"] == 200 and out["file"] == 200


# ---------------------------------------------------------------- сама репетиция: ловит ли она настоящие беды

def rows(db, table):
    return sqlite3.connect(db).execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_rehearsal_refuses_a_corrupted_file(tmp_path):
    bad = tmp_path / "portal.db"
    bad.write_bytes("это не база данных".encode() * 100)
    r = run_python(["-m", "app.preflight", "--db", str(bad)], tmp_path / "unused")
    assert r.returncode == 1 and "✗" in r.stdout


def test_rehearsal_refuses_a_missing_file(tmp_path):
    r = run_python(["-m", "app.preflight", "--db", str(tmp_path / "нет.db")], tmp_path / "unused")
    assert r.returncode == 1 and "нет" in r.stdout


def test_rehearsal_detects_a_missing_portrait_blob(tmp_path):
    data = make_data(tmp_path)
    conn = sqlite3.connect(data / "portal.db")
    conn.execute("DELETE FROM portraits")
    conn.commit()
    conn.close()
    r = run_python(["-m", "app.preflight", "--db", str(data / "portal.db")], tmp_path / "unused")
    assert r.returncode == 1 and "картинка карточки" in r.stdout and "ЕСТЬ ПРОБЛЕМЫ" in r.stdout


def test_rehearsal_detects_a_missing_handout_file(tmp_path):
    data = make_data(tmp_path)
    conn = sqlite3.connect(data / "portal.db")
    conn.execute("DELETE FROM handout_files")
    conn.commit()
    conn.close()
    r = run_python(["-m", "app.preflight", "--db", str(data / "portal.db")], tmp_path / "unused")
    assert r.returncode == 1 and "файла в базе нет" in r.stdout


def test_rehearsal_detects_a_broken_players_file(tmp_path):
    data = make_data(tmp_path)
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "campaign.json").write_text((FIXTURES / "campaign.json").read_text(encoding="utf-8"), encoding="utf-8")
    (cfg / "players.toml").write_text("[gm\nэто сломанный файл", encoding="utf-8")
    env = dict(os.environ, CONFIG_DIR=str(cfg), PYTHONPATH=str(ROOT))
    r = subprocess.run([sys.executable, "-m", "app.preflight", "--db", str(data / "portal.db")], env=env, capture_output=True, text=True, cwd=ROOT, timeout=300)
    assert r.returncode == 1 and ("список игроков" in r.stdout or "ошибкой" in r.stdout)


def test_rehearsal_detects_data_the_code_cannot_read(tmp_path):
    data = make_data(tmp_path)
    conn = sqlite3.connect(data / "portal.db")
    conn.execute("UPDATE entries SET data='{не json'")
    conn.commit()
    conn.close()
    r = run_python(["-m", "app.preflight", "--db", str(data / "portal.db")], tmp_path / "unused")
    assert r.returncode == 1 and "✗" in r.stdout


# ---------------------------------------------------------------- сверка двух баз

def test_compare_accepts_a_database_with_everything_and_more(tmp_path):
    old = make_data(tmp_path, "a") / "portal.db"
    new = make_data(tmp_path, "b") / "portal.db"
    conn = sqlite3.connect(new)
    conn.execute("INSERT INTO meta(key,value) VALUES('новое','1')")
    conn.execute("UPDATE meta SET value='999' WHERE key='version'")                # счётчик версии данных можно менять
    conn.execute("UPDATE logins SET last_seen=last_seen+100")                      # и время входа
    conn.execute("ALTER TABLE logins ADD COLUMN extra TEXT")                       # и добавлять столбцы
    conn.commit()
    conn.close()
    r = run_python(["-m", "app.preflight", "--compare", str(old), str(new)], tmp_path / "unused")
    assert r.returncode == 0 and "есть всё из старой" in r.stdout


@pytest.mark.parametrize("sql,words", [
    ("DELETE FROM entries WHERE rowid=(SELECT MIN(rowid) FROM entries)", "entries"),
    ("DELETE FROM messages", "messages"),
    ("UPDATE messages SET text=text||'!' WHERE id=1", "изменились"),
    ("UPDATE entries SET data=replace(data,'Встреча','Встреч') WHERE rowid=(SELECT MIN(rowid) FROM entries)", "изменились"),
    ("DELETE FROM portraits", "portraits"),
    ("UPDATE handout_files SET data=x'00'", "handout_files"),
    ("DROP TABLE logins", "logins"),
    ("UPDATE meta SET value='другое' WHERE key='now_date'", "meta"),
])
def test_compare_notices_lost_and_changed_data(tmp_path, sql, words):
    old = make_data(tmp_path, "a") / "portal.db"
    new = make_data(tmp_path, "b") / "portal.db"
    conn = sqlite3.connect(new)
    conn.execute(sql)
    conn.commit()
    conn.close()
    r = run_python(["-m", "app.preflight", "--compare", str(old), str(new)], tmp_path / "unused")
    assert r.returncode == 1 and "✗" in r.stdout and words in r.stdout, r.stdout


def test_compare_refuses_a_broken_new_database(tmp_path):
    old = make_data(tmp_path, "a") / "portal.db"
    new = tmp_path / "new.db"
    new.write_bytes("мусор".encode() * 500)
    r = run_python(["-m", "app.preflight", "--compare", str(old), str(new)], tmp_path / "unused")
    assert r.returncode == 1
