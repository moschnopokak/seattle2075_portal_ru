"""Очередь личных уведомлений: тихие часы, сводка, склейка сообщений, повторы, настройки, планировщик."""
import json
import threading
import time
from datetime import datetime, timezone

import pytest

from app import db, notify, outbox, scheduler
from conftest import GATE, GM, HAG, RIG, login
from helpers import create, entry, ok, remove

MSK = "Europe/Moscow"        # UTC+3 без перехода на летнее время


def utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp()


@pytest.fixture(autouse=True)
def clean_outbox(started):
    db.conn().execute("DELETE FROM outbox")
    db.conn().execute("DELETE FROM user_prefs")
    yield
    db.conn().execute("DELETE FROM outbox")
    db.conn().execute("DELETE FROM user_prefs")


class Sender:
    def __init__(self):
        self.sent = []

    def __call__(self, tg_id, text, section, buttons):
        self.sent.append({"to": tg_id, "text": text, "section": section, "buttons": buttons})


def prefs_for(tg, **kw):
    base = {"tz": MSK, "quiet_on": 0, "quiet_from": 23, "quiet_to": 8, "digest_on": 0, "digest_hour": 9, "chat_notify": 1}
    base.update(kw)
    return outbox.save_prefs(tg, base)


# ---------------------------------------------------------------- настройки

def test_defaults_and_roundtrip():
    p = outbox.prefs(555)
    assert p == outbox.defaults() and p["chat_notify"] == 1 and p["quiet_on"] == 0
    saved = prefs_for(555, quiet_on=1, quiet_from=22, quiet_to=7, digest_on=1, digest_hour=10, chat_notify=False)
    assert saved["tz"] == MSK and saved["quiet_on"] == 1 and (saved["quiet_from"], saved["quiet_to"]) == (22, 7)
    assert saved["digest_on"] == 1 and saved["digest_hour"] == 10 and saved["chat_notify"] == 0
    assert outbox.prefs(556) == outbox.defaults()                        # у другого человека свои


@pytest.mark.parametrize("bad", [
    {"tz": "Mars/Base"}, {"tz": "../etc/passwd"}, {"tz": "x" * 200}, {"tz": "Europe/Moscow\nX"},
    {"quiet_from": 24}, {"quiet_from": -1}, {"quiet_to": "утро"}, {"quiet_on": 1, "quiet_from": 5, "quiet_to": 5},
    {"digest_hour": 25}, {"digest_hour": None},
])
def test_invalid_prefs_are_rejected(bad):
    with pytest.raises(ValueError):
        prefs_for(557, **bad)
    assert outbox.prefs(557) == outbox.defaults()                        # ничего не сохранилось
    with pytest.raises(ValueError):
        outbox.save_prefs(557, ["не", "словарь"])


def test_quiet_hours_move_sending_to_their_end():
    p = prefs_for(1, quiet_on=1, quiet_from=23, quiet_to=8)
    inside = utc(2026, 6, 15, 20, 0)                                      # 23:00 по Москве
    assert outbox.next_allowed(p, inside) == utc(2026, 6, 16, 5, 0)       # 08:00 по Москве на следующий день
    after_midnight = utc(2026, 6, 15, 22, 30)                             # 01:30 по Москве
    assert outbox.next_allowed(p, after_midnight) == utc(2026, 6, 16, 5, 0)
    outside = utc(2026, 6, 15, 5, 30)                                     # 08:30 по Москве
    assert outbox.next_allowed(p, outside) == outside
    boundary = utc(2026, 6, 15, 5, 0)                                     # ровно 08:00: тихие часы уже кончились
    assert outbox.next_allowed(p, boundary) == boundary


