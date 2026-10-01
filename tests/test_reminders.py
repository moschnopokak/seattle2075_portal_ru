"""Напоминания о неотвеченных приглашениях: когда уходят, когда нет, сколько раз, уважают ли настройки и тихие часы."""
import time

import pytest

from app import db, notify, outbox, reminders, scheduler
from conftest import GATE, MAX, RIG
from helpers import create, find, ok, remove

DAY = 86400
MSK = "Europe/Moscow"


@pytest.fixture(autouse=True)
def tidy(started, monkeypatch):
    monkeypatch.setattr(notify, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(notify, "NOTIFY_DM", True)
    monkeypatch.setattr(reminders, "REMIND_DAYS", 2)
    monkeypatch.setattr(reminders, "REMIND_MAX", 2)
    for table in ("outbox", "user_prefs", "invite_clock"):
        db.conn().execute(f"DELETE FROM {table}")
    yield
    for table in ("outbox", "user_prefs", "invite_clock"):
        db.conn().execute(f"DELETE FROM {table}")


@pytest.fixture
def invitation(gate, gm):
    """Гейт приглашает Рига; приглашение создано «сейчас»."""
    e = create(gate, char="gate", title="Встреча у моста", who=["rig"])
    db.conn().execute("DELETE FROM outbox")
    yield e
    remove(gm, e["id"])


def queued(tg):
    return [r for r in outbox.pending(tg) if r["kind"] == "remind"]


def test_no_reminder_before_the_delay_and_one_after(invitation):
    t0 = time.time()
    assert reminders.run(t0 + DAY) == 0 and queued(RIG) == []
    assert reminders.run(t0 + 2 * DAY + 60) == 1
    (row,) = queued(RIG)
    assert "Встреча у моста" in row["text"] and "Гейт" in row["text"] and "не ответили" in row["text"]
    assert queued(GATE) == []                                                    # автору ничего не приходит
    assert reminders.run(t0 + 2 * DAY + 120) == 0                                # сразу же повторно не пишет


def test_at_most_remind_max_times_and_interval_counts_from_the_last_one(invitation):
    t0 = time.time()
    assert reminders.run(t0 + 2 * DAY + 1) == 1
    assert reminders.run(t0 + 3 * DAY) == 0                                      # ещё не прошло 2 дня с прошлого напоминания
    assert reminders.run(t0 + 4 * DAY + 5) == 1
    assert len(queued(RIG)) == 2
    assert reminders.run(t0 + 30 * DAY) == 0                                     # потолок
    assert len(queued(RIG)) == 2


def test_answered_invitations_are_not_reminded(invitation, rig):
    ok(rig.post(f"/api/entries/{invitation['id']}/act", json={"act": "ans", "char": "rig", "v": "да"}))
    assert reminders.run(time.time() + 10 * DAY) == 0 and queued(RIG) == []


def test_declined_invitations_are_not_reminded_either(invitation, rig):
    ok(rig.post(f"/api/entries/{invitation['id']}/act", json={"act": "ans", "char": "rig", "v": "нет"}))
    assert reminders.run(time.time() + 10 * DAY) == 0


def test_closed_deleted_and_past_entries_are_left_alone(invitation, gm, gate):
    t = time.time() + 5 * DAY
    # дата записи прошла по игровому времени
    ok(gm.post("/api/gm/time", json={"date": "2075-09-01", "tod": "день"}))
    try:
        assert reminders.run(t) == 0
    finally:
        ok(gm.post("/api/gm/time", json={"date": "2075-08-01", "tod": "вечер"}))
    assert reminders.run(t) == 1                                                 # время вернули: запись снова актуальна
    db.conn().execute("DELETE FROM outbox")
    ok(gate.post(f"/api/entries/{invitation['id']}/act", json={"act": "del", "char": "gate"}))
    assert reminders.run(t + 10 * DAY) == 0
    assert db.conn().execute("SELECT COUNT(*) FROM invite_clock WHERE entry_id=?", (invitation["id"],)).fetchone()[0] == 0


def test_restore_from_trash_restarts_the_countdown(invitation, gm, gate):
    ok(gate.post(f"/api/entries/{invitation['id']}/act", json={"act": "del", "char": "gate"}))
    trash_id = next(t["id"] for t in ok(gm.get("/api/gm/trash"))["items"] if t["title"] == "Встреча у моста")
    ok(gm.post(f"/api/gm/trash/{trash_id}/restore"))
    assert find(ok(gm.get("/api/state")), invitation["id"])
    assert reminders.run(time.time() + 60) == 0                                  # отсчёт пошёл заново, сразу не пишет
    assert reminders.run(time.time() + 2 * DAY + 60) == 1


def test_moving_the_dates_asks_again_and_restarts_the_counter(invitation, gate, rig):
    ok(rig.post(f"/api/entries/{invitation['id']}/act", json={"act": "ans", "char": "rig", "v": "да"}))
    assert reminders.run(time.time() + 5 * DAY) == 0                              # ответил: напоминать не о чем
    db.conn().execute("UPDATE invite_clock SET asked=asked-?, last=last-?", (9 * DAY, 9 * DAY))     # приглашению «девять дней»
    body = {k: invitation[k] for k in ("type", "title", "from", "to", "tod", "who", "open", "where", "cond", "goal", "vis", "place")}
    body.update({"from": "2075-08-07", "to": "2075-08-07", "char": "gate"})
    ok(gate.post(f"/api/entries/{invitation['id']}/edit", json=body))             # даты сдвинуты: Рига спрашивают заново
    assert reminders.run(time.time() + 60) == 0                                   # отсчёт начался только что
    assert reminders.run(time.time() + 2 * DAY + 60) == 1
    assert queued(RIG)[0]["text"].count("7 августа") == 1                         # в напоминании новая дата


def test_old_invitation_without_a_clock_row_counts_from_creation(invitation):
    db.conn().execute("DELETE FROM invite_clock")                                # как будто запись создана до этой функции
    assert reminders.run(time.time() + 60) == 0
    assert reminders.run(time.time() + 2 * DAY + 60) == 1


def test_switched_off_per_person_and_globally(invitation, monkeypatch):
    outbox.save_prefs(RIG, {**outbox.defaults(), "remind": False})
    assert reminders.run(time.time() + 3 * DAY) == 1 and queued(RIG) == []       # отсчёт идёт, но человек отказался
    db.conn().execute("DELETE FROM invite_clock")
    outbox.save_prefs(RIG, {**outbox.defaults(), "remind": True})
    monkeypatch.setattr(reminders, "REMIND_DAYS", 0)
    assert reminders.run(time.time() + 30 * DAY) == 0 and queued(RIG) == []


def test_two_characters_of_one_player_get_one_message(gate, gm):
    e = create(gate, char="gate", title="Двое от одного игрока", who=["alice", "karu"])
    try:
        db.conn().execute("DELETE FROM outbox")
        assert reminders.run(time.time() + 3 * DAY) == 2
        assert len(queued(MAX)) == 1
    finally:
        remove(gm, e["id"])


def test_quiet_hours_postpone_the_reminder(invitation):
    outbox.save_prefs(RIG, {**outbox.defaults(), "tz": MSK, "quiet_on": 1, "quiet_from": 23, "quiet_to": 8})
    first = invitation["created"] + 3 * DAY
    midnight_msk = (int(first // DAY) + 1) * DAY + 21 * 3600                      # ближайшие 21:00 UTC, то есть 00:00 по Москве
    assert reminders.run(midnight_msk) == 1
    (row,) = queued(RIG)
    assert row["send_after"] == midnight_msk + 8 * 3600                           # уйдёт в 08:00 по Москве
    sent = []
    assert outbox.flush(lambda *a: sent.append(a), midnight_msk + 3600) == 0 and not sent
    assert outbox.flush(lambda *a: sent.append(a), midnight_msk + 8 * 3600) == 1 and len(sent) == 1


def test_scheduler_runs_reminders_and_flushes_them(invitation, monkeypatch):
    sent = []
    monkeypatch.setattr(scheduler, "_last_remind", 0.0)
    done = scheduler.run_once(now=time.time() + 3 * DAY, send=lambda tg, text, section, buttons: sent.append((tg, text)))
    assert done["reminded"] == 1
    assert [tg for tg, _ in sent] == [RIG] and "Встреча у моста" in sent[0][1]
    again = scheduler.run_once(now=time.time() + 3 * DAY + 30, send=lambda *a: sent.append(a))
    assert again["reminded"] == 0                                                # проверка идёт не чаще раза в REMIND_EVERY


def test_orphan_rows_are_purged():
    reminders.asked("несуществует", ["rig"])
    reminders.purge_orphans()
    assert db.conn().execute("SELECT COUNT(*) FROM invite_clock WHERE entry_id='несуществует'").fetchone()[0] == 0
