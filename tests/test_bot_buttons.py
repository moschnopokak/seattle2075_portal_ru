"""Кнопки «Принять / Отклонить» в сообщениях бота: появление, приём нажатий через webhook, защита от чужих и устаревших нажатий."""
import json
import time
import urllib.error

import pytest

from app import db, notify, outbox, telegram_bot
from conftest import GATE, GM, HAG, RIG, STRANGER, login
from helpers import create, entry, find, ok, remove

SECRET_HEADER = "x-telegram-bot-api-secret-token"
URL = "/api/telegram/webhook"


class Telegram:
    """Подставной Telegram: запоминает вызовы Bot API."""

    def __init__(self):
        self.calls = []
        self.fail = None

    def __call__(self, method, payload):
        self.calls.append((method, payload))
        if self.fail:
            raise self.fail
        return {"ok": True, "result": {}}

    def of(self, method):
        return [p for m, p in self.calls if m == method]


@pytest.fixture
def tg(monkeypatch):
    fake = Telegram()
    monkeypatch.setattr(notify, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(notify, "NOTIFY_DM", True)
    monkeypatch.setattr(notify, "TG_WEBHOOK", True)
    monkeypatch.setattr(notify, "SITE_URL", "https://portal.example.test")
    monkeypatch.setattr(notify, "_call", fake)
    return fake


@pytest.fixture(autouse=True)
def tidy(started):
    for table in ("outbox", "user_prefs", "invite_clock"):
        db.conn().execute(f"DELETE FROM {table}")
    yield
    for table in ("outbox", "user_prefs", "invite_clock"):
        db.conn().execute(f"DELETE FROM {table}")


@pytest.fixture
def anon(started):
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def hook(client, update, secret=None, **kw):
    headers = {SECRET_HEADER: telegram_bot.secret() if secret is None else secret}
    return client.post(URL, json=update, headers=headers, **kw)


def press(data, who=RIG, message=None, username=""):
    cq = {"id": "cq1", "from": {"id": who, "username": username}, "data": data}
    if message is not None:
        cq["message"] = message
    return {"update_id": 1, "callback_query": cq}


def message_with(*rows, chat=RIG, mid=77):
    return {"message_id": mid, "chat": {"id": chat}, "reply_markup": {"inline_keyboard": [list(r) for r in rows]}}


def invite_rows(tg_id):
    return [r for r in outbox.pending(tg_id) if r["kind"] == "invite"]


def buttons_of(row):
    return json.loads(row["buttons"]) if row["buttons"] else []


@pytest.fixture
def invitation(gate, gm):
    e = create(gate, char="gate", title="Встреча у моста", who=["rig"])
    yield e
    remove(gm, e["id"])


# ---------------------------------------------------------------- кнопки под сообщением

def test_invitation_carries_accept_and_decline_buttons(tg, gate, gm):
    e = create(gate, char="gate", title="Встреча у моста", who=["rig"])
    try:
        (row,) = invite_rows(RIG)
        rows = buttons_of(row)
        assert [b[0]["callback_data"] for b in rows] == [f"e:y:{e['id']}:rig", f"e:n:{e['id']}:rig"]
        assert "Принять" in rows[0][0]["text"] and "Встреча у моста" in rows[0][0]["text"] and "Отклонить" in rows[1][0]["text"]
        assert all(len(b[0]["callback_data"].encode()) <= 64 for b in rows)
        assert invite_rows(GATE) == []                                             # автору приглашения кнопки не нужны
    finally:
        remove(gm, e["id"])


def test_buttons_follow_the_setting_and_https(monkeypatch, gate, gm):
    monkeypatch.setattr(notify, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(notify, "NOTIFY_DM", True)
    monkeypatch.setattr(notify, "SITE_URL", "https://portal.example.test")
    for setting, site in ((False, "https://portal.example.test"), (True, "http://portal.example.test")):
        monkeypatch.setattr(notify, "TG_WEBHOOK", setting)
        monkeypatch.setattr(notify, "SITE_URL", site)
        db.conn().execute("DELETE FROM outbox")
        e = create(gate, char="gate", title="Без кнопок", who=["rig"])
        try:
            assert invite_rows(RIG) and buttons_of(invite_rows(RIG)[0]) == []
        finally:
            remove(gm, e["id"])


def test_long_titles_are_shortened_and_oversized_callbacks_are_dropped(tg):
    long_title = "Очень длинное название встречи " * 5
    rows = notify.invite_buttons({"id": "abc123abc123", "title": long_title}, "rig")
    assert all(len(b[0]["text"]) < 60 for b in rows) and rows[0][0]["text"].endswith("…")
    assert notify.invite_buttons({"id": "abc123abc123", "title": "Т"}, "персонаж" * 10) is None   # не влезает в 64 байта


def test_growth_request_gives_the_gm_confirm_and_reject_buttons(tg, rig, gm):
    g = ok(rig.post("/api/entries", json=entry(type="grow", char="rig", title="Навык с кнопками", who=["rig"], goal="цель", effect="2075-08-05")))
    gid = next(e["id"] for e in g["state"]["entries"] if e["title"] == "Навык с кнопками")
    try:
        (row,) = [r for r in outbox.pending(GM) if r["kind"] == "grow"]
        assert [b[0]["callback_data"] for b in buttons_of(row)] == [f"e:ok:{gid}", f"e:no:{gid}"]
    finally:
        remove(gm, gid)


def test_buttons_are_added_under_the_portal_button_and_merged_messages_keep_all_of_them(tg, gate, gm):
    es = [create(gate, char="gate", title=f"Встреча {i}", who=["rig"]) for i in range(3)]
    try:
        sent = []
        outbox.flush(lambda tg_id, text, section, buttons: sent.append((tg_id, buttons)), time.time() + 10)
        (_, buttons), = [s for s in sent if s[0] == RIG]
        assert len(buttons) == 6 and buttons[0][0]["callback_data"].startswith("e:y:")
    finally:
        for e in es:
            remove(gm, e["id"])


# ---------------------------------------------------------------- webhook: доступ

def test_webhook_is_closed_when_the_feature_is_off(monkeypatch, anon):
    monkeypatch.setattr(notify, "TG_WEBHOOK", False)
    assert hook(anon, {"update_id": 1}).status_code == 404


def test_webhook_requires_the_secret(tg, anon):
    assert anon.post(URL, json={"update_id": 1}).status_code == 403                           # без заголовка
    assert anon.post(URL, json={"update_id": 1}, headers={SECRET_HEADER: b"\xff\xfe\xd0"}).status_code == 403   # не ASCII не роняет сервер
    assert hook(anon, {"update_id": 1}, secret="x" * 100).status_code == 403
    assert hook(anon, {"update_id": 1}).status_code == 200
    assert tg.calls == []


def test_webhook_survives_garbage(tg, anon):
    for body in ([], "строка", 5, {"callback_query": "x"}, {"callback_query": {"data": 5}}, {"message": {"text": "/start"}}):
        assert hook(anon, body).status_code == 200, body
    assert anon.post(URL, content=b"null", headers={SECRET_HEADER: telegram_bot.secret(), "content-type": "application/json"}).status_code == 200
    assert anon.post(URL, content="{не json".encode(), headers={SECRET_HEADER: telegram_bot.secret(), "content-type": "application/json"}).status_code == 400
    big = anon.post(URL, content=b"[" + b"0," * 40000 + b"0]", headers={SECRET_HEADER: telegram_bot.secret(), "content-type": "application/json"})
    assert big.status_code == 413


def test_secret_is_stable_and_fits_telegram_rules():
    s = telegram_bot.secret()
    assert s == telegram_bot.secret() and 1 <= len(s) <= 256 and all(c in "0123456789abcdef" for c in s)


# ---------------------------------------------------------------- webhook: нажатия

def test_accepting_from_the_message_answers_the_invitation_and_removes_its_buttons(tg, anon, invitation, gate):
    other = [{"text": "✅ Принять: Другая", "callback_data": "e:y:другая:rig"}]
    msg = message_with([{"text": "✅ Принять: Встреча у моста", "callback_data": f"e:y:{invitation['id']}:rig"}],
                       [{"text": "❌ Отклонить: Встреча у моста", "callback_data": f"e:n:{invitation['id']}:rig"}],
                       other, [{"text": "Открыть портал", "web_app": {"url": "https://portal.example.test/"}}])
    assert hook(anon, press(f"e:y:{invitation['id']}:rig", message=msg)).status_code == 200
    state = ok(login(GATE).get("/api/state"))
    e = find(state, invitation["id"])
    assert e["answers"]["rig"] == "да" and e["status"] == "ok"
    (answer,) = tg.of("answerCallbackQuery")
    assert answer["callback_query_id"] == "cq1" and "принято" in answer["text"] and answer["show_alert"] is False
    (edit,) = tg.of("editMessageReplyMarkup")
    assert edit["chat_id"] == RIG and edit["message_id"] == 77
    left = [b.get("callback_data") or b["text"] for r in edit["reply_markup"]["inline_keyboard"] for b in r]
    assert left == ["e:y:другая:rig", "Открыть портал"]                                        # убраны только кнопки этой записи
    assert any(r["kind"] == "answer" for r in outbox.pending(GATE))                            # автору ушло уведомление об ответе


def test_declining_marks_the_entry_for_rescheduling(tg, anon, invitation):
    assert hook(anon, press(f"e:n:{invitation['id']}:rig")).status_code == 200
    e = find(ok(login(GATE).get("/api/state")), invitation["id"])
    assert e["answers"]["rig"] == "нет" and e["status"] == "resched"
    assert "отклонено" in tg.of("answerCallbackQuery")[0]["text"]
    assert tg.of("editMessageReplyMarkup") == []                                               # сообщения в запросе не было: править нечего


def test_someone_elses_button_does_nothing(tg, anon, invitation):
    msg = message_with([{"text": "x", "callback_data": f"e:y:{invitation['id']}:rig"}], chat=HAG)
    hook(anon, press(f"e:y:{invitation['id']}:rig", who=HAG, message=msg))
    e = find(ok(login(GATE).get("/api/state")), invitation["id"])
    assert e["answers"]["rig"] == "ждёт"
    (answer,) = tg.of("answerCallbackQuery")
    assert answer["show_alert"] is True and "другим игроком" in answer["text"]
    assert tg.of("editMessageReplyMarkup") == []                                               # чужие кнопки не трогаем


def test_stranger_outside_the_list_is_refused(tg, anon, invitation):
    hook(anon, press(f"e:y:{invitation['id']}:rig", who=STRANGER))
    assert find(ok(login(GATE).get("/api/state")), invitation["id"])["answers"]["rig"] == "ждёт"
    assert "нет в списке" in tg.of("answerCallbackQuery")[0]["text"]


def test_a_stale_button_reports_it_and_disappears(tg, anon, invitation, rig):
    ok(rig.post(f"/api/entries/{invitation['id']}/act", json={"act": "ans", "char": "rig", "v": "да"}))      # уже ответил на портале
    msg = message_with([{"text": "x", "callback_data": f"e:n:{invitation['id']}:rig"}])
    hook(anon, press(f"e:n:{invitation['id']}:rig", message=msg))
    assert find(ok(login(GATE).get("/api/state")), invitation["id"])["answers"]["rig"] == "да"      # повторное нажатие ничего не сломало
    (answer,) = tg.of("answerCallbackQuery")
    assert answer["show_alert"] is True and "не требуется" in answer["text"]
    assert tg.of("editMessageReplyMarkup")[0]["reply_markup"] == {"inline_keyboard": []}


def test_a_deleted_entry_is_reported(tg, anon, invitation, gate):
    ok(gate.post(f"/api/entries/{invitation['id']}/act", json={"act": "del", "char": "gate"}))
    hook(anon, press(f"e:y:{invitation['id']}:rig"))
    assert "не найдена" in tg.of("answerCallbackQuery")[0]["text"]


def test_gm_confirms_and_rejects_growth_from_the_message(tg, anon, rig, gm):
    ids = []
    for title in ("Навык раз", "Навык два"):
        g = ok(rig.post("/api/entries", json=entry(type="grow", char="rig", title=title, who=["rig"], goal="цель", effect="2075-08-05")))
        ids.append(next(e["id"] for e in g["state"]["entries"] if e["title"] == title))
    try:
        hook(anon, press(f"e:ok:{ids[0]}", who=GM))
        hook(anon, press(f"e:no:{ids[1]}", who=GM))
        state = {e["id"]: e for e in ok(gm.get("/api/state"))["entries"]}
        assert state[ids[0]]["status"] == "ok" and state[ids[1]]["status"] == "rejected"
        hook(anon, press(f"e:ok:{ids[1]}", who=GM))                                              # уже рассмотрена
        assert "уже рассмотрена" in tg.of("answerCallbackQuery")[-1]["text"]
        hook(anon, press(f"e:ok:{ids[0]}", who=RIG))                                             # игрок не может подтверждать
        assert "только мастер" in tg.of("answerCallbackQuery")[-1]["text"].lower()
    finally:
        for i in ids:
            remove(gm, i)


@pytest.mark.parametrize("data", ["", "x", "e:y", "e:y:", "e:y:abc", "e:zz:abc:rig", "a:y:abc:rig", None, 5])
def test_unknown_buttons_are_politely_refused(tg, anon, data):
    assert hook(anon, press(data)).status_code == 200
    (answer,) = tg.of("answerCallbackQuery")
    assert answer["show_alert"] is True and "больше не работает" in answer["text"]
    assert tg.of("editMessageReplyMarkup") == []


def test_telegram_failures_do_not_break_the_webhook(tg, anon, invitation):
    tg.fail = urllib.error.HTTPError("https://api.telegram.org/x", 400, "Bad Request", {}, None)
    assert hook(anon, press(f"e:y:{invitation['id']}:rig")).status_code == 200
    assert find(ok(login(GATE).get("/api/state")), invitation["id"])["answers"]["rig"] == "да"      # ответ записан, даже если Telegram ответил ошибкой
    tg.fail = OSError("нет сети")
    assert hook(anon, press(f"e:y:{invitation['id']}:rig")).status_code == 200


def test_username_only_player_can_press(tg, anon, invitation, monkeypatch):
    """Человека могут опознавать по @имени, а не по числовому ID: нажатие работает и так."""
    from app import config
    real = config.resolve
    seen = []
    with monkeypatch.context() as m:                                           # патч только на время нажатия, не на уборку фикстур
        m.setattr(config, "resolve", lambda tg_id, username: (seen.append((tg_id, username)), real(RIG, ""))[1])
        hook(anon, press(f"e:y:{invitation['id']}:rig", who=555000, username="someone"))
    assert seen == [(555000, "someone")]
    assert find(ok(login(GATE).get("/api/state")), invitation["id"])["answers"]["rig"] == "да"


# ---------------------------------------------------------------- регистрация webhook

def test_register_sends_url_secret_and_only_button_updates(tg):
    telegram_bot.register()
    (payload,) = tg.of("setWebhook")
    assert payload["url"] == "https://portal.example.test/api/telegram/webhook"
    assert payload["secret_token"] == telegram_bot.secret() and payload["allowed_updates"] == ["callback_query"]


def test_command_line(tg, capsys):
    assert telegram_bot.main(["set"]) == 0 and tg.of("setWebhook")
    assert telegram_bot.main(["info"]) == 0 and tg.of("getWebhookInfo")
    assert telegram_bot.main(["delete"]) == 0 and tg.of("deleteWebhook")
    assert telegram_bot.main(["что-то"]) == 1
    tg.fail = OSError("нет сети")
    assert telegram_bot.main(["info"]) == 1 and "Нет связи" in capsys.readouterr().out


def test_command_line_without_a_token_or_https(monkeypatch, capsys):
    monkeypatch.setattr(notify, "BOT_TOKEN", "")
    assert telegram_bot.main(["set"]) == 1
    monkeypatch.setattr(notify, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(notify, "SITE_URL", "http://portal.example.test")
    assert telegram_bot.main(["set"]) == 1 and "https" in capsys.readouterr().out
