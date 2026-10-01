"""Скрипты обновления сервера: deploy/update.sh и deploy/rollback.sh.

Настоящего docker в тестах нет, его заменяет tests/tools/fake_docker.sh: «контейнеры» запускают настоящий код портала на
настоящих папках. Сама установка («сервер») собирается в tmp: старый код, .env, настройки, база от ПЕРВОЙ версии портала
(tests/fixtures/legacy_v1.sql). Проверяется то, ради чего скрипты написаны: база не теряется при любом сбое.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
META = json.loads((FIXTURES / "legacy_v1.json").read_text(encoding="utf-8"))
OLD_ENV = "DOMAIN=portal.example.test\nBOT_TOKEN=старый-секрет\n"


def tree(path):
    """Отпечаток папки: относительные пути, права и содержимое всех файлов."""
    out = {}
    for p in sorted(Path(path).rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            out[str(p.relative_to(path))] = (stat.S_IMODE(p.stat().st_mode), hashlib.sha256(p.read_bytes()).hexdigest())
    return out


def db_version(db):
    return sqlite3.connect(db).execute("PRAGMA user_version").fetchone()[0]


def count(db, table):
    return sqlite3.connect(db).execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class Site:
    """Поддельный сервер: старая установка, распакованная новая версия, заглушки docker и папка для копий."""

    def __init__(self, base):
        self.base = base
        self.new, self.srv, self.backups, self.bin, self.stub = (base / n for n in ("new", "srv", "backups", "bin", "stub"))
        for d in (self.bin, self.stub):
            d.mkdir()
        for name in ("app", "static", "deploy"):
            shutil.copytree(ROOT / name, self.new / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (self.new / "config").mkdir()
        shutil.copy(ROOT / "config" / "campaign.example.json", self.new / "config")
        for name in ("Dockerfile", "docker-compose.yml", "requirements.txt", ".env.example"):
            shutil.copy(ROOT / name, self.new / name)
        # старая установка
        (self.srv / "config").mkdir(parents=True)
        (self.srv / "app").mkdir()
        (self.srv / "static").mkdir()
        (self.srv / "deploy").mkdir()
        (self.srv / "docker-compose.yml").write_text("# старый compose\n", encoding="utf-8")
        (self.srv / ".env").write_text(OLD_ENV, encoding="utf-8")
        (self.srv / ".env").chmod(0o600)
        (self.srv / "app" / "main.py").write_text("СТАРЫЙ КОД\n", encoding="utf-8")
        (self.srv / "static" / "old.js").write_text("// старый файл\n", encoding="utf-8")
        (self.srv / "deploy" / "Caddyfile").write_text("старый Caddyfile\n", encoding="utf-8")
        shutil.copy(FIXTURES / "players.toml", self.srv / "config" / "players.toml")
        shutil.copy(FIXTURES / "campaign.json", self.srv / "config" / "campaign.json")
        data = self.srv / "data"
        data.mkdir()
        conn = sqlite3.connect(data / "portal.db")
        conn.executescript((FIXTURES / "legacy_v1.sql").read_text(encoding="utf-8"))
        conn.commit()
        conn.close()
        (data / "secret.key").write_text(META["secret_key"])
        (data / "backups").mkdir()
        (data / "backups" / "portal-20750101.db").write_bytes("старая копия".encode())
        # заглушки
        shutil.copy(ROOT / "tests" / "tools" / "fake_docker.sh", self.bin / "docker")
        (self.bin / "docker").chmod(0o755)
        (self.stub / "install-dir").write_text(str(self.srv))
        (self.stub / "state").write_text("running")
        (self.stub / "running_code").write_text("old")
        self.original_db = hashlib.sha256((data / "portal.db").read_bytes()).hexdigest()
        self.original_tree = tree(self.srv)

    def env(self, **extra):
        env = dict(os.environ, DOCKER=str(self.bin / "docker"), PYTHON=sys.executable, ASSUME_ROOT="1", CHOWN="true", STUB_DIR=str(self.stub),
                   STUB_CODE=str(self.new), STUB_PYTHON=sys.executable, CURL="false", CONFIG_DIR="", DEV_LOGIN="0", SCHEDULER="0")
        env.pop("CONFIG_DIR")
        env.update(extra)
        return env

    def flag(self, name):
        (self.stub / name).write_text("1")

    def update(self, *args, input=None, env=None, script=None):
        cmd = ["bash", str(script or self.new / "deploy" / "update.sh"), "--install-dir", str(self.srv), "--backups-dir", str(self.backups),
               "--health-wait", "6", *args]
        return subprocess.run(cmd, env=env or self.env(), input=input, capture_output=True, text=True, timeout=600, cwd=self.base)

    def calls(self):
        return (self.stub / "calls.log").read_text(encoding="utf-8").splitlines() if (self.stub / "calls.log").exists() else []

    def backup_dirs(self):
        return sorted(self.backups.iterdir()) if self.backups.exists() else []

    def only_backup(self):
        dirs = self.backup_dirs()
        assert len(dirs) == 1, dirs
        return dirs[0]

    def state(self):
        return (self.stub / "state").read_text().strip(), (self.stub / "running_code").read_text().strip()

    def after_update_dirs(self):
        return sorted(self.srv.glob("data.after-update-*"))


@pytest.fixture
def site(tmp_path):
    return Site(tmp_path)


def assert_everything_as_before(site):
    """Установка в точности такая же, как до обновления: код, настройки и база (проверка после отката)."""
    assert tree(site.srv) == site.original_tree


# ---------------------------------------------------------------- сами скрипты

def test_scripts_are_valid_bash_and_executable_through_bash():
    for name in ("update.sh", "rollback.sh"):
        r = subprocess.run(["bash", "-n", str(ROOT / "deploy" / name)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_help_explains_usage():
    r = subprocess.run(["bash", str(ROOT / "deploy" / "update.sh"), "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "--rehearse-only" in r.stdout and "rollback.sh" in r.stdout and "--skip-public-check" in r.stdout
    r = subprocess.run(["bash", str(ROOT / "deploy" / "rollback.sh"), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "data.after-update" in r.stdout


def test_unknown_option_is_refused():
    r = subprocess.run(["bash", str(ROOT / "deploy" / "update.sh"), "--nonsense"], capture_output=True, text=True)
    assert r.returncode == 2 and "Неизвестный параметр" in r.stdout


# ---------------------------------------------------------------- репетиция

def test_rehearse_only_changes_nothing_on_the_server(site):
    r = site.update("--rehearse-only")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Миграция прошла: схема 0 → 7" in r.stdout and "Все данные на месте" in r.stdout and "ничего не изменено" in r.stdout
    assert_everything_as_before(site)
    assert site.state() == ("running", "old")                                      # портал не останавливали
    assert not any(c.startswith("compose stop") or c.startswith("compose up") for c in site.calls())
    bk = site.only_backup()                                                         # осталась только копия для репетиции
    assert (bk / "portal-live.db").is_file() and db_version(bk / "portal-live.db") == 0
    assert not (bk / "data").exists()


def test_rehearsal_failure_stops_before_touching_anything(site):
    conn = sqlite3.connect(site.srv / "data" / "portal.db")
    conn.execute("DELETE FROM portraits")                                           # карточка ссылается на картинку, которой нет
    conn.commit()
    conn.close()
    site.original_tree = tree(site.srv)
    r = site.update("--yes")
    assert r.returncode != 0
    assert "картинка карточки" in r.stdout and "Репетиция нашла проблемы" in r.stderr
    assert_everything_as_before(site)
    assert site.state() == ("running", "old")
    assert not any(c.startswith("compose stop") for c in site.calls())


def test_a_broken_database_is_never_updated(site):
    (site.srv / "data" / "portal.db").write_bytes("это не база".encode() * 200)
    site.original_tree = tree(site.srv)
    r = site.update("--yes")
    assert r.returncode != 0
    assert_everything_as_before(site)
    assert not any(c.startswith("compose stop") for c in site.calls())


# ---------------------------------------------------------------- обновление

def test_full_update_keeps_all_data_and_swaps_the_code(site):
    r = site.update("--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Готово: портал обновлён" in r.stdout and "Сверка прошла" in r.stdout
    srv = site.srv
    # код заменён
    assert (srv / "app" / "preflight.py").is_file() and not (srv / "static" / "old.js").exists()
    assert (srv / "app" / "main.py").read_text(encoding="utf-8") != "СТАРЫЙ КОД\n"
    assert (srv / "deploy" / "update.sh").is_file() and "старый Caddyfile" not in (srv / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    # настройки на месте
    assert (srv / ".env").read_text(encoding="utf-8") == OLD_ENV
    assert (srv / "config" / "players.toml").read_bytes() == (FIXTURES / "players.toml").read_bytes()
    assert (srv / "config" / "campaign.json").read_bytes() == (FIXTURES / "campaign.json").read_bytes()
    assert (srv / "config" / "campaign.example.json").is_file()                     # а новые примеры приехали
    assert (srv / "data" / "secret.key").read_text() == META["secret_key"]
    assert (srv / "data" / "backups" / "portal-20750101.db").read_bytes() == "старая копия".encode()
    # база мигрировала и ничего не потеряла
    assert db_version(srv / "data" / "portal.db") == 7
    for table, n in META["counts"].items():
        assert count(srv / "data" / "portal.db", table) >= n, table
    assert site.state() == ("running", "new")


def test_full_update_leaves_a_complete_backup_outside_the_install_dir(site):
    r = site.update("--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    bk = site.only_backup()
    assert not str(bk).startswith(str(site.srv))
    assert stat.S_IMODE(bk.stat().st_mode) == 0o700 and stat.S_IMODE(site.backups.stat().st_mode) == 0o700
    # холодная копия data байт в байт такая, какой была база до обновления
    assert hashlib.sha256((bk / "data" / "portal.db").read_bytes()).hexdigest() == site.original_db
    assert (bk / "data" / "secret.key").read_text() == META["secret_key"]
    assert (bk / "portal-live.db").is_file() and (bk / "portal-after.db").is_file()
    assert (bk / "rollback.sh").read_bytes() == (ROOT / "deploy" / "rollback.sh").read_bytes()
    assert (bk / "install-dir").read_text().strip() == str(site.srv)
    names = subprocess.run(["tar", "-tzf", str(bk / "code-before.tgz")], capture_output=True, text=True, check=True).stdout
    assert "./app/main.py" in names and "./.env" in names and "./config/players.toml" in names and "./data/" not in names
    assert any(c.startswith("tag sha256:oldimage seattle2075-portal-before-update:") for c in site.calls())   # старый образ сохранён


def test_update_order_is_rehearse_then_stop_then_swap_then_compare(site):
    assert site.update("--yes").returncode == 0
    calls = site.calls()
    idx = lambda prefix: next(i for i, c in enumerate(calls) if c.startswith(prefix))
    assert idx("build") < idx("run") < idx("compose stop app") < idx("tag") < idx("compose up -d --build --force-recreate")
    assert idx("compose up") < max(i for i, c in enumerate(calls) if "--compare" in c)
    run = next(c for c in calls if c.startswith("run") and "--db" in c)
    assert "--network none" in run and ":ro" in run                                # репетиция без сети и с базой только для чтения


def test_asking_for_confirmation_and_declining_changes_nothing(site):
    r = site.update(input="n\n")
    assert r.returncode == 0 and "Отменено" in r.stdout
    assert_everything_as_before(site)
    assert site.state() == ("running", "old")
    assert not any(c.startswith("compose stop") for c in site.calls())


def test_asking_for_confirmation_and_agreeing_updates(site):
    r = site.update(input="y\n")
    assert r.returncode == 0 and db_version(site.srv / "data" / "portal.db") == 7


def test_update_reports_new_optional_settings(site):
    r = site.update("--yes")
    assert r.returncode == 0
    assert "Новые необязательные настройки" in r.stdout and "ANTHROPIC_API_KEY" in r.stdout


def test_public_check_is_reported(site):
    curl = site.bin / "curl"
    curl.write_text('#!/bin/sh\necho \'{"ok": true}\'\n')
    curl.chmod(0o755)
    r = site.update("--yes", env=site.env(CURL=str(curl)))
    assert r.returncode == 0 and "Портал отвечает снаружи: https://portal.example.test/healthz" in r.stdout


def test_two_updates_in_a_row_make_two_backups_and_stay_healthy(site):
    assert site.update("--yes").returncode == 0
    before = site.srv / "data" / "portal.db"
    count_before = count(before, "entries")
    import time
    time.sleep(1.1)                                                                 # метка копии берётся с точностью до секунды
    r = site.update("--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(site.backup_dirs()) == 2 and count(before, "entries") == count_before and db_version(before) == 7
    assert "Схема уже актуальна" in r.stdout


# ---------------------------------------------------------------- отказы: в каждом база остаётся целой

def test_unhealthy_new_version_rolls_back_automatically(site):
    site.flag("fail_health")
    r = site.update("--yes")
    assert r.returncode != 0
    assert "Откатываюсь" in r.stdout + r.stderr and "Откат выполнен" in r.stdout
    srv = site.srv
    assert (srv / "app" / "main.py").read_text(encoding="utf-8") == "СТАРЫЙ КОД\n" and not (srv / "app" / "preflight.py").exists()
    assert (srv / "static" / "old.js").is_file()
    assert hashlib.sha256((srv / "data" / "portal.db").read_bytes()).hexdigest() == site.original_db
    assert db_version(srv / "data" / "portal.db") == 0
    assert (srv / ".env").read_text(encoding="utf-8") == OLD_ENV
    assert site.state() == ("running", "old")
    kept = site.after_update_dirs()
    assert len(kept) == 1 and db_version(kept[0] / "portal.db") == 7               # то, что успела сделать новая версия, не выбросили


def test_failed_compose_up_rolls_back_automatically(site):
    site.flag("fail_up")
    r = site.update("--yes")
    assert r.returncode != 0
    assert hashlib.sha256((site.srv / "data" / "portal.db").read_bytes()).hexdigest() == site.original_db
    assert (site.srv / "app" / "main.py").read_text(encoding="utf-8") == "СТАРЫЙ КОД\n"
    assert site.state() == ("running", "old")


def test_data_loss_after_start_is_caught_and_rolled_back(site):
    site.flag("break_data")                                                         # «новая версия» при запуске стирает сообщения
    r = site.update("--yes")
    assert r.returncode != 0
    assert "пропали" in r.stdout and "messages" in r.stdout
    assert hashlib.sha256((site.srv / "data" / "portal.db").read_bytes()).hexdigest() == site.original_db
    assert count(site.srv / "data" / "portal.db", "messages") == META["counts"]["messages"]
    assert (site.srv / "app" / "main.py").read_text(encoding="utf-8") == "СТАРЫЙ КОД\n"
    assert site.state() == ("running", "old")


def test_failure_while_copying_data_just_restarts_the_old_portal(site):
    real_cp = shutil.which("cp")
    fake = site.bin / "cp"
    fake.write_text(f'#!/bin/sh\n[ "$1" = "-a" ] && {{ echo "cp: нет места на диске" >&2; exit 1; }}\nexec {real_cp} "$@"\n')
    fake.chmod(0o755)
    r = site.update("--yes", env=site.env(PATH=f"{site.bin}:{os.environ['PATH']}"))
    assert r.returncode != 0
    assert "Запускаю портал обратно" in r.stdout + r.stderr
    calls = site.calls()
    assert "compose stop app" in calls and calls.index("compose start app") > calls.index("compose stop app")
    assert site.state() == ("running", "old")
    assert (site.srv / "app" / "main.py").read_text(encoding="utf-8") == "СТАРЫЙ КОД\n"
    assert hashlib.sha256((site.srv / "data" / "portal.db").read_bytes()).hexdigest() == site.original_db
    assert not any(c.startswith("compose up") for c in calls)                       # до замены кода дело не дошло


def test_when_even_the_old_version_wont_start_the_copy_is_still_there(site):
    site.flag("fail_health")
    site.flag("fail_old_up")                                                        # откат тоже не смог поднять портал
    r = site.update("--yes")
    assert r.returncode != 0
    assert "Автоматический откат не удался" in r.stdout + r.stderr or "Откатываюсь" in r.stdout + r.stderr
    bk = site.only_backup()
    assert hashlib.sha256((bk / "data" / "portal.db").read_bytes()).hexdigest() == site.original_db
    assert hashlib.sha256((site.srv / "data" / "portal.db").read_bytes()).hexdigest() == site.original_db


# ---------------------------------------------------------------- отказ до начала работы

def test_incomplete_install_is_refused(site):
    (site.srv / ".env").unlink()
    r = site.update("--yes")
    assert r.returncode != 0 and "нет .env" in r.stdout + r.stderr
    assert not site.backup_dirs()


def test_running_from_the_install_dir_is_refused(site):
    for name in ("docker-compose.yml", ".env"):
        shutil.copy(site.srv / name, site.new / name)
    shutil.copytree(site.srv / "config", site.new / "config", dirs_exist_ok=True)
    shutil.copytree(site.srv / "data", site.new / "data")
    r = subprocess.run(["bash", str(site.new / "deploy" / "update.sh"), "--install-dir", str(site.new), "--backups-dir", str(site.backups)],
                       env=site.env(), capture_output=True, text=True, cwd=site.base)
    assert r.returncode != 0 and "из самой папки портала" in r.stdout + r.stderr


def test_low_disk_space_is_refused(site):
    df = site.bin / "df"
    df.write_text("#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted\\n/dev/x 1000 990 10 99%% /\\n'\n")
    df.chmod(0o755)
    r = site.update("--yes", env=site.env(PATH=f"{site.bin}:{os.environ['PATH']}"))
    assert r.returncode != 0 and "Мало места" in r.stdout + r.stderr
    assert_everything_as_before(site)


def test_not_root_is_refused(site):
    env = site.env()
    env["ASSUME_ROOT"] = "0"
    if os.getuid() == 0:
        pytest.skip("тест под root: проверка не сработает")
    r = site.update("--yes", env=env)
    assert r.returncode != 0 and "sudo" in r.stdout + r.stderr


def test_missing_docker_is_reported(site):
    r = site.update("--yes", env=site.env(DOCKER="/nonexistent/docker"))
    assert r.returncode != 0 and "docker" in r.stdout + r.stderr


# ---------------------------------------------------------------- ручной откат

def update_then_use_the_new_version(site):
    assert site.update("--yes").returncode == 0
    conn = sqlite3.connect(site.srv / "data" / "portal.db")                         # игроки уже поработали на новой версии
    conn.execute("INSERT INTO meta(key,value) VALUES('после обновления','да')")
    conn.commit()
    conn.close()
    return site.only_backup()


def test_manual_rollback_restores_code_and_database(site):
    bk = update_then_use_the_new_version(site)
    r = subprocess.run(["bash", str(bk / "rollback.sh"), "--yes", "--health-wait", "6"], env=site.env(), capture_output=True, text=True, cwd=site.base, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Откат выполнен" in r.stdout
    srv = site.srv
    assert hashlib.sha256((srv / "data" / "portal.db").read_bytes()).hexdigest() == site.original_db
    assert (srv / "app" / "main.py").read_text(encoding="utf-8") == "СТАРЫЙ КОД\n" and not (srv / "app" / "preflight.py").exists()
    assert (srv / ".env").read_text(encoding="utf-8") == OLD_ENV
    assert (srv / "config" / "players.toml").read_bytes() == (FIXTURES / "players.toml").read_bytes()
    kept = site.after_update_dirs()
    assert len(kept) == 1
    assert sqlite3.connect(kept[0] / "portal.db").execute("SELECT value FROM meta WHERE key='после обновления'").fetchone() == ("да",)
    assert site.state() == ("running", "old")


def test_manual_rollback_asks_first(site):
    bk = update_then_use_the_new_version(site)
    new_state = tree(site.srv)
    r = subprocess.run(["bash", str(bk / "rollback.sh"), "--health-wait", "6"], env=site.env(), input="n\n", capture_output=True, text=True, cwd=site.base)
    assert r.returncode == 0 and "Отменено" in r.stdout
    assert tree(site.srv) == new_state and not site.after_update_dirs()


def test_rollback_works_from_any_folder_and_finds_the_install_by_itself(site):
    bk = update_then_use_the_new_version(site)
    elsewhere = site.base / "elsewhere"
    elsewhere.mkdir()
    r = subprocess.run(["bash", str(bk / "rollback.sh"), "--yes", "--health-wait", "6"], env=site.env(), capture_output=True, text=True, cwd=elsewhere)
    assert r.returncode == 0 and f"в {site.srv}" in r.stdout


def test_rollback_refuses_a_folder_that_is_not_a_backup(site):
    stray = site.base / "stray"
    stray.mkdir()
    shutil.copy(ROOT / "deploy" / "rollback.sh", stray / "rollback.sh")
    r = subprocess.run(["bash", str(stray / "rollback.sh"), "--yes", "--install-dir", str(site.srv)], env=site.env(), capture_output=True, text=True)
    assert r.returncode != 0 and "не папка резервной копии" in r.stdout + r.stderr
    assert_everything_as_before(site)


def test_rollback_twice_is_harmless(site):
    bk = update_then_use_the_new_version(site)
    for _ in range(2):
        r = subprocess.run(["bash", str(bk / "rollback.sh"), "--yes", "--health-wait", "6"], env=site.env(), capture_output=True, text=True, cwd=site.base)
        assert r.returncode == 0, r.stdout + r.stderr
        import time
        time.sleep(1.1)
    assert hashlib.sha256((site.srv / "data" / "portal.db").read_bytes()).hexdigest() == site.original_db


def test_update_works_again_after_a_rollback(site):
    bk = update_then_use_the_new_version(site)
    subprocess.run(["bash", str(bk / "rollback.sh"), "--yes", "--health-wait", "6"], env=site.env(), capture_output=True, text=True, cwd=site.base, check=True)
    import time
    time.sleep(1.1)
    r = site.update("--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert db_version(site.srv / "data" / "portal.db") == 7 and site.state() == ("running", "new")
