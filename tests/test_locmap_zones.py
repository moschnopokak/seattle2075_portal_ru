"""Зоны на карте локаций: контур зоны на каждом рисунке и право игроков отмечать её состояние («расчищено»).
Главное: отмечать можно только открытое и только то, что мастер разрешил; контур на рисунке мастера игрокам не уходит; всё записывается в ленту."""
import json

import pytest

from app import db, notify, outbox
from conftest import GATE, GM, RIG
from helpers import ok
from test_locmaps import SECRET, SVG, SVG_GM, add, detail, feed, make_map, state, upload

@pytest.fixture(autouse=True)
def clean_tables(started):
    yield
    for table in ("locmap_files", "locmap_feed", "locmap_pins", "outbox"):
        db.conn().execute(f"DELETE FROM {table}")


@pytest.fixture
def telegram_on(monkeypatch):
    monkeypatch.setattr(notify, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(notify, "NOTIFY_DM", True)


TRI = [[100, 100], [300, 100], [200, 250]]
SQUARE = [[400, 400], [500, 400], [500, 500], [400, 500]]


@pytest.fixture
def zones(gm, sandbox):
    """Карта для всех с двумя рисунками и тремя зонами: открытая и разрешённая, открытая и неразрешённая, скрытая."""
    mid = make_map(gm)
    ok(upload(gm, mid, "player"))
    ok(upload(gm, mid, "gm", SVG_GM))
    add(gm, mid, name="Аллея", key="О3", vis="стол", play=True, shape={"player": TRI, "gm": SQUARE}, at={"player": [200, 150], "gm": [450, 450]})
    add(gm, mid, name="Ворота", key="О1", vis="стол", play=False, shape={"player": SQUARE}, at={"player": [450, 450]})
    add(gm, mid, name="Тайник", key="О9", vis="мастер", play=True, shape={"player": [[10, 10], [60, 10], [10, 60]]}, at={"player": [20, 20]})
    return mid


def obj(client, mid, key):
    return next(o for o in detail(client, mid)["objects"] if o["key"] == key)


def mark(client, mid, key, status="cleared", text="", **kw):
    oid = next(o["id"] for o in detail(client, mid)["objects"] if o["key"] == key)
    return client.post(f"/api/locmaps/{mid}/objects/{oid}/mark", json={"status": status, "text": text, **kw})


# ---------------------------------------------------------------- контур зоны

def test_a_zone_outline_is_saved_for_each_drawing_and_rounded(gm, zones):
    o = add(gm, zones, name="Круглая", key="К1", shape={"player": [[10.4, 10.6], [200.5, 10], [100, 150.2], [10, 11]], "gm": TRI})
    assert o["shape"]["player"] == [[10, 11], [200, 10], [100, 150]]          # соседние точки не повторяются, замкнутая точка не нужна
    assert o["shape"]["gm"] == TRI and o["play"] is False


@pytest.mark.parametrize("points, text", [
    ([[1, 1], [5, 5]], "от 3 до"),
    ([[1, 1], [2, 2], [3, 3]], "не должен быть линией"),
    ([[1, 1], [1, 1], [1, 1], [1, 1]], "не должен быть линией"),
    ([[1, 1], [5, 5], [900, 1]], "за край"),
    ([[1, 1], [5, 5], [-3, 8]], "за край"),
    ([[1, 1], [5, 5], ["a", 8]], "два числа"),
    ([[1, 1], [5, 5], [True, 8]], "два числа"),
    ([[1, 1], [5, 5], [3]], "два числа"),
    ([[0, 0]] * 2 + [[i, (i * 7) % 50] for i in range(1, 160)], "от 3 до"),
    ("зона", "от 3 до"), (5, "от 3 до"),
])
def test_bad_outlines_are_refused_with_a_reason(gm, zones, points, text):
    r = gm.post(f"/api/gm/locmaps/{zones}/objects", json={"name": "Плохая", "key": "П1", "shape": {"player": points}})
    assert r.status_code == 400 and text in r.text, r.text
    assert not any(o["key"] == "П1" for o in detail(gm, zones)["objects"])


def test_the_outline_stays_when_other_fields_change_and_can_be_replaced(gm, zones):
    oid = obj(gm, zones, "О3")["id"]
    ok(gm.post(f"/api/gm/locmaps/{zones}/objects", json={"id": oid, "note": "Новое описание"}))
    assert obj(gm, zones, "О3")["shape"] == {"player": TRI, "gm": SQUARE}
    ok(gm.post(f"/api/gm/locmaps/{zones}/objects", json={"id": oid, "shape": {"player": SQUARE, "gm": SQUARE}}))
    assert obj(gm, zones, "О3")["shape"]["player"] == SQUARE
    ok(gm.post(f"/api/gm/locmaps/{zones}/objects", json={"id": oid, "shape": {}}))
    assert obj(gm, zones, "О3")["shape"] == {}                                # пустой контур убирает зону, метка остаётся точкой


def test_players_get_only_the_outline_on_their_drawing_and_never_for_hidden_zones(gm, rig, zones):
    card = obj(rig, zones, "О3")
    assert card["shape"] == {"player": TRI} and card["play"] is True
    assert [o["key"] for o in detail(rig, zones)["objects"]] == ["О3", "О1"]
    text = json.dumps(detail(rig, zones), ensure_ascii=False)
    assert '"gm"' not in text and "gm_note" not in text and SECRET not in text
    assert obj(gm, zones, "О3")["shape"]["gm"] == SQUARE


def test_removing_a_drawing_removes_the_outline_on_it_but_keeps_the_other(gm, zones):
    ok(gm.post(f"/api/gm/locmaps/{zones}/drawing/gm/delete"))
    assert obj(gm, zones, "О3")["shape"] == {"player": TRI}


def test_the_outline_must_fit_the_drawing_it_is_for(gm, sandbox):
    mid = make_map(gm)
    ok(upload(gm, mid, "player", SVG.replace('viewBox="0 0 800 600"', 'viewBox="0 0 300 300"')))
    r = gm.post(f"/api/gm/locmaps/{mid}/objects", json={"name": "Большая", "key": "Б", "shape": {"player": [[10, 10], [500, 10], [10, 200]]}})
    assert r.status_code == 400 and "за край" in r.text


# ---------------------------------------------------------------- отметка зоны игроком

def test_a_player_marks_a_zone_and_everyone_who_sees_it_learns_who_and_when(gm, rig, gate, zones):
    r = mark(rig, zones, "О3", "cleared")
    assert r.status_code == 200 and "расчищено" in r.json()["msg"]
    for who in (gm, rig, gate):
        o = obj(who, zones, "О3")
        assert o["status"] == "cleared" and o["by"] == "rig" and o["date"] == state(gm)["now"]["date"]
    line = next(f for f in feed(gate, zones) if "Аллея" in f)
    assert line == "Риг: «Аллея», расчищено"


def test_a_comment_can_go_with_the_mark_or_alone(gm, rig, zones):
    ok(mark(rig, zones, "О3", "danger", "Слышали собак"))
    assert "Риг: «Аллея», опасно. Слышали собак" in feed(rig, zones)
    ok(mark(rig, zones, "О3", "danger", "Следы свежие"))                      # состояние то же: в ленту идёт только комментарий
    assert "Риг: «Аллея». Следы свежие" in feed(rig, zones)
    assert obj(rig, zones, "О3")["status"] == "danger"
    n = len(feed(rig, zones))
    r = mark(rig, zones, "О3", "danger")                                      # ни нового состояния, ни слов: ничего не пишется
    assert r.status_code == 200 and "уже такое" in r.json()["msg"] and len(feed(rig, zones)) == n


def test_a_player_can_remove_the_mark(gm, rig, zones):
    ok(mark(rig, zones, "О3", "cleared"))
    ok(mark(rig, zones, "О3", ""))
    assert obj(rig, zones, "О3")["status"] == "" and "Риг: «Аллея», отметка снята" in feed(rig, zones)


def test_only_what_the_master_allowed_and_only_what_is_open(gm, rig, zones):
    assert mark(rig, zones, "О1", "cleared").status_code == 403                # открыта, но не разрешена
    assert obj(gm, zones, "О1")["status"] == ""
    oid = obj(gm, zones, "О9")["id"]
    r = rig.post(f"/api/locmaps/{zones}/objects/{oid}/mark", json={"status": "cleared"})
    assert r.status_code == 404 and obj(gm, zones, "О9")["status"] == ""      # скрытая не существует для игрока, даже с разрешением
    assert mark(gm, zones, "О3", "cleared").status_code == 403                 # мастер меняет состояние в карточке метки


def test_a_zone_for_chosen_players_cannot_be_marked_by_others(gm, rig, gate, zones):
    add(gm, zones, name="Для Рига", key="Р", vis="знают", known=["rig"], play=True, shape={"player": TRI})
    oid = obj(gm, zones, "Р")["id"]
    assert gate.post(f"/api/locmaps/{zones}/objects/{oid}/mark", json={"status": "cleared"}).status_code == 404
    ok(mark(rig, zones, "Р", "cleared"))
    assert any("«Для Рига»" in f for f in feed(rig, zones)) and not any("«Для Рига»" in f for f in feed(gate, zones))


@pytest.mark.parametrize("body, code", [
    ({"status": "победа"}, 400), ({"status": None}, 400), ({"status": ["cleared"]}, 400), ({"status": {"a": 1}}, 400),
    ({"status": "cleared", "char": "gate"}, 403), ({"status": "cleared", "char": "нет такого"}, 403),
])
def test_bad_marks_are_refused(gm, rig, zones, body, code):
    oid = obj(gm, zones, "О3")["id"]
    assert rig.post(f"/api/locmaps/{zones}/objects/{oid}/mark", json=body).status_code == code
    assert obj(gm, zones, "О3")["status"] == ""


def test_a_long_comment_is_cut_and_markup_stays_text(gm, rig, zones):
    ok(mark(rig, zones, "О3", "cleared", "<img src=x onerror=alert(1)> " + "я" * 400))
    line = next(f for f in feed(rig, zones) if "Аллея" in f)
    assert len(line.split(". ", 1)[1]) == 120 and "<img" in line


def test_login_is_needed_and_a_missing_map_or_mark_is_a_clean_404(anon, rig, gm, zones):
    oid = obj(gm, zones, "О3")["id"]
    assert anon.post(f"/api/locmaps/{zones}/objects/{oid}/mark", json={"status": "cleared"}).status_code == 401
    assert rig.post(f"/api/locmaps/нет/objects/{oid}/mark", json={"status": "cleared"}).status_code == 404
    assert rig.post(f"/api/locmaps/{zones}/objects/нет/mark", json={"status": "cleared"}).status_code == 404


def test_the_master_is_told_in_telegram_and_players_are_not(gm, rig, gate, zones, telegram_on):
    db.conn().execute("DELETE FROM outbox")
    ok(mark(rig, zones, "О3", "cleared", "Чисто"))
    row = next(r for r in outbox.pending(GM) if r["kind"] == "map")
    assert "Риг: «Аллея», расчищено. Чисто" in row["text"] and "«Роща»" in row["text"] and row["section"] == "maps"
    assert not any(r["kind"] == "map" for r in outbox.pending(RIG)) and not any(r["kind"] == "map" for r in outbox.pending(GATE))


def test_the_master_changes_a_state_too_and_the_author_follows(gm, rig, zones):
    oid = obj(gm, zones, "О3")["id"]
    ok(gm.post(f"/api/gm/locmaps/{zones}/objects", json={"id": oid, "status": "found"}))
    assert (obj(gm, zones, "О3")["by"], obj(gm, zones, "О3")["status"]) == ("gm", "found")
    ok(mark(rig, zones, "О3", "cleared"))
    assert obj(gm, zones, "О3")["by"] == "rig"
    ok(gm.post(f"/api/gm/locmaps/{zones}/objects", json={"id": oid, "status": ""}))
    assert (obj(gm, zones, "О3")["by"], obj(gm, zones, "О3")["date"]) == ("", "")
    ok(gm.post(f"/api/gm/locmaps/{zones}/objects", json={"id": oid, "by": "rig", "date": "2001-01-01"}))   # поддельные значения не принимаются
    assert (obj(gm, zones, "О3")["by"], obj(gm, zones, "О3")["date"]) == ("", "")


def test_players_have_no_way_to_grant_themselves_the_right(gm, rig, zones):
    oid = obj(gm, zones, "О1")["id"]
    for url in (f"/api/gm/locmaps/{zones}/objects", f"/api/gm/locmaps/{zones}/import"):
        assert rig.post(url, json={"id": oid, "play": True, "objects": [{"key": "О1", "name": "Ворота", "play": True}]}).status_code == 403
    assert obj(gm, zones, "О1")["play"] is False


# ---------------------------------------------------------------- загрузка списком

ZONES_JSON = [{"key": "З1", "name": "Зона 1", "kind": "area", "play": True, "shape": {"player": TRI, "gm": SQUARE}, "at": {"player": [200, 150]}},
              {"key": "З2", "name": "Зона 2", "kind": "area", "shape": {"player": SQUARE}}]


def test_import_brings_outlines_and_the_right_to_mark_and_they_do_not_change_on_repeat(gm, zones):
    rep = ok(gm.post(f"/api/gm/locmaps/{zones}/import", json={"objects": ZONES_JSON}))["report"]
    assert (rep["add"], rep["error"]) == (2, 0)
    z1 = obj(gm, zones, "З1")
    assert z1["shape"] == {"player": TRI, "gm": SQUARE} and z1["play"] is True and z1["vis"] == "мастер"
    again = ok(gm.post(f"/api/gm/locmaps/{zones}/import", json={"objects": ZONES_JSON}))["report"]
    assert (again["add"], again["update"], again["skip"]) == (0, 0, 2)
    changed = [dict(ZONES_JSON[0], shape={"gm": TRI})]                          # новый контур для одного рисунка дополняет, а не стирает прежний
    assert ok(gm.post(f"/api/gm/locmaps/{zones}/import", json={"objects": changed}))["report"]["update"] == 1
    assert obj(gm, zones, "З1")["shape"] == {"player": TRI, "gm": TRI}


def test_import_can_open_new_zones_at_once_with_one_line_in_the_feed(gm, rig, zones):
    rep = ok(gm.post(f"/api/gm/locmaps/{zones}/import", json={"objects": ZONES_JSON, "open": True}))["report"]
    assert rep["add"] == 2 and all("открыта игрокам" in i["msg"] for i in rep["items"])
    assert obj(rig, zones, "З1")["play"] is True and obj(rig, zones, "З2")["shape"] == {"player": SQUARE}
    assert feed(rig, zones).count("Открыто на карте: 2 метки") == 1
    ok(mark(rig, zones, "З1", "cleared"))
    again = ok(gm.post(f"/api/gm/locmaps/{zones}/import", json={"objects": ZONES_JSON, "open": True}))["report"]
    assert again["add"] == 0 and obj(gm, zones, "З1")["status"] == "cleared"   # существующие метки не открываются и не сбрасываются повторной загрузкой
    assert not [f for f in feed(rig, zones) if f.startswith("Открыто на карте: 0")]


def test_old_marks_without_zone_fields_are_still_skipped_when_nothing_changed(gm, zones):
    ok(gm.post(f"/api/gm/locmaps/{zones}/import", json={"objects": [{"key": "С1", "name": "Старая", "kind": "thing", "at": {"player": [30, 30]}}]}))
    items = db.items("locmaps")
    for m in items:
        for o in m.get("objects", []):
            for k in ("play", "shape", "by", "date"):
                o.pop(k, None)
    db.set_items("locmaps", items)
    again = ok(gm.post(f"/api/gm/locmaps/{zones}/import", json={"objects": [{"key": "С1", "name": "Старая", "kind": "thing", "at": {"player": [30, 30]}}]}))["report"]
    assert (again["skip"], again["update"]) == (1, 0)
    detail(gm, zones)                                                          # метки старого вида читаются
    assert obj(gm, zones, "С1")["name"] == "Старая"
