"""Панель мастера: время, этапы, план и маски, хроника, места, районы."""
from helpers import ok


def test_time_controls(gm):
    before = gm.get("/api/state").json()
    d0, tod0, quiet0 = before["now"]["date"], before["now"]["tod"], before["quietUntil"]
    try:
        assert ok(gm.post("/api/gm/time", json={"shift": 3}))["state"]["now"]["date"] > d0
        for bad in ({"shift": 401}, {"shift": "abc"}, {"shift": None}, {"date": "2076-01-01"}, {"date": "2075-02-30"},
                    {"date": 20750801}, {"tod": "полдень"}, {"quiet": "вчера"}):
            assert gm.post("/api/gm/time", json=bad).status_code == 400, bad
        ok(gm.post("/api/gm/time", json={"date": before["calEnd"]}))
        assert ok(gm.post("/api/gm/time", json={"shift": 100}))["state"]["now"]["date"] == before["calEnd"]  # не за край календаря
        assert ok(gm.post("/api/gm/time", json={"quiet": ""}))["state"]["quietUntil"] == ""
    finally:
        gm.post("/api/gm/time", json={"date": d0, "tod": tod0, "quiet": quiet0})


def test_clock_crud(gm):
    data = ok(gm.post("/api/gm/items/clocks", json={"title": "Таймер", "when": "2075-09-01", "note": "n"}))
    cid = next(c["id"] for c in data["state"]["clocks"] if c["title"] == "Таймер")
    assert gm.post("/api/gm/items/clocks", json={"id": "нет", "title": "x"}).status_code == 404
    assert gm.post("/api/gm/items/zzz", json={}).status_code == 404
    assert gm.post(f"/api/gm/items/clocks/{cid}/delete").status_code == 200
    assert gm.post(f"/api/gm/items/clocks/{cid}/delete").status_code == 404


def test_windows_may_not_overlap(gm):
    w = gm.get("/api/state").json()["windows"][0]
    r = gm.post("/api/gm/items/windows", json={"name": "Дубль", "from": w["from"], "to": w["to"]})
    assert r.status_code == 400 and "пересека" in r.text
    assert gm.post("/api/gm/items/windows", json={"name": "Задом наперёд", "from": "2075-12-31", "to": "2075-12-30"}).status_code == 400


def test_plan_mask_and_played(gm, rig, hag):
    body = {"title": "Тайный план", "from": "2075-09-01", "to": "2075-09-02", "note": "СЕКРЕТ-детали",
            "cover": {"title": "Маска", "note": "m", "who": ["rig"]}}
    data = ok(gm.post("/api/gm/items/plan", json=body))
    pid = next(p["id"] for p in data["state"]["plan"] if p["title"] == "Тайный план")
    try:
        assert "Маска" in {b["title"] for b in rig.get("/api/state").json()["blocks"]}
        assert "Маска" not in {b["title"] for b in hag.get("/api/state").json()["blocks"]}
        assert "СЕКРЕТ" not in rig.get("/api/state").text
        data = ok(gm.post(f"/api/gm/plan/{pid}/played"))
        past = next(p for p in data["state"]["past"] if p["title"] == "Тайный план")
        assert past["gm_note"] == "СЕКРЕТ-детали"                # мастер видит заметку
        assert "СЕКРЕТ" not in rig.get("/api/state").text        # игрок не видит
        assert gm.post(f"/api/gm/plan/{pid}/played").status_code == 404
    finally:
        for p in gm.get("/api/state").json()["past"]:
            if p["title"] == "Тайный план":
                gm.post(f"/api/gm/items/past/{p['id']}/delete")
        gm.post(f"/api/gm/items/plan/{pid}/delete")


def test_place_must_be_inside_the_map(gm):
    assert gm.post("/api/gm/items/places", json={"name": "Далеко", "x": 10 ** 9, "y": 5}).status_code == 400
    assert gm.post("/api/gm/items/places", json={"name": "Без координат"}).status_code == 400
    assert gm.post("/api/gm/items/places", json={"name": "Отрицательно", "x": -5, "y": 5}).status_code == 400


def test_known_only_needs_characters(gm):
    for kind, body in (("places", {"name": "М", "x": 1, "y": 1, "vis": "знают", "known": []}),
                       ("dossier", {"name": "К", "vis": "знают", "known": []}),
                       ("handouts", {"title": "Р", "date": "2075-08-01", "vis": "знают", "known": []})):
        assert gm.post(f"/api/gm/items/{kind}", json=body).status_code == 400, kind


