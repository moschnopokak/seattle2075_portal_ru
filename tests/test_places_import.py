"""Импорт мест на карту: пакетное добавление (набор из «Seattle 2072», KML), фоновые места и новые типы мест."""
import json
from pathlib import Path

import pytest

from helpers import ok

MAP_DIR = Path(__file__).resolve().parent.parent / "static" / "map"
POI = json.loads((MAP_DIR / "poi_seattle2072.json").read_text(encoding="utf-8"))
URL = "/api/gm/places/import"
NEW_TYPES = ("medical", "security", "shop", "leisure")


def spot(i, **kw):
    body = {"name": f"Импорт {i}", "type": "shop", "x": 30000 + i, "y": 40000, "vis": "стол", "known": [], "note": "заметка", "gm_note": "для мастера", "bg": True}
    body.update(kw)
    return body


def places(client):
    return client.get("/api/state").json()["places"]


def imported(client, prefix="Импорт "):
    return [p for p in places(client) if p["name"].startswith(prefix)]


# ---------------------------------------------------------------- что приходит и что видят игроки

def test_import_adds_all_places_at_once(gm, sandbox):
    before = len(places(gm))
    data = ok(gm.post(URL, json={"items": [spot(i) for i in range(5)]}))
    assert data["msg"] == "Добавлено мест: 5"
    assert len(data["state"]["places"]) == before + 5
    new = imported(gm)
    assert len({p["id"] for p in new}) == 5 and all(p["id"].startswith("m") for p in new)
    assert all(p["bg"] is True and p["type"] == "shop" for p in new)


def test_existing_places_are_not_touched(gm, sandbox):
    old = places(gm)
    ok(gm.post(URL, json={"items": [spot(1)]}))
    assert [p for p in places(gm) if p["id"] in {o["id"] for o in old}] == old


def test_visibility_rules_apply_to_imported_places(gm, rig, gate, sandbox):
    ok(gm.post(URL, json={"items": [
        spot(1, name="Импорт общий"),
        spot(2, name="Импорт скрытый", vis="мастер", gm_note="СЕКРЕТ-импорт"),
        spot(3, name="Импорт для Рига", vis="знают", known=["rig"]),
    ]}))
    seen_by_rig = {p["name"] for p in imported(rig)}
    seen_by_gate = {p["name"] for p in imported(gate)}
    assert seen_by_rig == {"Импорт общий", "Импорт для Рига"}
    assert seen_by_gate == {"Импорт общий"}
    assert "СЕКРЕТ" not in rig.get("/api/state").text and "СЕКРЕТ" not in gate.get("/api/state").text
    assert all("gm_note" not in p for p in imported(rig))                       # заметка мастера игроку не уходит
    assert {p["name"] for p in imported(gm)} == {"Импорт общий", "Импорт скрытый", "Импорт для Рига"}


def test_players_get_the_background_flag(gm, rig, sandbox):
    ok(gm.post(URL, json={"items": [spot(1, bg=True, name="Импорт фон"), spot(2, bg=False, name="Импорт обычное")]}))
    flags = {p["name"]: p["bg"] for p in imported(rig)}
    assert flags == {"Импорт фон": True, "Импорт обычное": False}


# ---------------------------------------------------------------- типы и фон при обычном сохранении

@pytest.mark.parametrize("kind", NEW_TYPES)
def test_new_place_types_are_accepted(gm, rig, sandbox, kind):
    data = ok(gm.post("/api/gm/items/places", json={"name": f"Тип {kind}", "type": kind, "x": 31000, "y": 41000, "vis": "стол", "bg": True}))
    place = next(p for p in data["state"]["places"] if p["name"] == f"Тип {kind}")
    assert place["type"] == kind and place["bg"] is True


def test_unknown_type_falls_back_to_other_and_bg_must_be_a_real_boolean(gm, sandbox):
    data = ok(gm.post("/api/gm/items/places", json={"name": "Тип неизвестный", "type": "spaceport", "x": 31000, "y": 41000, "bg": "yes"}))
    place = next(p for p in data["state"]["places"] if p["name"] == "Тип неизвестный")
    assert place["type"] == "other" and place["bg"] is False
    data = ok(gm.post("/api/gm/items/places", json={"name": "Тип единица", "x": 31000, "y": 41000, "bg": 1}))
    assert next(p for p in data["state"]["places"] if p["name"] == "Тип единица")["bg"] is False


def test_bg_survives_an_edit(gm, sandbox):
    data = ok(gm.post("/api/gm/items/places", json={"name": "Тип правка", "x": 31000, "y": 41000, "bg": True}))
    place = next(p for p in data["state"]["places"] if p["name"] == "Тип правка")
    data = ok(gm.post("/api/gm/items/places", json=dict(place, note="новое описание")))
    assert next(p for p in data["state"]["places"] if p["id"] == place["id"])["bg"] is True


# ---------------------------------------------------------------- проверки

@pytest.mark.parametrize("items", [None, [], "строка", {"a": 1}, 5])
def test_nothing_to_import_is_refused(gm, items):
    assert gm.post(URL, json={"items": items}).status_code == 400


def test_missing_items_key_and_garbage_bodies(gm):
    assert gm.post(URL, json={}).status_code == 400
    for content in (b"not json", b"[1,2]", b"null", b'{"items": 1e999}', b""):
        assert gm.post(URL, content=content, headers={"Content-Type": "application/json"}).status_code < 500