def test_quiet_window_inside_one_day_and_other_time_zones():
    day = prefs_for(2, quiet_on=1, quiet_from=13, quiet_to=15)
    assert outbox.next_allowed(day, utc(2026, 6, 15, 11, 0)) == utc(2026, 6, 15, 12, 0)      # 14:00 по Москве, конец в 15:00
    assert outbox.next_allowed(day, utc(2026, 6, 15, 8, 0)) == utc(2026, 6, 15, 8, 0)
    tokyo = prefs_for(3, tz="Asia/Tokyo", quiet_on=1, quiet_from=22, quiet_to=6)                # UTC+9
    assert outbox.next_allowed(tokyo, utc(2026, 6, 15, 14, 0)) == utc(2026, 6, 15, 21, 0)       # 23:00 по Токио, конец 06:00 это 21:00 UTC


def test_daylight_saving_does_not_shift_the_local_hour():
    p = prefs_for(4, tz="America/New_York", quiet_on=1, quiet_from=23, quiet_to=8)
    for now in (utc(2026, 3, 8, 5, 0), utc(2026, 11, 1, 4, 30)):                                # ночи перевода часов
        end = datetime.fromtimestamp(outbox.next_allowed(p, now), outbox.zone("America/New_York"))
        assert (end.hour, end.minute) == (8, 0)


def test_digest_goes_at_the_chosen_local_hour_and_beats_quiet_hours():
    p = prefs_for(5, digest_on=1, digest_hour=9, quiet_on=1, quiet_from=23, quiet_to=8)
    assert outbox.next_allowed(p, utc(2026, 6, 15, 5, 0)) == utc(2026, 6, 15, 6, 0)      # 08:00 по Москве: сводка в 09:00 сегодня
    assert outbox.next_allowed(p, utc(2026, 6, 15, 6, 0)) == utc(2026, 6, 16, 6, 0)      # ровно 09:00: следующая завтра
    assert outbox.next_allowed(p, utc(2026, 6, 15, 12, 0)) == utc(2026, 6, 16, 6, 0)


# ---------------------------------------------------------------- очередь

def test_single_event_is_sent_as_is_and_removed():
    now = utc(2026, 6, 15, 12, 0)
    outbox.enqueue(10, "invite", "Риг приглашает в запись «Встреча»", "now", [[{"text": "Принять", "callback_data": "a"}]], now=now)
    sender = Sender()
    assert outbox.flush(sender, now) == 1
    assert sender.sent == [{"to": 10, "text": "Риг приглашает в запись «Встреча»", "section": "now",
                            "buttons": [[{"text": "Принять", "callback_data": "a"}]]}]
    assert outbox.pending() == [] and outbox.flush(sender, now + 100) == 0


def test_several_events_for_one_person_become_one_message():
    now = utc(2026, 6, 15, 12, 0)
    for text in ("Первое", "Второе", "Третье"):
        outbox.enqueue(11, "event", text, "now", now=now)
    outbox.enqueue(12, "event", "Другому человеку", "now", now=now)
    sender = Sender()
    assert outbox.flush(sender, now) == 2                                  # два получателя, два сообщения
    mine = next(m for m in sender.sent if m["to"] == 11)["text"]
    assert mine.startswith("Новое на портале (3):") and mine.count("•") == 3 and "Второе" in mine
    assert next(m for m in sender.sent if m["to"] == 12)["text"] == "Другому человеку"


def test_chat_messages_are_glued_and_wait_for_the_window():
    now = utc(2026, 6, 15, 12, 0)
    for i, who in enumerate(("Риг", "Гейт", "Риг"), 1):
        outbox.enqueue(13, "chat", "", "now", key="chat:e1", meta={"title": "Дело", "last": f"{who}: сообщение {i}"}, delay=300, now=now + i)
    rows = outbox.pending(13)
    assert len(rows) == 1 and rows[0]["count"] == 3
    sender = Sender()
    assert outbox.flush(sender, now + 100) == 0                            # окно склейки ещё не прошло
    assert outbox.flush(sender, now + 301) == 1
    text = sender.sent[0]["text"]
    assert text == "Обсуждение «Дело»: 3 новых сообщения\nПоследнее: Риг: сообщение 3"
    # после отправки новое сообщение начинает новую склейку
    outbox.enqueue(13, "chat", "", "now", key="chat:e1", meta={"title": "Дело", "last": "Гейт: ещё"}, delay=300, now=now + 400)
    assert outbox.pending(13)[0]["count"] == 1