def test_district_notes(gm, rig):
    assert gm.post("/api/gm/district/нет-такого", json={"text": "x"}).status_code == 404
    before = next(d for d in gm.get("/api/state").json()["dnotes"] if d["id"] == "downtown")
    try:
        ok(gm.post("/api/gm/district/downtown", json={"text": "Новый текст", "gm_text": "СЕКРЕТ-новое"}))
        note = next(d for d in rig.get("/api/state").json()["dnotes"] if d["id"] == "downtown")
        assert note == {"id": "downtown", "text": "Новый текст"}
    finally:
        gm.post("/api/gm/district/downtown", json={"text": before["text"], "gm_text": before["gm_text"]})


def test_state_version_short_circuit(gm):
    state = gm.get("/api/state").json()
    assert gm.get(f"/api/state?since={state['version']}").json() == {"unchanged": True}
    assert "now" in gm.get(f"/api/state?since={state['version'] - 1}").json()


def test_dossier_editing_keeps_image_and_fact_ids(gm):
    card = next(c for c in gm.get("/api/state").json()["dossier"] if c["id"] == "n1")
    ok(gm.post("/api/gm/items/dossier", json=dict(card, role="Новая роль")))
    again = next(c for c in gm.get("/api/state").json()["dossier"] if c["id"] == "n1")
    try:
        assert again["role"] == "Новая роль"
        assert [f["id"] for f in again["facts"]] == [f["id"] for f in card["facts"]]
    finally:
        gm.post("/api/gm/items/dossier", json=dict(card))


def travel(**kw):
    body = {"name": "Метролинк", "kind": "roads", "motorway": 90, "trunk": 70, "primary": 45, "off": 18, "delay": 5, "wall": 12, "vis": "стол", "note": "n"}
    body.update(kw)
    return body


def test_default_travel_profiles_are_seeded(gm, rig):
    names = [t["name"] for t in gm.get("/api/state").json()["travel"]]
    assert {"Пешком", "Автомобиль", "Вертолёт"} <= set(names)
    heli = next(t for t in gm.get("/api/state").json()["travel"] if t["name"] == "Вертолёт")
    assert heli["kind"] == "straight" and heli["off"] > 100
    assert [t["name"] for t in rig.get("/api/state").json()["travel"]] == names


def test_travel_crud_and_visibility(gm, rig, anon):
    data = ok(gm.post("/api/gm/items/travel", json=travel(name="Секретный катер", vis="мастер")))
    tid = next(t["id"] for t in data["state"]["travel"] if t["name"] == "Секретный катер")
    try:
        assert "Секретный катер" not in str(rig.get("/api/state").json()["travel"])        # скрытый вид игрок не видит
        ok(gm.post("/api/gm/items/travel", json=travel(id=tid, name="Секретный катер", vis="стол", motorway="0", off="33.5")))
        shown = next(t for t in rig.get("/api/state").json()["travel"] if t["id"] == tid)
        assert shown["off"] == 33.5 and shown["motorway"] == 0
        assert rig.post("/api/gm/items/travel", json=travel()).status_code == 403
        assert rig.post(f"/api/gm/items/travel/{tid}/delete").status_code == 403
    finally:
        gm.post(f"/api/gm/items/travel/{tid}/delete")
    assert all(t["id"] != tid for t in gm.get("/api/state").json()["travel"])


def test_travel_validation(gm):
    bad = [
        travel(name=""),
        travel(off=0),                                         # без скорости вне дорог нельзя
        travel(off="быстро"),
        travel(motorway=-1),
        travel(motorway=99999),
        travel(motorway="nan"),
        travel(delay=-5),
        travel(wall=1441),
        travel(motorway=0, trunk=0, primary=0),                # «по дорогам» без единой дороги
        travel(motorway=True),
        travel(primary=[40]),
    ]
    for body in bad:
        r = gm.post("/api/gm/items/travel", json=body)
        assert r.status_code == 400, (body, r.status_code, r.text[:100])
    # «по прямой»: дорожные скорости не нужны
    data = ok(gm.post("/api/gm/items/travel", json=travel(name="Дрон", kind="straight", motorway=0, trunk=0, primary=0, off=120)))
    tid = next(t["id"] for t in data["state"]["travel"] if t["name"] == "Дрон")
    gm.post(f"/api/gm/items/travel/{tid}/delete")


def test_travel_profiles_are_limited(gm):
    created = []
    try:
        for i in range(30):
            r = gm.post("/api/gm/items/travel", json=travel(name=f"Вид {i}"))
            if r.status_code != 200:
                assert r.status_code == 400 and "не больше" in r.text
                break
            created.append(next(t["id"] for t in r.json()["state"]["travel"] if t["name"] == f"Вид {i}"))
        else:
            raise AssertionError("лимит видов транспорта не сработал")
        assert len(gm.get("/api/state").json()["travel"]) == 12
    finally:
        for tid in created:
            gm.post(f"/api/gm/items/travel/{tid}/delete")
