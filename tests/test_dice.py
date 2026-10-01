"""Броски кубов (Shadowrun 5): правила на подставных кубах, честность, права и защита от злоупотреблений в обсуждении."""
import json
import random

import pytest

from app import db, dice, logic, outbox
from conftest import GATE
from helpers import create, find, ok, remove


class Seq:
    """Подставные кубы: выдают заданные значения по порядку."""

    def __init__(self, *values):
        self.values = list(values)
        self.calls = 0

    def randint(self, a, b):
        self.calls += 1
        return self.values.pop(0) if self.values else 3


# ---------------------------------------------------------------- правила

def test_hits_are_fives_and_sixes():
    r = dice.roll(6, rng=Seq(6, 5, 4, 3, 2, 1))
    assert r["dice"] == [6, 5, 4, 3, 2, 1] and r["hits"] == 2 and r["counted"] == 2 and r["glitch"] == ""


@pytest.mark.parametrize("faces,pool,glitch", [
    ([1, 1, 1, 2, 3], 5, "critical"),       # три единицы из пяти и ни одного успеха
    ([1, 1, 1, 6, 5], 5, "glitch"),         # то же, но успехи есть
    ([1, 1, 5, 5], 4, ""),                  # ровно половина единиц это ещё не глитч
    ([1, 1, 1, 5], 4, "glitch"),
    ([1], 1, "critical"),
    ([6], 1, ""),
    ([1, 2], 2, ""),                        # одна из двух: ровно половина
    ([1, 1], 2, "critical"),
])
def test_glitch_rules(faces, pool, glitch):
    assert dice.roll(pool, rng=Seq(*faces))["glitch"] == glitch


def test_limit_caps_counted_hits_but_not_the_total():
    r = dice.roll(6, limit=2, rng=Seq(5, 5, 6, 6, 2, 3))
    assert r["hits"] == 4 and r["counted"] == 2


def test_limit_above_hits_changes_nothing():
    r = dice.roll(4, limit=9, rng=Seq(5, 2, 2, 2))
    assert r["hits"] == r["counted"] == 1


def test_edge_explodes_sixes_and_ignores_the_limit():
    # исходные [6, 6, 2]: две шестёрки дают два новых куба [6, 3], шестёрка даёт ещё один [1]
    r = dice.roll(3, edge=True, limit=1, rng=Seq(6, 6, 2, 6, 3, 1))
    assert r["dice"] == [6, 6, 2] and r["extra"] == [6, 3, 1]
    assert r["hits"] == 3 and r["counted"] == 3                                      # предел не действует


def test_edge_without_sixes_adds_nothing():
    r = dice.roll(4, edge=True, rng=Seq(1, 2, 3, 4))
    assert r["extra"] == []


def test_extra_dice_never_cause_a_glitch_and_do_not_count_as_ones():
    r = dice.roll(2, edge=True, rng=Seq(6, 6, 1, 1))                                 # исходные без единиц, две единицы в добавочных
    assert r["extra"] == [1, 1] and r["ones"] == 0 and r["glitch"] == ""


def test_explosion_always_terminates():
    class Sixes:
        def randint(self, a, b):
            return 6
    r = dice.roll(10, edge=True, rng=Sixes())
    assert len(r["extra"]) == dice.MAX_EXTRA and r["hits"] == 10 + dice.MAX_EXTRA


def test_threshold_decides_success_and_net():
    r = dice.roll(5, threshold=2, rng=Seq(5, 5, 5, 2, 2))
    assert r["success"] is True and r["net"] == 1
    r = dice.roll(5, threshold=3, rng=Seq(5, 5, 2, 2, 2))
    assert r["success"] is False and r["net"] == -1
    assert dice.roll(5, threshold=0, rng=Seq(2, 2, 2, 2, 2))["success"] is True      # порог 0: успех без успехов
    assert dice.roll(2, rng=Seq(5, 5))["success"] is None                            # без порога вердикта нет


def test_threshold_uses_hits_after_the_limit():
    r = dice.roll(6, limit=2, threshold=3, rng=Seq(5, 5, 5, 5, 2, 2))
    assert r["counted"] == 2 and r["success"] is False


def test_distribution_is_fair_enough():
    rng = random.Random(20750101)
    rolls = [dice.roll(6, rng=rng) for _ in range(20000)]
    mean_hits = sum(r["hits"] for r in rolls) / len(rolls)
    assert abs(mean_hits - 2.0) < 0.05                                               # вероятность успеха на кубе 1/3
    faces = [d for r in rolls for d in r["dice"]]
    for n in range(1, 7):
        assert abs(faces.count(n) / len(faces) - 1 / 6) < 0.01


