"""«Что было раньше» через мастера (RECAP_MODE=gm): игрок просит, портал собирает запрос, мастер копирует его в свой чат с Claude
и вставляет ответ обратно. Главное: в запрос попадает только то, что видит игрок; чужие просьбы и запросы не видны; лимиты и замены работают;
ключ API и обращения к нему не нужны вовсе."""
import json

import pytest

from app import config, db, notify, outbox, recap
from conftest import GM, RIG, GATE
from helpers import ok

SECRET = "СЕКРЕТ"


@pytest.fixture(autouse=True)
def manual(started, monkeypatch):
    monkeypatch.setattr(config, "RECAP_MANUAL", True)
    monkeypatch.setattr(config, "RECAP_ENABLED", False)
    monkeypatch.setattr(config, "RECAP_PER_DAY", 50)

    def no_api():
        raise AssertionError("в режиме «через мастера» портал не должен обращаться к Claude API")
    monkeypatch.setattr(recap, "_client", no_api)
    recap._recent.clear()
    for table in ("recap_requests", "outbox"):
        db.conn().execute(f"DELETE FROM {table}")
    yield
    for table in ("recap_requests", "outbox"):
        db.conn().execute(f"DELETE FROM {table}")
    recap._recent.clear()


@pytest.fixture
def telegram_on(monkeypatch):
    monkeypatch.setattr(notify, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(notify, "NOTIFY_DM", True)


@pytest.fixture
def story(gm, gate, rig, sandbox):
    for day, title in (("2075-07-22", "Первая встреча"), ("2075-07-24", "Налёт на склад"), ("2075-07-26", "Погоня"), ("2075-07-28", "Разбор")):
        ok(gm.post("/api/gm/items/past", json={"title": title, "from": day, "to": day, "note": f"Итог: {title}", "gm_note": f"{SECRET}-{title}", "session": "Арка 1"}))
    card = {"name": "Мэри-Лу", "alias": "Лу", "type": "person", "role": "контрабандист", "stance": "ally", "org": "", "vis": "стол", "known": [], "met": ["rig"],
            "facts": [{"id": "fa1", "text": "Знает ход через канализацию", "vis": "стол", "known": [], "truth": "", "date": "2075-07-26"},
                      {"id": "fa2", "text": f"{SECRET}-только-мастер", "vis": "мастер", "known": [], "truth": "", "date": "2075-07-26"},
                      {"id": "fa3", "text": "Сведение только Гейту", "vis": "знают", "known": ["gate"], "truth": "", "date": "2075-07-27"}], "gm_note": f"{SECRET}-карточка"}
    ok(gm.post("/api/gm/items/dossier", json=card))
    yield {"since": "2075-07-20"}


def ask(client, **body):
    return client.post("/api/me/recap", json=body)


def queue(gm):
    return ok(gm.get("/api/gm/recap"))["items"]


def mine(client):
    return ok(client.get("/api/me/recap/requests"))["items"]


def answer(gm, req_id, text="Вы пропустили налёт.", **kw):
    return gm.post(f"/api/gm/recap/{req_id}/answer", json={"text": text, **kw})


# ---------------------------------------------------------------- режим и признаки в состоянии

def test_state_flags_for_players_and_for_the_master(rig, gm, story):
    state = ok(rig.get("/api/state"))
    assert state["recap"] is True and state["recap_mode"] == "gm" and state["recap_open"] == 0
    state = ok(gm.get("/api/state"))
    assert state["recap"] is False and state["recap_mode"] == "gm" and state["recap_open"] == 0           # мастеру кнопка не нужна, но очередь у него есть
    ask(rig, since=story["since"], char="rig")
    assert ok(rig.get("/api/state"))["recap_open"] == 1 and ok(gm.get("/api/state"))["recap_open"] == 1


def test_each_player_counts_only_his_own_open_requests(rig, gate, gm, story):
    ask(rig, since=story["since"], char="rig")
    ask(gate, since=story["since"], char="gate")
    ask(gate, since="2075-07-25", char="gate")                                               # заменяет прежнюю просьбу Гейта, а не добавляется к ней
    assert ok(rig.get("/api/state"))["recap_open"] == 1 and ok(gate.get("/api/state"))["recap_open"] == 1
    assert ok(gm.get("/api/state"))["recap_open"] == 2


def test_modes_do_not_mix(rig, gm, story, monkeypatch):
    monkeypatch.setattr(config, "RECAP_MANUAL", False)
    assert recap.mode() is None
    r = ask(rig, since=story["since"], char="rig")
    assert r.status_code == 404 and "не включён" in r.json()["detail"]
    state = ok(rig.get("/api/state"))
    assert state["recap"] is False and state["recap_open"] == 0
    assert ok(gm.get("/api/gm/recap")) == {"items": []}
    assert gm.post("/api/gm/recap/1/answer", json={"text": "x"}).status_code == 404
    assert ok(rig.get("/api/me/recap/requests")) == {"items": []}
    monkeypatch.setattr(config, "RECAP_ENABLED", True)                                       # ключ задан и режим не «через мастера»: пишет Claude
    assert recap.mode() == "api" and ok(rig.get("/api/state"))["recap_mode"] == "api"
    monkeypatch.setattr(config, "RECAP_MANUAL", True)                                        # оба сразу невозможны в настройках; ключ главнее только в тесте
    assert recap.mode() == "api"


def config_in_subprocess(tmp_path, **env_extra):
    """Настройки в отдельном процессе: перечитывать config в тестовом процессе нельзя, на нём держатся база и игроки."""
    import os
    import subprocess
    import sys
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC", "RECAP"))}
    env.update(DATA_DIR=str(tmp_path), CONFIG_DIR=str(tmp_path), **env_extra)
    code = "from app import config; print(config.RECAP_MANUAL, config.RECAP_ENABLED)"
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout.strip()


def test_mode_comes_from_the_environment(tmp_path):
    assert config_in_subprocess(tmp_path) == "False False"                                   # по умолчанию ничего не меняется
    assert config_in_subprocess(tmp_path, RECAP_MODE="gm") == "True False"                   # ключ не нужен
    assert config_in_subprocess(tmp_path, RECAP_MODE="  GM ") == "True False"
    assert config_in_subprocess(tmp_path, RECAP_MODE="gm", ANTHROPIC_API_KEY="sk-test") == "True False"        # при режиме «через мастера» ключ не используется
    assert config_in_subprocess(tmp_path, ANTHROPIC_API_KEY="sk-test") == "False True"
    assert config_in_subprocess(tmp_path, RECAP_MODE="auto", ANTHROPIC_API_KEY="sk-test") == "False True"
    assert config_in_subprocess(tmp_path, RECAP_MODE="gm", RECAP="0") == "False False"       # общий выключатель главнее
    assert config_in_subprocess(tmp_path, RECAP_MODE="что-то") == "False False"


# ---------------------------------------------------------------- просьба и запрос для мастера

def test_request_waits_for_the_master_and_gives_him_the_prompt(rig, gm, story):
    r = ask(rig, since=story["since"], char="rig")
    assert r.status_code == 200
    body = r.json()
    assert body["pending"] is True and body["since"] == story["since"] and body["events"] == 5 and isinstance(body["id"], int) and "text" not in body
    (item,) = queue(gm)
    assert item["id"] == body["id"] and item["char"] == "rig" and item["name"] == "Риг" and item["since"] == story["since"] and item["events"] == 5
    p = item["prompt"]
    assert p.startswith(recap.SYSTEM) and "Персонаж: Риг" in p                                # правила и материалы одним текстом для чата
    for needle in ("Первая встреча", "Налёт на склад", "Погоня", "Разбор", "Итог: Погоня", "Мэри-Лу", "Знает ход через канализацию"):
        assert needle in p, needle
    for forbidden in (SECRET, "Сведение только Гейту"):
        assert forbidden not in p, forbidden


def test_each_player_gets_his_own_prompt(rig, gate, gm, story):
    ask(rig, since=story["since"], char="rig")
    ask(gate, since=story["since"], char="gate")
    prompts = {i["char"]: i["prompt"] for i in queue(gm)}
    assert set(prompts) == {"rig", "gate"} and "Персонаж: Гейт" in prompts["gate"] and "Персонаж: Риг" in prompts["rig"]
    assert "Сведение только Гейту" in prompts["gate"] and "Сведение только Гейту" not in prompts["rig"]
    assert all(SECRET not in p for p in prompts.values())


def test_the_same_request_twice_is_one_request(rig, gm, story, telegram_on):
    first = ask(rig, since=story["since"], char="rig").json()
    second = ask(rig, since=story["since"], char="rig").json()
    assert first["id"] == second["id"] and len(queue(gm)) == 1
    assert len([r for r in outbox.pending(GM) if r["kind"] == "recap"]) == 1                 # мастера не дёргают второй раз


def test_a_new_request_replaces_the_open_one_and_the_old_one_cannot_be_answered(rig, gm, story, telegram_on):
    first = ask(rig, since=story["since"], char="rig").json()
    second = ask(rig, since="2075-07-25", char="rig").json()                                 # другой период: другой запрос
    assert second["id"] != first["id"] and second["events"] == 2
    (item,) = queue(gm)
    assert item["id"] == second["id"] and item["since"] == "2075-07-25" and "Первая встреча" not in item["prompt"]
    r = answer(gm, first["id"])
    assert r.status_code == 409 and "поменял" in r.json()["detail"]                           # мастер успел скопировать старый запрос: ответ к новому не приклеится
    assert [i["id"] for i in mine(rig)] == [second["id"]]                                    # заменённых игрок не видит
    assert len([r for r in outbox.pending(GM) if r["kind"] == "recap"]) == 2                 # каждая новая просьба сообщается мастеру


def test_nothing_to_tell_creates_no_request(rig, gm, story):
    r = ask(rig, since="2075-08-01", char="rig")
    assert r.status_code == 400 and "пересказывать нечего" in r.json()["detail"] and queue(gm) == []


@pytest.mark.parametrize("body", [{"since": None}, {"since": "вчера"}, {"since": 5}, {"since": "2075-13-45"}, {"since": "2099-01-01"}, {"since": "2075-07-20", "char": "gate"}, {}])
def test_bad_requests_are_refused_and_nothing_is_queued(rig, gm, story, body):
    body = {"char": "rig", **body} if "char" not in body else body
    r = ask(rig, **body)
    assert r.status_code in (400, 403) and queue(gm) == []


def test_garbage_bodies_do_not_break_anything(rig, gm, story):
    for content in ("не json".encode(), b"[1,2]", b"null", b""):
        assert rig.post("/api/me/recap", content=content, headers={"Content-Type": "application/json"}).status_code < 500
    assert queue(gm) == []


# ---------------------------------------------------------------- ответ мастера

def test_answer_reaches_the_player_and_is_remembered(rig, gm, story, telegram_on):
    req = ask(rig, since=story["since"], char="rig").json()
    data = ok(answer(gm, req["id"], "  Вы пропустили налёт.\r\nГруз захвачен.  "))
    assert data["msg"] == "Пересказ отправлен: Риг" and data["state"]["recap_open"] == 0
    assert queue(gm) == []
    (row,) = mine(rig)
    assert row["status"] == "done" and row["text"] == "Вы пропустили налёт.\nГруз захвачен." and row["since"] == story["since"] and row["char"] == "rig"
    again = ask(rig, since=story["since"], char="rig").json()                                # тот же период и те же материалы: сразу из памяти, мастер не нужен
    assert again == {"text": row["text"], "cached": True, "events": 5, "since": story["since"]} and queue(gm) == []
    (note,) = [r for r in outbox.pending(RIG) if r["kind"] == "recap"]
    assert "подготовил пересказ" in note["text"] and note["section"] == "chron"


def test_ready_mark_stays_until_the_player_opens_the_list(rig, gate, gm, story):
    a = ask(rig, since=story["since"], char="rig").json()
    b = ask(gate, since=story["since"], char="gate").json()
    assert ok(rig.get("/api/state"))["recap_ready"] == 0                                     # просьба ещё не отвечена
    ok(answer(gm, a["id"]))
    ok(gm.post(f"/api/gm/recap/{b['id']}/decline", json={"note": "Позже"}))
    assert ok(rig.get("/api/state"))["recap_ready"] == 1 and ok(gate.get("/api/state"))["recap_ready"] == 1      # отказ тоже ответ
    assert ok(gm.get("/api/state"))["recap_ready"] == 0
    mine(gate)                                                                               # игрок открыл свой список: метка гаснет только у него
    assert ok(gate.get("/api/state"))["recap_ready"] == 0 and ok(rig.get("/api/state"))["recap_ready"] == 1
    mine(rig)
    assert ok(rig.get("/api/state"))["recap_ready"] == 0
    assert [i["status"] for i in mine(rig)] == ["done"]                                      # сам ответ остаётся в списке


def test_new_materials_mean_a_new_request(rig, gm, story):
    req = ask(rig, since=story["since"], char="rig").json()
    ok(answer(gm, req["id"]))
    ok(gm.post("/api/gm/items/past", json={"title": "Свежая новость", "from": "2075-07-30", "to": "2075-07-30", "note": "Появилась", "session": "Арка 1"}))
    again = ask(rig, since=story["since"], char="rig").json()
    assert again.get("pending") is True and again["id"] != req["id"] and "Свежая новость" in queue(gm)[0]["prompt"]


def test_players_do_not_see_each_others_requests_or_answers(rig, gate, gm, story):
    a = ask(rig, since=story["since"], char="rig").json()
    ask(gate, since=story["since"], char="gate")
    ok(answer(gm, a["id"], "Ответ только для Рига"))
    assert [i["status"] for i in mine(rig)] == ["done"] and mine(gate)[0]["status"] == "open"
    assert "Ответ только для Рига" not in json.dumps(mine(gate), ensure_ascii=False)
    assert "prompt" not in json.dumps(mine(rig)) and "hash" not in json.dumps(mine(rig))      # запрос целиком игроку не уходит


@pytest.mark.parametrize("text, message", [("", "Вставьте"), ("   \n ", "Вставьте"), (5, "Вставьте"), (None, "Вставьте"), (["a"], "Вставьте"), ("я" * 6001, "длиннее 6000")])
def test_bad_answers_are_refused_and_the_request_stays_open(rig, gm, story, text, message):
    req = ask(rig, since=story["since"], char="rig").json()
    r = gm.post(f"/api/gm/recap/{req['id']}/answer", json={"text": text})
    assert r.status_code == 400 and message in r.json()["detail"]
    assert [i["id"] for i in queue(gm)] == [req["id"]] and mine(rig)[0]["status"] == "open"


def test_answer_of_exactly_the_limit_is_taken_and_control_characters_are_dropped(rig, gm, story):
    req = ask(rig, since=story["since"], char="rig").json()
    ok(answer(gm, req["id"], "Я" * 5990 + "\x00\x01\x1f" + "я" * 10))
    assert mine(rig)[0]["text"] == "Я" * 5990 + "я" * 10


def test_answering_twice_or_a_missing_request(rig, gm, story):
    req = ask(rig, since=story["since"], char="rig").json()
    ok(answer(gm, req["id"], "Первый ответ"))
    r = answer(gm, req["id"], "Второй ответ")
    assert r.status_code == 409 and "уже ответили" in r.json()["detail"]
    assert mine(rig)[0]["text"] == "Первый ответ"
    assert answer(gm, 999999).status_code == 404
    assert gm.post(f"/api/gm/recap/{req['id']}/decline", json={"note": ""}).status_code == 409           # после ответа отказать уже нельзя
    assert gm.post("/api/gm/recap/abc/answer", json={"text": "x"}).status_code == 422


def test_decline_with_and_without_a_reason(rig, gate, gm, story, telegram_on):
    a = ask(rig, since=story["since"], char="rig").json()
    b = ask(gate, since=story["since"], char="gate").json()
    data = ok(gm.post(f"/api/gm/recap/{a['id']}/decline", json={"note": "  Давайте на игре, там расскажу.  "}))
    assert data["msg"] == "Просьба отклонена: Риг" and data["state"]["recap_open"] == 1
    ok(gm.post(f"/api/gm/recap/{b['id']}/decline", json={}))
    (row,) = mine(rig)
    assert row["status"] == "declined" and row["text"] == "Давайте на игре, там расскажу."
    assert mine(gate)[0]["status"] == "declined" and mine(gate)[0]["text"] == ""
    texts = [r["text"] for r in outbox.pending(RIG) if r["kind"] == "recap"]
    assert texts == ["Мастер пока не может подготовить пересказ. Давайте на игре, там расскажу."]
    assert [r["text"] for r in outbox.pending(GATE) if r["kind"] == "recap"] == ["Мастер пока не может подготовить пересказ."]
    assert ask(rig, since=story["since"], char="rig").json().get("pending") is True               # после отказа можно попросить снова
    long = gm.post(f"/api/gm/recap/{queue(gm)[0]['id']}/decline", json={"note": "я" * 301})
    assert long.status_code == 400 and "длиннее" in long.json()["detail"] and len(queue(gm)) == 1


# ---------------------------------------------------------------- кто что может

def test_permissions(rig, gate, gm, anon, story):
    req = ask(rig, since=story["since"], char="rig").json()
    for client in (rig, gate):                                                               # игрок не видит очередь и не отвечает
        assert client.get("/api/gm/recap").status_code == 403
        assert client.post(f"/api/gm/recap/{req['id']}/answer", json={"text": "подделка"}).status_code == 403
        assert client.post(f"/api/gm/recap/{req['id']}/decline", json={}).status_code == 403
    for r in (anon.get("/api/gm/recap"), anon.get("/api/me/recap/requests"), anon.post("/api/me/recap", json={"since": "2075-07-20"}),
              anon.post(f"/api/gm/recap/{req['id']}/answer", json={"text": "x"})):
        assert r.status_code == 401
    assert mine(rig)[0]["status"] == "open"
    r = ask(gm, since=story["since"], char="rig")                                            # мастер знает, что было: просить ему не у кого
    assert r.status_code == 403 and "Пересказ нужен игрокам" in r.json()["detail"]
    assert gm.get("/api/me/recap/requests").status_code == 403


def test_the_prompt_and_other_peoples_requests_are_never_in_the_state(rig, gate, gm, story):
    ask(rig, since=story["since"], char="rig")
    for client in (rig, gate, gm):
        text = client.get("/api/state").text
        assert "Персонаж: Риг" not in text and recap.SYSTEM[:40] not in text


def test_a_player_cannot_ask_for_somebody_elses_character(rig, gm, story):
    r = ask(rig, since=story["since"], char="gate")
    assert r.status_code == 403 and queue(gm) == []


# ---------------------------------------------------------------- лимиты

def test_per_day_limit_counts_replaced_requests_too(rig, gm, story, monkeypatch):
    monkeypatch.setattr(config, "RECAP_PER_DAY", 2)
    ok(ask(rig, since="2075-07-20", char="rig"))
    ok(ask(rig, since="2075-07-23", char="rig"))                                             # замена тоже считается: иначе можно засыпать мастера
    r = ask(rig, since="2075-07-25", char="rig")
    assert r.status_code == 429 and "не больше 2" in r.json()["detail"]
    assert len(queue(gm)) == 1 and queue(gm)[0]["since"] == "2075-07-23"
    assert ask(rig, since="2075-07-23", char="rig").json()["pending"] is True               # та же открытая просьба лимит не тратит


def test_burst_limit(rig, gm, story, monkeypatch):
    monkeypatch.setattr(recap, "BURST", 2)
    ok(ask(rig, since="2075-07-20", char="rig"))
    ok(ask(rig, since="2075-07-23", char="rig"))
    r = ask(rig, since="2075-07-25", char="rig")
    assert r.status_code == 429 and "Слишком часто" in r.json()["detail"]


def test_total_number_of_open_requests_is_capped(rig, gate, gm, story, monkeypatch):
    monkeypatch.setattr(recap, "OPEN_MAX", 1)
    ok(ask(rig, since="2075-07-20", char="rig"))
    r = ask(gate, since="2075-07-20", char="gate")
    assert r.status_code == 429 and "слишком много" in r.json()["detail"]
    assert ok(ask(rig, since="2075-07-23", char="rig"))["pending"] is True                  # у кого просьба уже есть, тот может её заменить
    assert len(queue(gm)) == 1


# ---------------------------------------------------------------- уведомления и уборка

def test_the_master_is_told_about_a_new_request(rig, gm, story, telegram_on):
    ask(rig, since=story["since"], char="rig")
    (row,) = [r for r in outbox.pending(GM) if r["kind"] == "recap"]
    assert "Риг" in row["text"] and "Что было раньше" in row["text"] and "панели мастера" in row["text"] and row["section"] == "gm"
    assert "Персонаж:" not in row["text"] and SECRET not in row["text"]                       # сам запрос в Telegram не уходит


def test_no_notifications_when_the_bot_is_off(rig, gm, story):
    ask(rig, since=story["since"], char="rig")
    ok(answer(gm, queue(gm)[0]["id"]))
    assert not [r for r in outbox.pending(GM) + outbox.pending(RIG) if r["kind"] == "recap"]


def test_old_requests_are_cleaned_up(rig, gm, story):
    import time
    ask(rig, since=story["since"], char="rig")
    db.conn().execute("UPDATE recap_requests SET created=?", (time.time() - 100 * 86400,))
    recap.purge_old()
    assert db.conn().execute("SELECT COUNT(*) FROM recap_requests").fetchone()[0] == 0


def test_table_is_part_of_the_schema():
    cols = [r["name"] for r in db.conn().execute("PRAGMA table_info(recap_requests)")]
    assert {"id", "tg_id", "char", "since", "prompt", "hash", "events", "status", "text", "created", "answered"} <= set(cols)
    assert db.schema_version() == db.LATEST >= 8