def test_more_than_the_limit_at_once_is_refused(gm, sandbox):
    before = len(places(gm))
    r = gm.post(URL, json={"items": [spot(i) for i in range(601)]})
    assert r.status_code == 400 and "не больше 600" in r.text
    assert len(places(gm)) == before


def test_one_bad_place_rejects_the_whole_import_and_names_it(gm, sandbox):
    before = len(places(gm))
    r = gm.post(URL, json={"items": [spot(1), spot(2, x=10 ** 9, name="Далеко"), spot(3)]})
    assert r.status_code == 400 and "Место №2" in r.text and "Далеко" in r.text
    r = gm.post(URL, json={"items": [spot(1), "не место"]})
    assert r.status_code == 400 and "Место №2" in r.text
    r = gm.post(URL, json={"items": [spot(1), spot(2, name="")]})
    assert r.status_code == 400
    r = gm.post(URL, json={"items": [spot(1), spot(2, vis="знают", known=[])]})
    assert r.status_code == 400
    assert len(places(gm)) == before                                              # ничего не добавилось


def test_total_number_of_places_is_capped(gm, sandbox, monkeypatch):
    from app import logic
    now = len(places(gm))
    monkeypatch.setitem(logic.MAX_ITEMS, "places", now + 2)
    r = gm.post(URL, json={"items": [spot(i) for i in range(3)]})
    assert r.status_code == 409 and "не больше" in r.text
    assert len(places(gm)) == now
    ok(gm.post(URL, json={"items": [spot(i) for i in range(2)]}))
    assert gm.post("/api/gm/items/places", json={"name": "Лишнее", "x": 31000, "y": 41000}).status_code == 409


# ---------------------------------------------------------------- журнал

def test_import_is_one_record_in_the_history_and_cannot_be_reverted(gm, sandbox):
    ok(gm.post(URL, json={"items": [spot(i) for i in range(4)]}))
    items = ok(gm.get("/api/gm/history"))["items"]
    rec = next(h for h in items if h["action"] == "import")
    assert rec["kind"] == "places" and rec["title"] == "Импорт мест: 4" and rec["role"] == "gm"
    assert sum(1 for h in items if h["action"] == "import") >= 1
    assert gm.post(f"/api/gm/history/{rec['id']}/revert").status_code == 400
    assert len(imported(gm)) == 4


def test_imported_places_can_be_deleted_to_the_trash_and_restored(gm, sandbox):
    ok(gm.post(URL, json={"items": [spot(1)]}))
    pid = imported(gm)[0]["id"]
    ok(gm.post(f"/api/gm/items/places/{pid}/delete"))
    assert not imported(gm)
    tid = next(t["id"] for t in ok(gm.get("/api/gm/trash"))["items"] if t["title"] == "Импорт 1")
    ok(gm.post(f"/api/gm/trash/{tid}/restore"))
    assert imported(gm)[0]["bg"] is True


# ---------------------------------------------------------------- наборы данных, которые лежат в static/map

def test_whole_canon_set_imports_cleanly(gm, sandbox):
    """Каждая точка набора проходит ту же проверку, что и ручное добавление, и весь набор влезает в одну операцию."""
    items = POI["items"]
    assert 100 < len(items) <= 600
    payload = [{"name": i["name"], "type": i["type"], "x": i["x"], "y": i["y"], "vis": "стол", "known": [], "note": i.get("note", ""),
                "gm_note": i.get("gm_note", ""), "bg": bool(i.get("bg"))} for i in items]
    before = len(places(gm))
    data = ok(gm.post(URL, json={"items": payload}))
    assert data["msg"] == f"Добавлено мест: {len(items)}"
    new = data["state"]["places"][before:]
    assert [p["name"] for p in new] == [i["name"] for i in items]
    assert [p["type"] for p in new] == [i["type"] for i in items]                   # ни один тип не превратился в «other» по ошибке
    assert [bool(p["bg"]) for p in new] == [bool(i.get("bg")) for i in items]


def test_canon_set_is_well_formed():
    from app.logic import PLACE_TYPES
    ids = [i["id"] for i in POI["items"]]
    assert len(set(ids)) == len(ids)
    for i in POI["items"]:
        assert i["type"] in PLACE_TYPES and isinstance(i["group"], str) and i["group"], i["id"]
        assert isinstance(i["same"], list) and all(isinstance(k, list) and all(isinstance(w, str) for w in k) for k in i["same"]), i["id"]
        assert len(i["name"]) <= 80 and len(i.get("note", "")) <= 2000 and len(i.get("gm_note", "")) <= 2000, i["id"]


def test_coordinate_grid_for_kml_is_consistent():
    grid = json.loads((MAP_DIR / "llgrid.json").read_text(encoding="utf-8"))
    assert grid["nx"] * grid["ny"] == len(grid["x"]) == len(grid["y"])
    assert grid["step"] > 0 and -180 < grid["lon0"] < 180 and -90 < grid["lat0"] < 90


def test_license_of_the_third_party_data_ships_with_it():
    text = (MAP_DIR / "POI_LICENSE.txt").read_text(encoding="utf-8")
    assert "skiant/seattle-2072-map" in text and "MIT License" in text and "Mathieu Dubois" in text
    assert "MIT" in POI["source"]


def test_static_map_files_are_served(anon):
    for name in ("poi_seattle2072.json", "llgrid.json", "map.json"):
        r = anon.get(f"/static/map/{name}")
        assert r.status_code == 200 and r.json(), name