def test_different_discussions_are_glued_separately_but_sent_together():
    now = utc(2026, 6, 15, 12, 0)
    for key, title in (("chat:a", "Дело А"), ("chat:b", "Дело Б")):
        outbox.enqueue(14, "chat", "", "now", key=key, meta={"title": title, "last": "Риг: привет"}, delay=60, now=now)
        outbox.enqueue(14, "chat", "", "now", key=key, meta={"title": title, "last": "Риг: ещё"}, delay=60, now=now)
    sender = Sender()
    assert outbox.flush(sender, now + 61) == 1
    text = sender.sent[0]["text"]
    assert "«Дело А»: 2 новых сообщения" in text and "«Дело Б»: 2 новых сообщения" in text and text.startswith("Новое на портале (2):")


@pytest.mark.parametrize("n,word", [(1, "новое сообщение"), (2, "новых сообщения"), (4, "новых сообщения"), (5, "новых сообщений"),
                                    (11, "новых сообщений"), (21, "новое сообщение"), (22, "новых сообщения")])
def test_chat_message_plural_forms(n, word):
    now = utc(2026, 6, 15, 12, 0)
    for _ in range(n):
        outbox.enqueue(15, "chat", "", "now", key="chat:p", meta={"title": "Т", "last": "А: б"}, delay=0, now=now)
    sender = Sender()
    outbox.flush(sender, now)
    assert f"{n} {word}" in sender.sent[0]["text"]


def test_chat_notifications_can_be_turned_off():
    prefs_for(16, chat_notify=False)
    assert outbox.enqueue(16, "chat", "", "now", key="chat:x", meta={"title": "Т"}, delay=0) is None
    assert outbox.enqueue(16, "invite", "Приглашение", "now") is not None             # остальное приходит


def test_quiet_hours_hold_everything_and_deliver_one_morning_message():
    prefs_for(17, quiet_on=1, quiet_from=23, quiet_to=8)
    night = utc(2026, 6, 15, 20, 30)                                                   # 23:30 по Москве
    for text in ("Приглашение А", "Приглашение Б", "Ответ В"):
        outbox.enqueue(17, "event", text, "now", now=night)
    sender = Sender()
    assert outbox.flush(sender, utc(2026, 6, 15, 23, 0)) == 0                          # 02:00 по Москве
    assert outbox.flush(sender, utc(2026, 6, 16, 4, 59)) == 0                          # 07:59
    assert outbox.flush(sender, utc(2026, 6, 16, 5, 1)) == 1                           # 08:01
    assert len(sender.sent) == 1 and sender.sent[0]["text"].startswith("Новое на портале (3):")


def test_digest_mode_collects_the_day_into_one_message():
    prefs_for(18, digest_on=1, digest_hour=9)
    for hour in (10, 13, 16):                                                          # по Москве, после сводки этого дня
        outbox.enqueue(18, "event", f"Событие в {hour}", "now", now=utc(2026, 6, 15, hour - 3, 0))
    sender = Sender()
    assert outbox.flush(sender, utc(2026, 6, 15, 20, 0)) == 0                          # 23:00: сводка завтра
    assert outbox.flush(sender, utc(2026, 6, 16, 6, 0)) == 1                           # 09:00 по Москве
    assert sender.sent[0]["text"].count("•") == 3


