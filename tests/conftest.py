"""Общая среда тестов: отдельная папка данных и конфиг из tests/fixtures.

Переменные окружения задаются ДО импорта приложения: app.config читает их при импорте.
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest

pytest_plugins = ["ui_support"]   # фикстуры браузерных тестов (Playwright подгружается только при их использовании)

FIXTURES = Path(__file__).parent / "fixtures"
_tmp = Path(tempfile.mkdtemp(prefix="portal-tests-"))
(_tmp / "config").mkdir()
(_tmp / "data").mkdir()
shutil.copy(FIXTURES / "campaign.json", _tmp / "config" / "campaign.json")
shutil.copy(FIXTURES / "players.toml", _tmp / "config" / "players.toml")
for _name in ("BOT_TOKEN", "BOT_USERNAME", "SECRET_KEY", "SITE_URL", "TG_CHAT_ID"):
    os.environ.pop(_name, None)
os.environ.update(DATA_DIR=str(_tmp / "data"), CONFIG_DIR=str(_tmp / "config"),
                  DEV_LOGIN="1", COOKIE_SECURE="0", NOTIFY_DM="0", SCHEDULER="0")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

GM, MAX, GATE, RIG, HAG, ELI, NOCHAR, STRANGER = 1, 101, 102, 103, 104, 105, 106, 999


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def tmp_root():
    return _tmp


@pytest.fixture(scope="session", autouse=True)
def started():
    """Запускает приложение (создаёт базу из campaign.json) один раз на весь прогон."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def login(tg_id):
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/api/auth/dev", json={"tg_id": tg_id})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def anon(started):
    """Каждому тесту свой клиент без cookie: вход в одном тесте не должен делать «анонимом» игрока в другом."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="session")
def gm(started):
    return login(GM)


@pytest.fixture(scope="session")
def players(started):
    return {"max": login(MAX), "gate": login(GATE), "rig": login(RIG), "hag": login(HAG), "eli": login(ELI)}


@pytest.fixture(scope="session")
def gate(players):
    return players["gate"]


@pytest.fixture(scope="session")
def rig(players):
    return players["rig"]


@pytest.fixture(scope="session")
def hag(players):
    return players["hag"]


KINDS = ("windows", "rhythm", "clocks", "plan", "past", "places", "dossier", "handouts", "travel", "money", "factions", "standing", "contacts", "locmaps")


@pytest.fixture
def sandbox(gm):
    """Запоминает состояние портала и после теста убирает всё созданное, возвращает время и описания районов."""
    before = gm.get("/api/state").json()
    ids = {k: {x["id"] for x in before[k]} for k in KINDS}
    ids["entries"] = {e["id"] for e in before["entries"]}
    dnotes = {d["id"]: d for d in before["dnotes"]}
    yield
    after = gm.get("/api/state").json()
    for e in after["entries"]:
        if e["id"] not in ids["entries"]:
            gm.post(f"/api/entries/{e['id']}/act", json={"act": "del"})
    for kind in KINDS:
        for x in after[kind]:
            if x["id"] not in ids[kind]:
                gm.post(f"/api/gm/items/{kind}/{x['id']}/delete")
    for slug, d in dnotes.items():
        gm.post(f"/api/gm/district/{slug}", json={"text": d.get("text", ""), "gm_text": d.get("gm_text", "")})
    gm.post("/api/gm/time", json={"date": before["now"]["date"], "tod": before["now"]["tod"], "quiet": before["quietUntil"]})
