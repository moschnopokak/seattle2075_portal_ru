"""«Что видят игроки вперёд» (logic.horizon): пока включено, игроки не видят и не могут назвать дату позже конца текущего этапа.
В тестовой кампании сегодня 2075-08-01, этап «Промежуточная арка» идёт до 2075-08-31, дальше «СЕКРЕТ-будущий этап» (сентябрь)."""
import json
import re

import pytest

from app import db, notify, outbox
from conftest import GATE, RIG
from helpers import create, entry, ok, remove

H = "2075-08-31"                    # конец текущего этапа
BEYOND = "2075-09-10"               # уже следующий этап
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SECRET = "СЕКРЕТ"


def horizon(client, mode):
    return client.post("/api/gm/horizon", json={"mode": mode})


@pytest.fixture
def on(gm, sandbox):
    ok(horizon(gm, "window"))
    yield
    ok(horizon(gm, "off"))


@pytest.fixture
def telegram_on(monkeypatch):
    monkeypatch.setattr(notify, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(notify, "NOTIFY_DM", True)


def state(client):
    return ok(client.get("/api/state"))


def gm_entry(gm, **kw):
    return ok(gm.post("/api/entries", json=entry(char="gm", who=["rig"], **kw)))


def titles(st, kind):
    return [x.get("title") or x.get("name") for x in st[kind]]


def handout_with_file(gm, title, date, vis="стол"):
    data = ok(gm.post("/api/gm/items/handouts", json={"title": title, "date": date, "vis": vis, "known": [], "note": "Для игроков", "gm_note": ""}))
    hid = next(x["id"] for x in data["state"]["handouts"] if x["title"] == title)
    ok(gm.post(f"/api/gm/handouts/{hid}/file", content=b"<!doctype html><html><body>x</body></html>", headers={"X-File-Name": "f"}))
    return hid


# ---------------------------------------------------------------- выключено: всё как раньше

def test_off_by_default_players_see_the_whole_calendar(gm, rig, sandbox):
    gm_entry(gm, title="Дальняя встреча", **{"from": BEYOND, "to": BEYOND})
    st = state(rig)
    assert st["horizon"] == {"on": False, "until": ""} and st["calEnd"] == "2075-12-31"
    assert "Дальняя встреча" in titles(st, "entries")
    info = state(gm)["horizon"]
    assert info["mode"] == "off" and info["on"] is False and info["until"] == H and info["window"] == "Промежуточная арка" and info["hidden"] == {}


# ---------------------------------------------------------------- включено: что скрыто

def test_calendar_range_and_flags(gm, rig, on):
    st = state(rig)
    assert st["horizon"] == {"on": True, "until": H} and st["calEnd"] == H
    g = state(gm)
    assert g["calEnd"] == "2075-12-31" and g["horizon"]["mode"] == "window" and g["horizon"]["on"] is True and g["horizon"]["until"] == H


def test_entries_beyond_the_horizon_are_hidden_and_cannot_be_opened(gm, rig, gate, on):
    gm_entry(gm, title="Видимая сейчас", **{"from": "2075-08-20", "to": "2075-08-20"})
    gm_entry(gm, title="Последний день", **{"from": H, "to": H})
    far = gm_entry(gm, title="Далёкая встреча", **{"from": BEYOND, "to": BEYOND})
    far_id = next(e["id"] for e in far["state"]["entries"] if e["title"] == "Далёкая встреча")
    gm_entry(gm, title="Далёкое личное", vis="лично", **{"from": BEYOND, "to": BEYOND})
    shown = titles(state(rig), "entries")
    assert "Видимая сейчас" in shown and "Последний день" in shown
    assert "Далёкая встреча" not in shown and "Далёкое личное" not in shown
    assert "Далёкая встреча" in titles(state(gm), "entries")                                # мастер видит всё
    r = rig.post(f"/api/entries/{far_id}/act", json={"act": "star", "char": "rig"})
    assert r.status_code == 404 and "не найдена" in r.json()["detail"]                      # по номеру тоже не открыть
    assert far_id not in json.dumps(state(gate), ensure_ascii=False)


def test_an_entry_that_crosses_the_border_is_shown_but_ends_at_the_border(gm, rig, on):
    gm_entry(gm, title="Через границу", **{"from": "2075-08-30", "to": "2075-09-04"})
    e = next(e for e in state(rig)["entries"] if e["title"] == "Через границу")
    assert e["from"] == "2075-08-30" and e["to"] == H
    assert next(e for e in state(gm)["entries"] if e["title"] == "Через границу")["to"] == "2075-09-04"


def test_cover_events_regular_events_and_chronicle(gm, rig, on):
    ok(gm.post("/api/gm/items/plan", json={"title": "План с маской далеко", "from": BEYOND, "to": "2075-09-12", "cover": {"title": "Видно только потом", "who": []}}))
    ok(gm.post("/api/gm/items/plan", json={"title": "План с маской рядом", "from": "2075-08-20", "to": "2075-09-03", "cover": {"title": "Видно уже сейчас", "who": []}}))
    ok(gm.post("/api/gm/items/rhythm", json={"title": "Далёкий рынок", "vis": "стол", "wd": [2], "from": BEYOND, "to": ""}))
    ok(gm.post("/api/gm/items/rhythm", json={"title": "Ближний рынок", "vis": "стол", "wd": [4], "from": "2075-08-10", "to": "2075-12-01"}))
    ok(gm.post("/api/gm/items/past", json={"title": "Сыгранное из будущего", "from": BEYOND, "to": BEYOND}))
    st = state(rig)
    assert [b["title"] for b in st["blocks"] if "Видно" in b["title"]] == ["Видно уже сейчас"]
    assert next(b for b in st["blocks"] if b["title"] == "Видно уже сейчас")["to"] == H
    assert "Далёкий рынок" not in titles(st, "rhythm") and next(r for r in st["rhythm"] if r["title"] == "Ближний рынок")["to"] == H
    assert "Сыгранное из будущего" not in titles(st, "past")
    g = state(gm)
    assert "Далёкий рынок" in titles(g, "rhythm") and "Сыгранное из будущего" in titles(g, "past")
    assert g["horizon"]["hidden"]["blocks"] == 1 and g["horizon"]["hidden"]["rhythm"] == 1


def test_handouts_dated_beyond_the_horizon_are_hidden_even_when_opened(gm, rig, on):
    handout_with_file(gm, "Раздатка сейчас", "2075-08-15")
    handout_with_file(gm, "Раздатка потом", BEYOND)
    assert titles(state(rig), "handouts") == ["Раздатка сейчас"]
    assert sorted(titles(state(gm), "handouts")) == ["Раздатка потом", "Раздатка сейчас"]
    assert state(gm)["horizon"]["hidden"]["handouts"] == 1


def test_dossier_facts_dated_beyond_the_horizon_are_hidden_but_the_card_stays(gm, rig, on):
    card = {"name": "Мэри-Лу", "type": "person", "vis": "стол", "known": [], "met": [], "gm_note": "",
            "facts": [{"id": "a1", "text": "Узнали давно", "vis": "стол", "known": [], "truth": "", "date": "2075-08-05"},
                      {"id": "a2", "text": "Узнают потом", "vis": "стол", "known": [], "truth": "", "date": BEYOND},
                      {"id": "a3", "text": "Без даты", "vis": "стол", "known": [], "truth": ""}]}
    ok(gm.post("/api/gm/items/dossier", json=card))
    seen = next(c for c in state(rig)["dossier"] if c["name"] == "Мэри-Лу")
    assert [f["text"] for f in seen["facts"]] == ["Узнали давно", "Без даты"]
    assert len(next(c for c in state(gm)["dossier"] if c["name"] == "Мэри-Лу")["facts"]) == 3


def test_no_date_after_the_horizon_anywhere_in_the_players_state(gm, rig, on):
    gm_entry(gm, title="Далёкая", **{"from": BEYOND, "to": "2075-09-20"})
    gm_entry(gm, title="Через границу", **{"from": "2075-08-30", "to": "2075-09-04"})
    ok(gm.post("/api/gm/items/plan", json={"title": "Маска далеко", "from": BEYOND, "to": BEYOND, "cover": {"title": "Далеко", "who": []}}))
    handout_with_file(gm, "Раздатка потом", BEYOND)
    st = state(rig)
    for key in ("entries", "blocks", "handouts", "past", "rhythm"):
        for path, value in __import__("helpers").walk(st[key], key):
            if isinstance(value, str) and ISO.match(value):
                assert value <= H, (path, value)
    assert st["calEnd"] == H


# ---------------------------------------------------------------- игрок не может назвать дату позже границы

@pytest.mark.parametrize("start, end", [(BEYOND, BEYOND), ("2075-08-30", "2075-09-02"), ("2075-12-01", "2075-12-02")])
def test_player_cannot_create_an_entry_beyond_the_horizon(rig, on, start, end):
    r = rig.post("/api/entries", json=entry(char="rig", title="Слишком далеко", who=["rig"], **{"from": start, "to": end}))
    assert r.status_code == 400 and r.json()["detail"].startswith("Дальше ") and "31 августа" in r.json()["detail"] and "до конца текущего этапа" in r.json()["detail"]


def test_player_can_create_up_to_the_border_and_cannot_move_past_it(gm, rig, on):
    e = create(rig, char="rig", title="До границы", who=["rig"], **{"from": H, "to": H})
    try:
        r = rig.post(f"/api/entries/{e['id']}/edit", json=entry(char="rig", title="До границы", who=["rig"], **{"from": BEYOND, "to": BEYOND}))
        assert r.status_code == 400 and "31 августа" in r.json()["detail"]
        assert next(x for x in state(rig)["entries"] if x["id"] == e["id"])["from"] == H
    finally:
        remove(gm, e["id"])


def test_growth_request_cannot_take_effect_beyond_the_horizon(rig, on):
    r = rig.post("/api/entries", json=entry(char="rig", type="grow", title="Рост", who=["rig"], goal="Цель", effect=BEYOND, **{"from": "2075-08-05", "to": "2075-08-05"}))
    assert r.status_code == 400 and "31 августа" in r.json()["detail"]


def test_master_is_not_limited(gm, on):
    assert gm.post("/api/entries", json=entry(char="gm", title="Мастеру можно", who=["rig"], **{"from": "2075-12-20", "to": "2075-12-20"})).status_code == 200


def test_when_off_players_can_name_any_date_again(gm, rig, sandbox):
    ok(horizon(gm, "window"))
    ok(horizon(gm, "off"))
    e = create(rig, char="rig", title="Снова можно", who=["rig"], **{"from": BEYOND, "to": BEYOND})
    remove(gm, e["id"])


# ---------------------------------------------------------------- граница двигается вместе с игровым временем

def test_the_border_moves_with_the_game_date(gm, rig, on):
    gm_entry(gm, title="Сентябрьская встреча", **{"from": BEYOND, "to": BEYOND})
    assert "Сентябрьская встреча" not in titles(state(rig), "entries")
    ok(gm.post("/api/gm/time", json={"date": "2075-09-01"}))                              # начался следующий этап
    st = state(rig)
    assert st["horizon"]["until"] == "2075-09-30" and st["calEnd"] == "2075-09-30"
    assert "Сентябрьская встреча" in titles(st, "entries")
    ok(gm.post("/api/gm/time", json={"date": "2075-08-31"}))
    assert "Сентябрьская встреча" not in titles(state(rig), "entries")


def test_outside_any_stage_there_is_no_limit_and_the_master_is_told(gm, rig, on):
    ok(gm.post("/api/gm/time", json={"date": "2075-10-15"}))
    st = state(rig)
    assert st["horizon"] == {"on": False, "until": ""} and st["calEnd"] == "2075-12-31"
    info = state(gm)["horizon"]
    assert info["mode"] == "window" and info["on"] is False and info["until"] == "" and info["window"] == ""


# ---------------------------------------------------------------- переключатель

def test_only_the_master_switches_it(rig, anon, gm, sandbox):
    assert horizon(rig, "window").status_code == 403
    assert horizon(anon, "window").status_code == 401
    assert state(gm)["horizon"]["mode"] == "off"


@pytest.mark.parametrize("mode", ["", "всё", None, 5, ["window"], {"a": 1}])
def test_unknown_modes_are_refused(gm, sandbox, mode):
    r = horizon(gm, mode)
    assert r.status_code == 400 and "Выберите" in r.json()["detail"]
    assert state(gm)["horizon"]["mode"] == "off"


def test_switching_is_logged_once_and_repeating_changes_nothing(gm, sandbox):
    def records():
        return [h for h in ok(gm.get("/api/gm/history?kind=horizon&limit=100"))["items"] if h["action"] == "setting"]
    before = len(records())
    ok(horizon(gm, "window"))
    version = state(gm)["version"]
    ok(horizon(gm, "window"))
    assert state(gm)["version"] == version and len(records()) == before + 1
    rec = records()[0]
    assert rec["title"] == "Игроки видят вперёд: до конца текущего этапа" and rec["role"] == "gm"
    assert gm.post(f"/api/gm/history/{rec['id']}/revert").status_code == 400
    ok(horizon(gm, "off"))
    assert records()[0]["title"] == "Игроки видят вперёд: без ограничения"


# ---------------------------------------------------------------- уведомления о будущем не уходят

def texts(tg):
    return [r["text"] for r in outbox.pending(tg)]


def test_cover_event_from_the_future_does_not_notify_players(gm, on, telegram_on):
    db.conn().execute("DELETE FROM outbox")
    ok(gm.post("/api/gm/items/plan", json={"title": "Ближнее", "from": "2075-08-20", "to": "2075-08-20", "cover": {"title": "Ближнее общее", "who": []}}))
    assert any("Ближнее общее" in t for t in texts(RIG))
    db.conn().execute("DELETE FROM outbox")
    ok(gm.post("/api/gm/items/plan", json={"title": "Дальнее", "from": BEYOND, "to": BEYOND, "cover": {"title": "Дальнее общее", "who": []}}))
    assert not any("Дальнее общее" in t for t in texts(RIG) + texts(GATE))
    db.conn().execute("DELETE FROM outbox")


def test_handout_from_the_future_does_not_notify_players(gm, on, telegram_on):
    db.conn().execute("DELETE FROM outbox")
    handout_with_file(gm, "Ближняя раздатка", "2075-08-15")
    assert any("Ближняя раздатка" in t for t in texts(RIG))
    db.conn().execute("DELETE FROM outbox")
    handout_with_file(gm, "Дальняя раздатка", BEYOND)
    assert not any("Дальняя раздатка" in t for t in texts(RIG) + texts(GATE))
    db.conn().execute("DELETE FROM outbox")


# ---------------------------------------------------------------- производные вещи опираются на то же состояние

def test_recap_and_diary_do_not_carry_dates_from_beyond(gm, rig, on):
    from app import diary, logic
    handout_with_file(gm, "Раздатка потом", BEYOND)
    ok(gm.post("/api/gm/items/past", json={"title": "Сыгранное из будущего", "from": BEYOND, "to": BEYOND, "note": f"{SECRET}-будущее"}))
    v = logic.Viewer("player", {"name": "Игрок", "chars": ["rig"]}, RIG, "")
    doc = diary.build(v, "rig", diary.parse_parts(None))
    assert SECRET not in json.dumps(doc, ensure_ascii=False) and "Раздатка потом" not in json.dumps(doc, ensure_ascii=False)


def test_the_master_preview_data_is_unaffected_for_the_master(gm, on):
    st = state(gm)
    assert st["calEnd"] == "2075-12-31" and "2075-09-01" in [w["from"] for w in st["windows"]]          # мастер видит и будущий этап


def test_no_reminders_about_invitations_the_player_cannot_see(gm, gate, on, monkeypatch):
    """Игрок пригласил Рига на дату дальше границы ещё до включения; после включения напоминать о нём нельзя: Риг запись уже не видит."""
    from app import reminders
    ok(horizon(gm, "off"))
    e = create(gate, char="gate", title="Давнее приглашение", who=["rig"], **{"from": BEYOND, "to": BEYOND})
    try:
        monkeypatch.setattr(reminders, "REMIND_DAYS", 1)
        monkeypatch.setattr(reminders, "REMIND_MAX", 3)
        later = e["created"] + 3 * 86400
        assert [x[0]["title"] for x in reminders.due(later, only={e["id"]})] == ["Давнее приглашение"]
        ok(horizon(gm, "window"))
        assert reminders.due(later, only={e["id"]}) == []
    finally:
        remove(gm, e["id"])