def test_buttons_are_combined_and_capped_and_text_stays_under_the_limit():
    now = utc(2026, 6, 15, 12, 0)
    for i in range(12):
        outbox.enqueue(19, "invite", f"Приглашение номер {i} " + "очень длинное " * 40, "now", [[{"text": f"Принять {i}", "callback_data": f"a{i}"}]], now=now)
    sender = Sender()
    outbox.flush(sender, now)
    msg = sender.sent[0]
    assert len(msg["buttons"]) == outbox.MAX_BUTTON_ROWS
    assert len(msg["text"]) <= 4000 and "…и ещё" in msg["text"]


def test_section_of_a_merged_message():
    now = utc(2026, 6, 15, 12, 0)
    outbox.enqueue(20, "event", "А", "cal", now=now)
    outbox.enqueue(20, "event", "Б", "cal", now=now)
    outbox.enqueue(21, "event", "А", "cal", now=now)
    outbox.enqueue(21, "event", "Б", "handouts", now=now)
    sender = Sender()
    outbox.flush(sender, now)
    sections = {m["to"]: m["section"] for m in sender.sent}
    assert sections == {20: "cal", 21: "now"}                      # одинаковые разделы сохраняются, разные открывают «Сегодня»


# ---------------------------------------------------------------- сбои доставки

class Failing:
    def __init__(self, exc):
        self.exc, self.calls = exc, 0

    def __call__(self, *a):
        self.calls += 1
        raise self.exc


def test_blocked_bot_drops_the_notification():
    now = utc(2026, 6, 15, 12, 0)
    outbox.enqueue(30, "event", "Тест", "now", now=now)
    send = Failing(notify.TelegramError(403, '{"description":"Forbidden: bot was blocked by the user"}'))
    assert outbox.flush(send, now) == 0 and outbox.pending(30) == []     # писать некуда: больше не пытаемся
    outbox.enqueue(30, "event", "Тест 2", "now", now=now)
    assert outbox.flush(Failing(notify.TelegramError(400, "chat not found")), now) == 0 and outbox.pending(30) == []


def test_temporary_failures_are_retried_with_backoff_then_dropped():
    now = utc(2026, 6, 15, 12, 0)
    outbox.enqueue(31, "event", "Тест", "now", now=now)
    send = Failing(OSError("сеть недоступна"))
    outbox.flush(send, now)
    row = outbox.pending(31)[0]
    assert row["attempts"] == 1 and row["send_after"] == now + 60
    assert outbox.flush(send, now + 30) == 0 and send.calls == 1                       # ещё рано
    outbox.flush(send, now + 61)
    assert outbox.pending(31)[0]["attempts"] == 2 and outbox.pending(31)[0]["send_after"] == now + 61 + 120
    outbox.flush(send, now + 61 + 121)
    assert outbox.pending(31) == []                                                    # после третьей неудачи снимается


def test_telegram_flood_limit_respects_retry_after_and_then_succeeds():
    now = utc(2026, 6, 15, 12, 0)
    outbox.enqueue(32, "event", "Тест", "now", now=now)
    outbox.flush(Failing(notify.TelegramError(429, "Too Many Requests", retry_after=45)), now)
    assert outbox.pending(32)[0]["send_after"] == now + 45
    sender = Sender()
    assert outbox.flush(sender, now + 46) == 1 and sender.sent and outbox.pending(32) == []


def test_stale_notifications_are_purged():
    now = utc(2026, 6, 15, 12, 0)
    outbox.enqueue(33, "event", "Старое", "now", delay=10 ** 9, now=now - 5 * 86400)
    outbox.enqueue(33, "event", "Свежее", "now", delay=10 ** 9, now=now)
    assert outbox.purge_stale(3, now) == 1 and [r["text"] for r in outbox.pending(33)] == ["Свежее"]


# ---------------------------------------------------------------- связь с порталом

