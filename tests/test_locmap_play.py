"""Карты локаций, всё, что помогает на игре: счётчики мастера с правилами расчистки, журнал и отмена, сроки, фишка группы «Мы здесь»,
вопросы мастеру, связи с досье и раздатками, значок «новое». Главное: игрок не видит ни счётчиков, ни скрытых сроков, ни журнала."""
import json

import pytest

from app import db, notify, outbox
from conftest import GATE, GM, RIG
from helpers import ok
from test_locmaps import SECRET, SVG_GM, add, detail, feed, make_map, state, upload

TRI = [[100, 100], [300, 100], [200, 250]]
SQUARE = [[400, 400], [500, 400], [500, 500], [400, 500]]


@pytest.fixture(autouse=True)
def clean_tables(started):
    yield
    for table in ("locmap_files", "locmap_feed", "locmap_pins", "locmap_log", "outbox"):
        db.conn().execute(f"DELETE FROM {table}")


@pytest.fixture
def telegram_on(monkeypatch):
    monkeypatch.setattr(notify, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(notify, "NOTIFY_DM", True)


@pytest.fixture
def play(gm, sandbox):
    """Карта с двумя рисунками и тремя метками: Опушка и Глубина (зоны со счётчиками и правилами) и скрытая Сердце."""
    mid = make_map(gm)
    ok(upload(gm, mid, "player"))
    ok(upload(gm, mid, "gm", SVG_GM))
    gm.post("/api/gm/items/locmaps", json={"id": mid, "name": "Роща", "vis": "стол", "counter": "Фон"})
    add(gm, mid, name="Опушка", key="О1", vis="стол", play=True, shape={"player": TRI}, at={"player": [200, 150]}, count=3, fx=[{"to": "self", "delta": -2}])
    add(gm, mid, name="Глубина", key="Г1", vis="стол", play=True, shape={"player": SQUARE}, at={"player": [450, 450]}, count=4,
        fx=[{"to": "self", "delta": -2}, {"to": "Сердце", "delta": -1}])
    add(gm, mid, name="Сердце", key="Сердце", vis="мастер", play=False, at={"player": [600, 100]}, count=5)
    return mid


def obj(client, mid, key):
    return next(o for o in detail(client, mid)["objects"] if o["key"] == key)


def mark(client, mid, key, status="cleared", text=""):
    oid = obj(client, mid, key)["id"]
    return client.post(f"/api/locmaps/{mid}/objects/{oid}/mark", json={"status": status, "text": text})


def gm_set(gm, mid, key, **body):
    return gm.post(f"/api/gm/locmaps/{mid}/objects", json={"id": obj(gm, mid, key)["id"], "announce": False, **body})


def counts(gm, mid):
    return {o["key"]: o["count"] for o in detail(gm, mid)["objects"]}


# ---------------------------------------------------------------- счётчики и правила расчистки

def test_clearing_a_zone_changes_the_counters_by_its_rules_and_only_once(gm, rig, play):
    assert counts(gm, play) == {"О1": 3, "Г1": 4, "Сердце": 5}
    ok(mark(rig, play, "Г1", "cleared"))
    assert counts(gm, play) == {"О1": 3, "Г1": 2, "Сердце": 4}                 # своя зона −2 и «Сердце» −1
    ok(mark(rig, play, "Г1", "cleared", "ещё раз"))                              # то же состояние: правила второй раз не применяются
    assert counts(gm, play) == {"О1": 3, "Г1": 2, "Сердце": 4}
    ok(mark(rig, play, "Г1", "danger"))                                         # состояние сменилось на другое: расчистка снята, счётчики вернулись
    assert counts(gm, play) == {"О1": 3, "Г1": 4, "Сердце": 5}
    ok(mark(rig, play, "Г1", "cleared"))
    ok(mark(rig, play, "Г1", ""))
    assert counts(gm, play) == {"О1": 3, "Г1": 4, "Сердце": 5}


def test_the_master_changing_a_state_applies_the_same_rules(gm, play):
    ok(gm_set(gm, play, "О1", status="cleared"))
    assert counts(gm, play)["О1"] == 1
    ok(gm_set(gm, play, "О1", status="found"))
    assert counts(gm, play)["О1"] == 3
    ok(gm_set(gm, play, "О1", note="Новое описание"))                            # правка текста счётчики не трогает
    assert counts(gm, play)["О1"] == 3


def test_players_never_see_counters_or_rules(gm, rig, play):
    ok(mark(rig, play, "Г1", "cleared"))
    card = obj(rig, play, "Г1")
    assert not {"count", "fx", "fx_on", "gm_note"} & set(card)
    text = json.dumps(detail(rig, play), ensure_ascii=False) + rig.get("/api/state").text
    assert '"count"' not in text and '"fx"' not in text and '"counter"' not in text and SECRET not in text
    assert all("counter" not in m and "due" not in m for m in state(rig)["locmaps"])


def test_the_master_edits_a_counter_by_hand_and_bad_values_are_refused(gm, play):
    ok(gm_set(gm, play, "О1", count=7))
    assert counts(gm, play)["О1"] == 7
    ok(gm_set(gm, play, "О1", count=""))
    assert counts(gm, play)["О1"] is None
    for bad_value in (1.5, "abc", [1], {"a": 1}, 10000, -1000, True):
        assert gm_set(gm, play, "О1", count=bad_value).status_code == 400, bad_value


@pytest.mark.parametrize("fx", [[{"to": "self", "delta": 0}], [{"to": "", "delta": 1}], [{"to": "self", "delta": 100}], [{"to": "self", "delta": "x"}],
                                ["self"], "self", [{"to": "self", "delta": 1}] * 7, [{"delta": 1}]])
def test_bad_clearing_rules_are_refused(gm, play, fx):
    assert gm_set(gm, play, "О1", fx=fx).status_code == 400


def test_a_rule_pointing_to_a_missing_zone_changes_nothing_else(gm, rig, play):
    ok(gm_set(gm, play, "О1", fx=[{"to": "Нет такой", "delta": 5}, {"to": "self", "delta": -1}]))
    ok(mark(rig, play, "О1", "cleared"))
    assert counts(gm, play) == {"О1": 2, "Г1": 4, "Сердце": 5}


def test_bump_changes_every_counter_and_needs_at_least_one(gm, rig, play):
    ok(gm.post(f"/api/gm/locmaps/{play}/counter", json={"delta": 1}))
    assert counts(gm, play) == {"О1": 4, "Г1": 5, "Сердце": 6}
    ok(gm.post(f"/api/gm/locmaps/{play}/counter", json={"delta": -3}))
    assert counts(gm, play) == {"О1": 1, "Г1": 2, "Сердце": 3}
    for body in ({"delta": 0}, {"delta": 100}, {"delta": "a"}, {}, {"delta": [1]}):
        assert gm.post(f"/api/gm/locmaps/{play}/counter", json=body).status_code == 400
    assert rig.post(f"/api/gm/locmaps/{play}/counter", json={"delta": 1}).status_code == 403
    other = make_map(gm, name="Пустая")
    assert gm.post(f"/api/gm/locmaps/{other}/counter", json={"delta": 1}).status_code == 400


def test_import_sets_counters_for_new_zones_but_never_resets_them(gm, play):
    data = {"counter": "Фон", "objects": [{"key": "Н1", "name": "Новая", "kind": "area", "count": 6, "fx": [{"to": "self", "delta": -2}], "shape": {"player": TRI}}]}
    assert ok(gm.post(f"/api/gm/locmaps/{play}/import", json=data))["report"]["add"] == 1
    assert counts(gm, play)["Н1"] == 6
    ok(gm_set(gm, play, "Н1", count=9))
    again = ok(gm.post(f"/api/gm/locmaps/{play}/import", json=data))["report"]
    assert (again["add"], again["update"], again["skip"]) == (0, 0, 1) and counts(gm, play)["Н1"] == 9     # счётчик, который менял мастер, не сбрасывается
    assert next(m for m in state(gm)["locmaps"] if m["id"] == play)["counter"] == "Фон"


def test_the_map_form_keeps_deadlines_party_and_marks_and_sets_the_counter_name(gm, play):
    ok(gm.post(f"/api/gm/locmaps/{play}/deadlines", json={"date": "2075-08-10", "title": "Срок"}))
    ok(gm.post(f"/api/locmaps/{play}/party", json={"x": 50, "y": 60}))
    ok(gm.post("/api/gm/items/locmaps", json={"id": play, "name": "Роща (новое имя)", "vis": "стол", "counter": "Угроза"}))
    d = detail(gm, play)
    assert len(d["objects"]) == 3 and len(d["deadlines"]) == 1 and d["party"]["x"] == 50 and d["counter"] == "Угроза"


# ---------------------------------------------------------------- журнал и отмена

def test_state_changes_by_players_and_by_the_master_are_logged_and_undone(gm, rig, play):
    ok(mark(rig, play, "Г1", "cleared", "Чисто"))
    ok(gm_set(gm, play, "О1", status="danger"))
    log = detail(gm, play)["log"]
    assert [r["kind"] for r in log[:2]] == ["status", "status"] and log[1]["text"] == "Риг: «Глубина», расчищено. Чисто"
    assert log[0]["text"] == "Мастер: «Опушка», опасно" and log[0]["undoable"] is True
    ok(gm.post(f"/api/gm/locmaps/{play}/log/{log[1]['id']}/undo"))
    g = obj(gm, play, "Г1")
    assert (g["status"], g["by"], g["date"]) == ("", "", "") and counts(gm, play) == {"О1": 3, "Г1": 4, "Сердце": 5}   # состояние и счётчики вернулись
    assert detail(gm, play)["log"][0]["kind"] == "undo" and any(r["undone"] for r in detail(gm, play)["log"])
    assert "«Глубина»: отметка снята (мастер вернул прежнее)" in feed(rig, play)
    assert gm.post(f"/api/gm/locmaps/{play}/log/{log[1]['id']}/undo").status_code == 409     # второй раз нельзя


def test_undoing_an_older_change_does_not_apply_the_rules_a_second_time(gm, rig, play):
    ok(mark(rig, play, "Г1", "cleared"))
    ok(mark(rig, play, "Г1", "danger"))
    ok(mark(rig, play, "Г1", "cleared"))                                           # расчищено, потом опасно, потом снова расчищено
    assert counts(gm, play) == {"О1": 3, "Г1": 2, "Сердце": 4}
    older = [r for r in detail(gm, play)["log"] if r["kind"] == "status"][1]       # «опасно», прежнее состояние до него было «расчищено»
    ok(gm.post(f"/api/gm/locmaps/{play}/log/{older['id']}/undo"))
    assert obj(gm, play, "Г1")["status"] == "cleared" and counts(gm, play) == {"О1": 3, "Г1": 2, "Сердце": 4}      # правила действуют один раз


def test_undo_restores_the_previous_author_and_date(gm, rig, gate, play):
    ok(mark(rig, play, "О1", "scouted"))
    first = obj(gm, play, "О1")
    ok(mark(gate, play, "О1", "danger"))
    gate_row = detail(gm, play)["log"][0]
    ok(gm.post(f"/api/gm/locmaps/{play}/log/{gate_row['id']}/undo"))
    now = obj(gm, play, "О1")
    assert (now["status"], now["by"], now["date"]) == ("scouted", "rig", first["date"])


def test_a_deleted_mark_comes_back_with_everything(gm, play):
    before = obj(gm, play, "Г1")
    ok(gm.post(f"/api/gm/locmaps/{play}/objects/{before['id']}/delete"))
    assert not any(o["key"] == "Г1" for o in detail(gm, play)["objects"])
    row = next(r for r in detail(gm, play)["log"] if r["kind"] == "delete")
    ok(gm.post(f"/api/gm/locmaps/{play}/log/{row['id']}/undo"))
    assert obj(gm, play, "Г1") == before
    add(gm, play, name="Другая", key="Д9", vis="стол")
    again = next(r for r in detail(gm, play)["log"] if r["kind"] == "undo")
    assert gm.post(f"/api/gm/locmaps/{play}/log/{again['id']}/undo").status_code == 400         # саму отмену отменить нельзя


def test_a_deleted_mark_cannot_come_back_over_a_taken_key(gm, play):
    gone = obj(gm, play, "Г1")
    ok(gm.post(f"/api/gm/locmaps/{play}/objects/{gone['id']}/delete"))
    add(gm, play, name="Занял место", key="Г1", vis="стол")
    row = next(r for r in detail(gm, play)["log"] if r["kind"] == "delete")
    assert gm.post(f"/api/gm/locmaps/{play}/log/{row['id']}/undo").status_code == 409


def test_only_the_master_sees_and_uses_the_log(gm, rig, anon, play):
    ok(mark(rig, play, "О1", "cleared"))
    row = detail(gm, play)["log"][0]
    assert "log" not in detail(rig, play)
    assert rig.post(f"/api/gm/locmaps/{play}/log/{row['id']}/undo").status_code == 403
    assert anon.post(f"/api/gm/locmaps/{play}/log/{row['id']}/undo").status_code == 401
    for bad_id in (999999, 0):
        assert gm.post(f"/api/gm/locmaps/{play}/log/{bad_id}/undo").status_code == 404


def test_the_log_is_capped(gm, play, monkeypatch):
    from app import locmaps
    monkeypatch.setattr(locmaps, "MAX_LOG", 5)
    for i in range(9):
        ok(gm_set(gm, play, "О1", status="danger" if i % 2 == 0 else "scouted"))
    assert len(detail(gm, play)["log"]) == 5


# ---------------------------------------------------------------- сроки

def deadline(gm, mid, **kw):
    body = {"date": "2075-08-05", "title": "Тедди Мур становится статуей"}
    body.update(kw)
    return gm.post(f"/api/gm/locmaps/{mid}/deadlines", json=body)


def test_the_master_adds_changes_and_removes_a_deadline(gm, play):
    d = ok(deadline(gm, play, note=f"{SECRET}-срок", obj=obj(gm, play, "О1")["id"], status="cleared", delta=-1, reveal=True))["deadline"]
    assert d["done"] is False and d["vis"] == "мастер" and d["delta"] == -1
    ok(gm.post(f"/api/gm/locmaps/{play}/deadlines", json={"id": d["id"], "title": "Другое название"}))
    assert detail(gm, play)["deadlines"][0]["title"] == "Другое название" and detail(gm, play)["deadlines"][0]["date"] == "2075-08-05"
    ok(gm.post(f"/api/gm/locmaps/{play}/deadlines/{d['id']}/delete"))
    assert detail(gm, play)["deadlines"] == [] and gm.post(f"/api/gm/locmaps/{play}/deadlines/{d['id']}/delete").status_code == 404


@pytest.mark.parametrize("body", [
    {"date": "2075-13-45"}, {"date": "2001-01-01"}, {"date": ""}, {"date": None}, {"date": ["2075-08-05"]}, {"title": ""}, {"title": None},
    {"obj": "нет такой"}, {"status": "победа"}, {"status": ["cleared"]}, {"delta": 100}, {"delta": "x"}, {"delta": 1.5},
    {"vis": "знают", "known": []}, {"vis": "знают", "known": ["чужой"]},
])
def test_bad_deadlines_are_refused(gm, play, body):
    assert deadline(gm, play, **body).status_code == 400
    assert detail(gm, play)["deadlines"] == []


def test_players_see_only_the_deadlines_opened_to_them_without_the_master_details(gm, rig, gate, play):
    oid = obj(gm, play, "О1")["id"]
    ok(deadline(gm, play, title="Тайный срок", note=f"{SECRET}-тайный"))
    ok(deadline(gm, play, title="Открытый срок", vis="стол", obj=oid, note=f"{SECRET}-открытый", status="danger", delta=2))
    ok(deadline(gm, play, title="Только для Рига", vis="знают", known=["rig"]))
    ok(deadline(gm, play, title="Метка скрыта", vis="стол", obj=obj(gm, play, "Сердце")["id"]))
    titles = lambda who: [d["title"] for d in detail(who, play)["deadlines"]]
    assert titles(rig) == ["Метка скрыта", "Открытый срок", "Только для Рига"] or set(titles(rig)) == {"Открытый срок", "Только для Рига", "Метка скрыта"}
    assert set(titles(gate)) == {"Открытый срок", "Метка скрыта"} and len(titles(gm)) == 4
    shown = next(d for d in detail(rig, play)["deadlines"] if d["title"] == "Открытый срок")
    assert set(shown) == {"id", "date", "title", "obj", "done"} and shown["obj"] == oid
    assert next(d for d in detail(rig, play)["deadlines"] if d["title"] == "Метка скрыта")["obj"] == ""      # скрытую метку игрок по сроку не узнаёт
    assert SECRET not in json.dumps(detail(rig, play), ensure_ascii=False)


def test_deadlines_beyond_the_horizon_are_hidden_from_players(gm, rig, play):
    ok(deadline(gm, play, title="Далеко", vis="стол", date="2075-09-20"))
    ok(deadline(gm, play, title="Близко", vis="стол", date="2075-08-05"))
    assert {d["title"] for d in detail(rig, play)["deadlines"]} == {"Далеко", "Близко"}
    ok(gm.post("/api/gm/horizon", json={"mode": "window"}))
    try:
        assert {d["title"] for d in detail(rig, play)["deadlines"]} == {"Близко"}
    finally:
        ok(gm.post("/api/gm/horizon", json={"mode": "off"}))


def test_applying_a_deadline_does_what_it_says_once(gm, rig, play):
    oid = obj(gm, play, "Сердце")["id"]
    d = ok(deadline(gm, play, title="Цветение", vis="стол", obj=oid, status="danger", reveal=True, delta=2))["deadline"]
    r = ok(gm.post(f"/api/gm/locmaps/{play}/deadlines/{d['id']}/apply"))
    assert "Цветение" not in r["msg"] and "опасно" in r["msg"] and "открыта" in r["msg"]
    heart = obj(gm, play, "Сердце")
    assert (heart["status"], heart["vis"], heart["count"], heart["by"]) == ("danger", "стол", 7, "gm")
    assert obj(rig, play, "Сердце")["status"] == "danger"                       # метка открыта игрокам
    assert "Срок наступил: Цветение" in feed(rig, play) and "Открыто на карте: «Сердце»" in feed(rig, play)
    done = next(x for x in detail(gm, play)["deadlines"] if x["id"] == d["id"])
    assert done["done"] is True and done["done_date"] == state(gm)["now"]["date"]
    assert gm.post(f"/api/gm/locmaps/{play}/deadlines/{d['id']}/apply").status_code == 409
    assert counts(gm, play)["Сердце"] == 7                                      # второй раз ничего не меняется


def test_a_deadline_without_a_mark_changes_every_counter_and_a_secret_one_stays_off_the_feed(gm, rig, play):
    d = ok(deadline(gm, play, title="Полнолуние", delta=1))["deadline"]
    ok(gm.post(f"/api/gm/locmaps/{play}/deadlines/{d['id']}/apply"))
    assert counts(gm, play) == {"О1": 4, "Г1": 5, "Сердце": 6}
    assert not any("Полнолуние" in f for f in feed(rig, play))                  # срок скрыт от игроков, в ленту не попал


def test_a_deadline_can_be_marked_done_without_consequences(gm, play):
    d = ok(deadline(gm, play, title="Пропущен", delta=5, status="cleared", obj=obj(gm, play, "О1")["id"]))["deadline"]
    ok(gm.post(f"/api/gm/locmaps/{play}/deadlines/{d['id']}/apply", json={"apply": False}))
    assert counts(gm, play)["О1"] == 3 and obj(gm, play, "О1")["status"] == ""
    assert next(x for x in detail(gm, play)["deadlines"] if x["id"] == d["id"])["done"] is True


def test_applying_a_deadline_is_undoable_through_the_log(gm, play):
    d = ok(deadline(gm, play, title="Срок", status="cleared", obj=obj(gm, play, "О1")["id"]))["deadline"]
    ok(gm.post(f"/api/gm/locmaps/{play}/deadlines/{d['id']}/apply"))
    assert obj(gm, play, "О1")["status"] == "cleared" and counts(gm, play)["О1"] == 1
    row = next(r for r in detail(gm, play)["log"] if r["kind"] == "status")
    ok(gm.post(f"/api/gm/locmaps/{play}/log/{row['id']}/undo"))
    assert obj(gm, play, "О1")["status"] == "" and counts(gm, play)["О1"] == 3


def test_only_the_master_works_with_deadlines(gm, rig, anon, play):
    d = ok(deadline(gm, play, vis="стол"))["deadline"]
    for url, body in ((f"/api/gm/locmaps/{play}/deadlines", {"date": "2075-08-05", "title": "x"}), (f"/api/gm/locmaps/{play}/deadlines/{d['id']}/apply", {}),
                      (f"/api/gm/locmaps/{play}/deadlines/{d['id']}/delete", {})):
        assert rig.post(url, json=body).status_code == 403 and anon.post(url, json=body).status_code == 401


def test_the_master_is_told_when_the_game_date_reaches_a_deadline(gm, play, telegram_on):
    ok(deadline(gm, play, title="Мина и старик", date="2075-08-06"))
    ok(deadline(gm, play, title="Далёкий срок", date="2075-09-30"))
    db.conn().execute("DELETE FROM outbox")
    ok(gm.post("/api/gm/time", json={"date": "2075-08-05"}))
    assert not any(r["kind"] == "map" for r in outbox.pending(GM))                 # срок ещё не наступил
    ok(gm.post("/api/gm/time", json={"date": "2075-08-07"}))
    row = next(r for r in outbox.pending(GM) if r["kind"] == "map")
    assert "Мина и старик" in row["text"] and "Далёкий срок" not in row["text"] and "«Роща»" in row["text"] and row["section"] == "maps"
    db.conn().execute("DELETE FROM outbox")
    ok(gm.post("/api/gm/time", json={"date": "2075-08-08"}))                       # тот же срок второй раз не напоминается
    assert not any(r["kind"] == "map" for r in outbox.pending(GM))


def test_the_master_badge_counts_due_deadlines_and_open_questions(gm, rig, play):
    ok(deadline(gm, play, title="Уже наступил", date="2075-07-20"))
    ok(deadline(gm, play, title="Ещё нет", date="2075-12-01"))
    ok(rig.post(f"/api/locmaps/{play}/pins", json={"text": "Куда идти?", "x": 10, "y": 10, "kind": "question"}))
    card = next(m for m in state(gm)["locmaps"] if m["id"] == play)
    assert (card["due"], card["open_q"]) == (1, 1)


def test_import_brings_deadlines_by_mark_key_and_is_safe_to_repeat(gm, play):
    data = {"deadlines": [{"date": "2075-08-31", "title": "Тедди Мур станет статуей", "obj": "О1", "note": "заметка"},
                          {"date": "2075-09-01", "title": "Цветение", "obj": "Сердце", "delta": 2},
                          {"date": "2075-08-26", "title": "Фон вернулся", "delta": -1},
                          {"date": "2075-08-27", "title": "Метки нет", "obj": "Нет такой"},
                          {"date": "2075-13-01", "title": "Плохая дата"}]}
    rep = ok(gm.post(f"/api/gm/locmaps/{play}/import", json=data))["report"]
    assert (rep["d_add"], rep["error"]) == (3, 2) and {i["title"] for i in rep["items"] if i["status"] == "error"} == {"Срок: Метки нет", "Срок: Плохая дата"}
    assert [d["date"] for d in detail(gm, play)["deadlines"]] == ["2075-08-26", "2075-08-31", "2075-09-01"]
    assert next(d for d in detail(gm, play)["deadlines"] if d["title"] == "Цветение")["obj"] == obj(gm, play, "Сердце")["id"]
    again = ok(gm.post(f"/api/gm/locmaps/{play}/import", json=data))["report"]
    assert (again["d_add"], again["d_update"], again["d_skip"]) == (0, 0, 3)
    data["deadlines"][1]["delta"] = 3
    assert ok(gm.post(f"/api/gm/locmaps/{play}/import", json=data))["report"]["d_update"] == 1
    d = next(d for d in detail(gm, play)["deadlines"] if d["title"] == "Цветение")
    ok(gm.post(f"/api/gm/locmaps/{play}/deadlines/{d['id']}/apply"))
    after = ok(gm.post(f"/api/gm/locmaps/{play}/import", json=data))["report"]
    assert after["d_add"] == 0 and next(x for x in detail(gm, play)["deadlines"] if x["id"] == d["id"])["done"] is True    # выполненный срок остаётся выполненным


def test_import_of_only_deadlines_is_allowed_and_nothing_at_all_is_not(gm, play):
    assert ok(gm.post(f"/api/gm/locmaps/{play}/import", json={"deadlines": [{"date": "2075-08-30", "title": "Только срок"}]}))["report"]["d_add"] == 1
    assert gm.post(f"/api/gm/locmaps/{play}/import", json={}).status_code == 400
    assert gm.post(f"/api/gm/locmaps/{play}/import", json={"deadlines": "срок"}).status_code == 400


def test_deadline_limit(gm, play, monkeypatch):
    from app import locmaps
    monkeypatch.setattr(locmaps, "MAX_DEADLINES", 2)
    ok(deadline(gm, play, title="1"))
    ok(deadline(gm, play, title="2"))
    assert deadline(gm, play, title="3").status_code == 409


# ---------------------------------------------------------------- фишка группы

def test_players_and_the_master_place_and_clear_the_party_token(gm, rig, gate, play):
    assert detail(rig, play)["party"] is None
    ok(rig.post(f"/api/locmaps/{play}/party", json={"x": 200, "y": 150}))
    for who in (gm, rig, gate):
        p = detail(who, play)["party"]
        assert (p["x"], p["y"], p["by"], p["date"]) == (200, 150, "rig", state(gm)["now"]["date"])
    ok(gm.post(f"/api/locmaps/{play}/party", json={"x": 450, "y": 450}))
    assert detail(gate, play)["party"]["by"] == "gm" and detail(gate, play)["party"]["x"] == 450
    ok(gate.post(f"/api/locmaps/{play}/party/clear"))
    assert detail(rig, play)["party"] is None
    assert gate.post(f"/api/locmaps/{play}/party/clear").json()["msg"] == "Группа и так не отмечена"


@pytest.mark.parametrize("body", [{"x": 900, "y": 10}, {"x": -1, "y": 10}, {"x": 1.5, "y": 2}, {"x": "a", "y": 2}, {"x": None, "y": 2}, {"x": [1], "y": 2}, {"y": 2}, {}, {"x": True, "y": 1}])
def test_a_bad_party_position_is_refused(gm, rig, play, body):
    assert rig.post(f"/api/locmaps/{play}/party", json=body).status_code == 400 and detail(gm, play)["party"] is None


def test_the_party_needs_a_visible_map_with_a_players_drawing(gm, rig, anon, sandbox):
    hidden = make_map(gm, name="Скрытая", vis="мастер")
    ok(upload(gm, hidden, "player"))
    assert rig.post(f"/api/locmaps/{hidden}/party", json={"x": 1, "y": 1}).status_code == 404
    bare = make_map(gm, name="Без рисунка", vis="стол")
    assert rig.post(f"/api/locmaps/{bare}/party", json={"x": 1, "y": 1}).status_code == 400
    assert anon.post(f"/api/locmaps/{bare}/party", json={"x": 1, "y": 1}).status_code == 401


# ---------------------------------------------------------------- вопросы мастеру и типы пометок

def pin(client, mid, text="Тропы врут", kind="note", **kw):
    return client.post(f"/api/locmaps/{mid}/pins", json={"text": text, "x": 120, "y": 130, "kind": kind, **kw})


def test_pins_have_a_kind_and_an_unknown_kind_is_a_plain_note(gm, rig, play):
    for kind in ("note", "danger", "find", "question", "что-то", None, ["danger"]):
        ok(pin(rig, play, kind=kind))
    assert [p["kind"] for p in detail(gm, play)["pins"]] == ["note", "danger", "find", "question", "note", "note", "note"]
    assert detail(gm, play)["pin_kinds"]["question"] == "Вопрос мастеру"


def test_a_question_reaches_the_master_and_the_answer_reaches_everyone(gm, rig, gate, play, telegram_on):
    db.conn().execute("DELETE FROM outbox")
    r = ok(pin(rig, play, "Что за звук у ворот?", "question"))
    assert "Вопрос мастеру" in r["msg"]
    row = next(x for x in outbox.pending(GM) if x["kind"] == "map")
    assert "Риг: Что за звук у ворот?" in row["text"] and "«Роща»" in row["text"]
    qid = detail(gm, play)["pins"][0]["id"]
    db.conn().execute("DELETE FROM outbox")
    ok(gm.post(f"/api/gm/locmaps/{play}/pins/{qid}/answer", json={"text": "Скрипят цепи на ветру"}))
    for who in (rig, gate):
        p = detail(who, play)["pins"][0]
        assert p["answer"] == "Скрипят цепи на ветру" and p["answered"] > 0
        assert "Ответ мастера на вопрос «Что за звук у ворот?»: Скрипят цепи на ветру" in feed(who, play)
    assert not any(x["kind"] == "map" for x in outbox.pending(RIG))               # без галочки в Telegram ничего не уходит
    ok(gm.post(f"/api/gm/locmaps/{play}/pins/{qid}/answer", json={"text": "Уточняю: это цепи", "notify": True}))
    assert any(x["kind"] == "map" and "Уточняю" in x["text"] for x in outbox.pending(RIG)) and any(x["kind"] == "map" for x in outbox.pending(GATE))
    assert next(m for m in state(gm)["locmaps"] if m["id"] == play)["open_q"] == 0       # отвеченный вопрос больше не считается


@pytest.mark.parametrize("who, body, code", [("rig", {"text": "Я сам отвечу"}, 403), ("gm", {"text": ""}, 400), ("gm", {}, 400), ("gm", {"text": None}, 400)])
def test_answers_are_for_the_master_and_not_empty(gm, rig, play, who, body, code):
    ok(pin(rig, play, "Вопрос", "question"))
    qid = detail(gm, play)["pins"][0]["id"]
    assert {"rig": rig, "gm": gm}[who].post(f"/api/gm/locmaps/{play}/pins/{qid}/answer", json=body).status_code == code
    assert detail(gm, play)["pins"][0]["answer"] == ""


def test_only_questions_can_be_answered_and_a_missing_pin_is_a_404(gm, rig, play):
    ok(pin(rig, play, "Просто заметка", "note"))
    nid = detail(gm, play)["pins"][0]["id"]
    assert gm.post(f"/api/gm/locmaps/{play}/pins/{nid}/answer", json={"text": "ответ"}).status_code == 400
    assert gm.post(f"/api/gm/locmaps/{play}/pins/99999/answer", json={"text": "ответ"}).status_code == 404


def test_a_long_answer_is_cut_and_markup_stays_text(gm, rig, play):
    ok(pin(rig, play, "Вопрос", "question"))
    qid = detail(gm, play)["pins"][0]["id"]
    ok(gm.post(f"/api/gm/locmaps/{play}/pins/{qid}/answer", json={"text": "<img src=x onerror=alert(1)>" + "я" * 500}))
    assert len(detail(rig, play)["pins"][0]["answer"]) == 300 and detail(rig, play)["pins"][0]["answer"].startswith("<img")


# ---------------------------------------------------------------- связи с досье и раздатками

def make_card(gm, name="Тедди Мур"):
    data = ok(gm.post("/api/gm/items/dossier", json={"name": name, "type": "person", "vis": "стол"}))
    return next(c["id"] for c in data["state"]["dossier"] if c["name"] == name)


def make_handout(gm, title="Письмо Хильды"):
    data = ok(gm.post("/api/gm/items/handouts", json={"title": title, "date": "2075-08-01", "vis": "стол"}))
    return next(h["id"] for h in data["state"]["handouts"] if h["title"] == title)


def test_a_mark_can_be_linked_to_dossier_cards_and_handouts(gm, rig, play):
    card, handout = make_card(gm), make_handout(gm)
    links = [{"kind": "dossier", "id": card}, {"kind": "handouts", "id": handout}, {"kind": "dossier", "id": card}]
    ok(gm_set(gm, play, "О1", links=links))
    assert obj(gm, play, "О1")["links"] == [{"kind": "dossier", "id": card}, {"kind": "handouts", "id": handout}]       # повтор убран
    assert obj(rig, play, "О1")["links"] == obj(gm, play, "О1")["links"]
    ok(gm_set(gm, play, "О1", note="Другое описание"))
    assert len(obj(gm, play, "О1")["links"]) == 2                               # правка текста связи не стирает
    ok(gm_set(gm, play, "О1", links=[]))
    assert obj(gm, play, "О1")["links"] == []


@pytest.mark.parametrize("links", [[{"kind": "dossier", "id": "нет-такой"}], [{"kind": "places", "id": "x"}], [{"kind": "dossier"}], [{"id": "x"}], ["dossier"], "dossier",
                                   [{"kind": "dossier", "id": 5}], [{"kind": ["dossier"], "id": "x"}]])
def test_bad_links_are_refused(gm, play, links):
    assert gm_set(gm, play, "О1", links=links).status_code == 400


def test_link_limit_and_import_does_not_touch_links(gm, play):
    ids = [make_card(gm, f"Карточка {i}") for i in range(13)]
    assert gm_set(gm, play, "О1", links=[{"kind": "dossier", "id": i} for i in ids]).status_code == 400
    ok(gm_set(gm, play, "О1", links=[{"kind": "dossier", "id": ids[0]}]))
    ok(gm.post(f"/api/gm/locmaps/{play}/import", json={"objects": [{"key": "О1", "name": "Опушка", "links": [{"kind": "dossier", "id": ids[1]}]}]}))
    assert obj(gm, play, "О1")["links"] == [{"kind": "dossier", "id": ids[0]}]    # загрузка списком связи не меняет


# ---------------------------------------------------------------- значок «новое»

def test_players_get_the_newest_feed_ids_they_may_see_and_the_master_does_not(gm, rig, gate, play):
    ok(gm.post(f"/api/gm/locmaps/{play}/feed", json={"text": "Для всех"}))
    ok(gm.post(f"/api/gm/locmaps/{play}/feed", json={"text": "Только Рига", "vis": "знают", "known": ["rig"]}))
    mine = next(m for m in state(rig)["locmaps"] if m["id"] == play)["fresh"]
    theirs = next(m for m in state(gate)["locmaps"] if m["id"] == play)["fresh"]
    ids = {f["text"]: f["id"] for f in detail(rig, play)["feed"]}
    assert mine == sorted(mine, reverse=True) and ids["Только Рига"] in mine and ids["Для всех"] in mine
    assert ids["Только Рига"] not in theirs and ids["Для всех"] in theirs
    assert "fresh" not in next(m for m in state(gm)["locmaps"] if m["id"] == play)


def test_the_fresh_list_is_short_and_follows_the_horizon(gm, rig, play):
    for i in range(35):
        ok(gm.post(f"/api/gm/locmaps/{play}/feed", json={"text": f"Запись {i}"}))
    fresh = lambda: next(m for m in state(rig)["locmaps"] if m["id"] == play)["fresh"]
    assert len(fresh()) == 30
    db.conn().execute("INSERT INTO locmap_feed(map_id,ts,gdate,obj,text,vis,known) VALUES(?,?,?,?,?,?,?)", (play, 9e9, "2075-12-01", "", "Из далёкого будущего", "стол", "[]"))
    future = db.conn().execute("SELECT MAX(id) AS i FROM locmap_feed").fetchone()["i"]
    assert future in fresh()
    ok(gm.post("/api/gm/horizon", json={"mode": "window"}))
    try:
        assert future not in fresh() and len(fresh()) == 30
    finally:
        ok(gm.post("/api/gm/horizon", json={"mode": "off"}))