def test_real_generator_stays_in_range():
    r = dice.roll(dice.MAX_POOL, edge=True)
    assert all(1 <= d <= 6 for d in r["dice"] + r["extra"]) and len(r["dice"]) == dice.MAX_POOL


def test_text_description():
    r = dice.roll(4, edge=False, limit=1, threshold=2, rng=Seq(5, 5, 1, 1))
    text = dice.describe(r, "Скрытность")
    assert "4d6" in text and "Скрытность" in text and "5 5 1 1" in text and "Успехов: 2" in text and "предела 1" in text and "Порог 2: провал" in text
    crit = dice.describe(dice.roll(3, rng=Seq(1, 1, 2)))
    assert "КРИТИЧЕСКИЙ ГЛИТЧ" in crit
    edge = dice.describe(dice.roll(2, edge=True, limit=1, rng=Seq(6, 5, 4)))
    assert "взрываются" in edge and "предел не действует" in edge


# ---------------------------------------------------------------- в обсуждении

@pytest.fixture
def thread(gate, gm):
    e = create(gate, char="gate", title="Дело с бросками", who=["rig"])
    yield e
    remove(gm, e["id"])


def roll(client, thread, **body):
    return client.post(f"/api/entries/{thread['id']}/roll", json=body)


def chat(client, thread):
    return find(ok(client.get("/api/state")), thread["id"])["chat"]


def test_participant_rolls_and_everyone_in_the_thread_sees_the_same_result(thread, rig, gate, gm):
    ok(roll(rig, thread, char="rig", dice=8, limit=5, threshold=2, label="Скрытность"))
    seen = [chat(c, thread)[-1] for c in (rig, gate, gm)]
    assert seen[0] == seen[1] == seen[2]
    msg = seen[0]
    r = msg["r"]
    assert msg["a"] == "rig" and len(r["dice"]) == 8 and r["pool"] == 8 and r["label"] == "Скрытность"
    assert r["hits"] == sum(1 for d in r["dice"] if d >= 5) and r["counted"] == min(r["hits"], 5)
    assert r["success"] == (r["counted"] >= 2) and "8d6" in msg["t"] and "Скрытность" in msg["t"]


def test_client_cannot_supply_the_result(thread, rig):
    ok(roll(rig, thread, char="rig", dice=3, dice_result=[6, 6, 6], result={"hits": 99}, hits=99, extra=[6, 6]))
    r = chat(rig, thread)[-1]["r"]
    assert len(r["dice"]) == 3 and r["hits"] <= 3 and r["extra"] == []              # лишние поля игнорируются, кубы бросил сервер


def test_rolling_uses_the_server_generator(thread, rig, monkeypatch):
    monkeypatch.setattr(dice, "roll", lambda *a, **k: {"pool": 1, "dice": [6], "extra": [], "hits": 1, "counted": 1, "ones": 0, "glitch": "",
                                                       "edge": False, "limit": None, "threshold": None, "success": None, "net": None})
    ok(roll(rig, thread, char="rig", dice=1))
    assert chat(rig, thread)[-1]["r"]["dice"] == [6]


def test_gm_can_roll_and_it_is_shown_as_the_master(thread, gm, rig):
    ok(roll(gm, thread, dice=5))
    m = chat(rig, thread)[-1]
    assert m["a"] == "gm" and "r" in m


def test_outsiders_and_closed_threads_are_refused(thread, hag, gate, anon):
    assert roll(hag, thread, char="hagane", dice=3).status_code == 403                                   # запись видна, но не участник
    assert roll(anon, thread, dice=3).status_code == 401
    ok(gate.post(f"/api/entries/{thread['id']}/act", json={"act": "talk", "char": "gate"}))              # обсуждение завершено
    r = roll(gate, thread, char="gate", dice=3)
    assert r.status_code == 400 and "окончено" in r.json()["detail"]


def test_a_player_cannot_roll_for_someone_elses_character(thread, rig):
    assert roll(rig, thread, char="gate", dice=3).status_code == 403


def test_private_thread_is_invisible_to_a_stranger(gate, hag, gm):
    e = create(gate, char="gate", title="Личная", who=["rig"], vis="лично")
    try:
        assert roll(hag, e, char="hagane", dice=2).status_code == 404
    finally:
        remove(gm, e["id"])