@pytest.fixture
def telegram_on(monkeypatch):
    monkeypatch.setattr(notify, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(notify, "NOTIFY_DM", True)


def rows(tg):
    return outbox.pending(tg)


def test_discussion_messages_notify_participants_and_gm_but_not_the_author(telegram_on, gm, gate, rig):
    e = create(gate, char="gate", title="Дело с обсуждением", who=["rig"])
    try:
        db.conn().execute("DELETE FROM outbox")
        ok(rig.post(f"/api/entries/{e['id']}/messages", json={"char": "rig", "text": "Привет, давай встретимся?"}))
        assert [r["kind"] for r in rows(GATE)] == ["chat"] and [r["kind"] for r in rows(GM)] == ["chat"]
        assert rows(RIG) == [] and rows(HAG) == []                      # автор и посторонний ничего не получают
        ok(rig.post(f"/api/entries/{e['id']}/messages", json={"char": "rig", "text": "И ещё одно"}))
        assert len(rows(GATE)) == 1 and rows(GATE)[0]["count"] == 2     # склеилось
        meta = json.loads(rows(GATE)[0]["meta"])
        assert meta["title"] == "Дело с обсуждением" and meta["last"] == "Риг: И ещё одно"
        sender = Sender()
        outbox.flush(sender, time.time() + 400)
        gate_msg = next(m for m in sender.sent if m["to"] == GATE)["text"]
        assert "2 новых сообщения" in gate_msg and "Риг: И ещё одно" in gate_msg
        # мастер пишет в обсуждение: участники получают, мастер нет
        db.conn().execute("DELETE FROM outbox")
        ok(gm.post(f"/api/entries/{e['id']}/messages", json={"text": "Мастер здесь"}))
        assert {t for t in (GATE, RIG, GM, HAG) if rows(t)} == {GATE, RIG}
    finally:
        remove(gm, e["id"])


def test_long_message_preview_is_trimmed(telegram_on, gm, gate, rig):
    e = create(gate, char="gate", title="Длинное", who=["rig"])
    try:
        db.conn().execute("DELETE FROM outbox")
        ok(rig.post(f"/api/entries/{e['id']}/messages", json={"char": "rig", "text": "я" * 1500}))
        assert len(json.loads(rows(GATE)[0]["meta"])["last"]) <= 160
    finally:
        remove(gm, e["id"])


def test_a_player_can_mute_discussions(telegram_on, gm, gate, rig):
    prefs_for(GATE, chat_notify=False)
    e = create(gate, char="gate", title="Тихое дело", who=["rig"])
    try:
        db.conn().execute("DELETE FROM outbox")
        ok(rig.post(f"/api/entries/{e['id']}/messages", json={"char": "rig", "text": "привет"}))
        assert rows(GATE) == [] and len(rows(GM)) == 1
    finally:
        remove(gm, e["id"])


def test_invites_and_growth_requests_are_queued_with_their_kinds(telegram_on, gm, gate, rig):
    db.conn().execute("DELETE FROM outbox")
    e = create(gate, char="gate", title="Приглашение в очередь", who=["rig"])
    g = ok(rig.post("/api/entries", json=entry(type="grow", char="rig", title="Навык в очередь", who=["rig"], goal="цель", effect="2075-08-05")))
    gid = next(x["id"] for x in g["state"]["entries"] if x["title"] == "Навык в очередь")
    try:
        assert [r["kind"] for r in rows(RIG)] == ["invite"] and rows(RIG)[0]["text"].startswith("Игрок Гейта") is False
        assert "приглашает в запись «Приглашение в очередь»" in rows(RIG)[0]["text"]
        assert [r["kind"] for r in rows(GM)] == ["grow"]
    finally:
        remove(gm, e["id"])
        remove(gm, gid)


def test_nothing_is_queued_when_notifications_are_off(gm, gate, rig):
    db.conn().execute("DELETE FROM outbox")
    e = create(gate, char="gate", title="Без уведомлений", who=["rig"])
    ok(rig.post(f"/api/entries/{e['id']}/messages", json={"char": "rig", "text": "привет"}))
    assert outbox.pending() == []
    remove(gm, e["id"])


# ---------------------------------------------------------------- API настроек

def test_prefs_api_for_players_and_gm(gm, rig, anon):
    assert anon.get("/api/me/prefs").status_code == 401
    r = rig.get("/api/me/prefs").json()
    assert r["prefs"] == outbox.defaults() and r["dm"] is False and r["chat_minutes"] >= 1
    saved = ok(rig.post("/api/me/prefs", json={"tz": MSK, "quiet_on": True, "quiet_from": 22, "quiet_to": 7, "digest_on": False,
                                                 "digest_hour": 9, "chat_notify": False}))["prefs"]
    assert saved["quiet_on"] == 1 and saved["tz"] == MSK and saved["chat_notify"] == 0
    assert rig.get("/api/me/prefs").json()["prefs"]["quiet_from"] == 22
    assert gm.get("/api/me/prefs").json()["prefs"] == outbox.defaults()          # у мастера свои
    assert rig.post("/api/me/prefs", json={"tz": "Nowhere/Land"}).status_code == 400
    assert rig.post("/api/me/prefs", json={"quiet_on": True, "quiet_from": 3, "quiet_to": 3}).status_code == 400


def test_test_message_reports_what_happened(rig, monkeypatch):
    assert rig.post("/api/me/prefs/test").status_code == 400                      # уведомления выключены в окружении тестов
    from app import config
    monkeypatch.setattr(config, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "NOTIFY_DM", True)
    got = []
    monkeypatch.setattr(notify, "deliver", lambda tg, text, section=None, buttons=None: got.append((tg, text)))
    assert rig.post("/api/me/prefs/test").status_code == 200 and got and got[0][0] == RIG
    monkeypatch.setattr(notify, "deliver", Failing(notify.TelegramError(403, "bot was blocked")))
    r = rig.post("/api/me/prefs/test")
    assert r.status_code == 502 and "нажмите «Запустить»" in r.json()["detail"]
    monkeypatch.setattr(notify, "deliver", Failing(OSError("нет сети")))
    assert rig.post("/api/me/prefs/test").status_code == 502


# ---------------------------------------------------------------- планировщик

def test_run_once_flushes_and_does_maintenance_hourly(started):
    now = utc(2026, 6, 15, 12, 0)
    scheduler._last_maintenance = 0.0
    outbox.enqueue(40, "event", "Из планировщика", "now", now=now)
    sender = Sender()
    done = scheduler.run_once(now, send=sender)
    assert done["sent"] == 1 and done["maintenance"] is True and sender.sent[0]["text"] == "Из планировщика"
    assert scheduler.run_once(now + 60, send=sender)["maintenance"] is False       # уборка не чаще раза в час
    assert scheduler.run_once(now + 3601, send=sender)["maintenance"] is True


def test_scheduler_thread_starts_runs_and_stops(monkeypatch):
    calls = threading.Event()
    monkeypatch.setattr(scheduler, "SCHEDULER", True)
    monkeypatch.setattr(scheduler, "TICK", 0.02)
    monkeypatch.setattr(scheduler, "run_once", lambda *a, **k: calls.set())
    assert scheduler.start() is True and scheduler.start() is False               # второй запуск ничего не делает
    assert calls.wait(2)
    scheduler.stop()
    assert scheduler._thread is None


def test_scheduler_survives_an_error_in_one_pass(monkeypatch):
    seen = {"n": 0}

    def flaky(*a, **k):
        seen["n"] += 1
        if seen["n"] == 1:
            raise RuntimeError("разовый сбой")
    monkeypatch.setattr(scheduler, "SCHEDULER", True)
    monkeypatch.setattr(scheduler, "TICK", 0.02)
    monkeypatch.setattr(scheduler, "run_once", flaky)
    scheduler.start()
    deadline = time.time() + 3
    while seen["n"] < 3 and time.time() < deadline:
        time.sleep(0.02)
    scheduler.stop()
    assert seen["n"] >= 3


def test_login_helper_is_available():
    assert login(GATE).get("/api/me/prefs").status_code == 200