@pytest.mark.parametrize("body", [
    {"dice": 0}, {"dice": 41}, {"dice": -3}, {"dice": "много"}, {"dice": None}, {"dice": True}, {"dice": [3]}, {"dice": {"a": 1}}, {"dice": 2.5},
    {"dice": 3, "limit": 0}, {"dice": 3, "limit": 100}, {"dice": 3, "limit": "x"}, {"dice": 3, "limit": [1]},
    {"dice": 3, "threshold": -1}, {"dice": 3, "threshold": 100}, {"dice": 3, "threshold": "x"}, {},
])
def test_bad_parameters_are_refused(thread, rig, body):
    r = roll(rig, thread, char="rig", **body)
    assert r.status_code == 400, (body, r.status_code, r.text[:100])


def test_edges_of_valid_parameters(thread, rig):
    ok(roll(rig, thread, char="rig", dice=1))
    ok(roll(rig, thread, char="rig", dice=40, edge=True, limit=99, threshold=0))
    ok(roll(rig, thread, char="rig", dice="6", limit="", threshold=None))            # числа в строках и пустой предел
    last = chat(rig, thread)[-1]["r"]
    assert last["pool"] == 6 and last["limit"] is None and last["threshold"] is None


def test_label_is_cleaned_and_cut(thread, rig):
    ok(roll(rig, thread, char="rig", dice=2, label="  <b>Метка</b>\nс переводом " + "я" * 100))
    r = chat(rig, thread)[-1]["r"]
    assert "\n" not in r["label"] and len(r["label"]) <= 60 and r["label"].startswith("<b>Метка</b>")        # текст, не разметка: страница экранирует


def test_flood_is_limited(thread, rig, monkeypatch):
    monkeypatch.setattr(logic, "ROLLS_PER_MINUTE", 3)
    logic._ROLL_TIMES.clear()
    for _ in range(3):
        ok(roll(rig, thread, char="rig", dice=2))
    r = roll(rig, thread, char="rig", dice=2)
    assert r.status_code == 429 and "Слишком много" in r.json()["detail"]
    logic._ROLL_TIMES.clear()
    ok(roll(rig, thread, char="rig", dice=2))


def test_roll_notifies_like_a_message(thread, rig, monkeypatch):
    from app import notify
    monkeypatch.setattr(notify, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(notify, "NOTIFY_DM", True)
    db.conn().execute("DELETE FROM outbox")
    ok(roll(rig, thread, char="rig", dice=4, label="Взлом"))
    rows = [r for r in outbox.pending(GATE) if r["kind"] == "chat"]
    assert len(rows) == 1 and "Взлом" in json.loads(rows[0]["meta"])["last"] and "4d6" in json.loads(rows[0]["meta"])["last"]
    db.conn().execute("DELETE FROM outbox")


def test_rolls_survive_deleting_and_restoring_the_entry(thread, rig, gm, gate):
    ok(roll(rig, thread, char="rig", dice=5, label="Память"))
    before = chat(rig, thread)[-1]
    ok(gate.post(f"/api/entries/{thread['id']}/act", json={"act": "del", "char": "gate"}))
    t = next(t for t in ok(gm.get("/api/gm/trash"))["items"] if t["kind"] == "entry" and t["item_id"] == thread["id"])
    ok(gm.post(f"/api/gm/trash/{t['id']}/restore"))
    after = chat(rig, thread)[-1]
    assert after["r"] == before["r"] and after["t"] == before["t"]


def test_plain_messages_have_no_roll_field(thread, rig):
    ok(rig.post(f"/api/entries/{thread['id']}/messages", json={"char": "rig", "text": "Просто сообщение"}))
    assert "r" not in chat(rig, thread)[-1]


def test_old_database_without_the_roll_column_is_migrated(tmp_path):
    import os
    import sqlite3
    import subprocess
    import sys
    old = tmp_path / "portal.db"
    c = sqlite3.connect(old)
    c.executescript(db.SCHEMA)
    c.execute("INSERT INTO messages(entry_id,author,user_id,text,ts) VALUES('e1','rig',1,'до миграции',1.0)")
    c.commit()
    c.close()
    code = ("from app import db; db.init(); db.init(); r = db.conn().execute('SELECT text, roll FROM messages').fetchone(); "
            "print(db.schema_version(), db.LATEST, r['text'], r['roll'])")
    env = dict(os.environ, DATA_DIR=str(tmp_path), CONFIG_DIR=str(tmp_path))
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout.split()
    assert out[0] == out[1] and out[2:] == ["до", "миграции", "None"]
