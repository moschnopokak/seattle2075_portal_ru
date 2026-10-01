"""Лист персонажа (Shadowrun): нуйены, фракции, репутация, контакты. Кто что видит, кто что может, проверки ввода, корзина и журнал."""
import json

import pytest

from app import logic
from helpers import ok

SECRET = "СЕКРЕТ"


def add(gm, section, **body):
    """Создать запись раздела и вернуть её (у фракций в теле есть своё поле kind, поэтому раздел зовётся section)."""
    data = ok(gm.post(f"/api/gm/items/{section}", json=body), section)
    return data["state"][section][-1]


def find(state, kind, **match):
    return next((x for x in state[kind] if all(x.get(k) == v for k, v in match.items())), None)


@pytest.fixture
def world(gm, sandbox):
    """Три фракции (открытая, для Рига, скрытая), репутация, нуйены и контакты у Рига и Гейта."""
    w = {}
    for key, vis, known in (("open", "стол", []), ("rig", "знают", ["rig"]), ("hidden", "мастер", [])):
        w[key] = add(gm, "factions", name=f"Фракция {key}", kind="corp", vis=vis, known=known, note=f"Публично о {key}", gm_note=f"{SECRET}-фракция-{key}")["id"]
    for char, key, value in (("rig", "open", 2), ("rig", "rig", -3), ("rig", "hidden", 5), ("gate", "open", 1), ("gate", "rig", 4)):
        add(gm, "standing", char=char, faction=w[key], value=value, note=f"Заметка {char}-{key}", gm_note=f"{SECRET}-репутация")
    for char, delta, note in (("rig", 1500, "Награда"), ("rig", -200, "Ремонт"), ("gate", 100, "Подарок")):
        add(gm, "money", char=char, delta=delta, note=note, gm_note=f"{SECRET}-деньги")
    add(gm, "contacts", char="rig", name="Фиксер Ли", card="n2", connection=4, loyalty=2, services="Достаёт железо", note="Видно игроку", gm_note=f"{SECRET}-контакт")
    add(gm, "contacts", char="gate", name="Врач", card="n2", connection=3, loyalty=3, note="", gm_note="")
    add(gm, "contacts", char="rig", name="Просто знакомый", connection=1, loyalty=1)
    return w


def state(client):
    return ok(client.get("/api/state"))


# ---------------------------------------------------------------- кто что видит

def test_player_sees_only_his_own_sheet_and_no_gm_notes(world, rig):
    s = state(rig)
    assert {m["char"] for m in s["money"]} == {"rig"} and sorted(m["delta"] for m in s["money"]) == [-200, 1500]
    assert {x["char"] for x in s["standing"]} == {"rig"} and {x["char"] for x in s["contacts"]} == {"rig"}
    assert SECRET not in json.dumps({k: s[k] for k in ("money", "factions", "standing", "contacts")}, ensure_ascii=False)
    for row in s["money"]:
        assert set(row) == {"id", "char", "delta", "note", "date"}                    # без заголовка и заметки мастера
    for row in s["standing"]:
        assert set(row) == {"id", "char", "faction", "value", "note"}


def test_factions_follow_the_visibility_rules(world, rig, gate, hag):
    names = lambda client: {f["name"] for f in state(client)["factions"]}
    assert names(rig) == {"Фракция open", "Фракция rig"}                              # открытая и «знают Риг», скрытой нет
    assert names(gate) == {"Фракция open"}
    assert names(hag) == {"Фракция open"}
    # репутация у фракции, которой персонаж не знает, не показывается, даже если мастер её записал
    assert {x["faction"] for x in state(rig)["standing"]} == {world["open"], world["rig"]}
    assert {x["faction"] for x in state(gate)["standing"]} == {world["open"]}
    assert state(hag)["standing"] == [] and state(hag)["money"] == [] and state(hag)["contacts"] == []


def test_contact_link_to_a_card_only_when_the_player_can_see_that_card(world, rig, gate):
    rig_contacts = {c["name"]: c for c in state(rig)["contacts"]}
    gate_contacts = {c["name"]: c for c in state(gate)["contacts"]}
    assert "card" not in rig_contacts["Фиксер Ли"]                                    # n2 открыта только Гейту
    assert gate_contacts["Врач"]["card"] == "n2"
    assert "card" not in rig_contacts["Просто знакомый"]


def test_gm_sees_everything(world, gm):
    s = state(gm)
    assert len(s["money"]) == 3 and len(s["factions"]) == 3 and len(s["standing"]) == 5 and len(s["contacts"]) == 3
    assert any(SECRET in json.dumps(x, ensure_ascii=False) for x in s["money"])


def test_players_cannot_write_and_strangers_cannot_read(world, rig, gate, anon):
    for kind, body in (("money", {"char": "rig", "delta": 10**6}), ("factions", {"name": "Моя", "vis": "стол"}),
                       ("standing", {"char": "rig", "faction": world["open"], "value": 5}),
                       ("contacts", {"char": "rig", "name": "Друг", "connection": 12, "loyalty": 6})):
        assert rig.post(f"/api/gm/items/{kind}", json=body).status_code == 403
    mine = state(rig)["money"][0]
    assert rig.post(f"/api/gm/items/money/{mine['id']}/delete").status_code == 403
    assert rig.post("/api/gm/items/money", json={"id": mine["id"], "char": "rig", "delta": 10**6}).status_code == 403
    assert anon.get("/api/state").status_code == 401


def test_gm_previewing_as_a_player_still_gets_everything_from_the_server_but_not_in_player_state(world, rig):
    # состояние игрока никогда не содержит чужого, что бы ни показывал мастер у себя
    s = json.dumps(state(rig), ensure_ascii=False)
    assert "Врач" not in s and "Подарок" not in s


# ---------------------------------------------------------------- проверки ввода

@pytest.mark.parametrize("body", [
    {"char": "", "delta": 5}, {"char": "нет", "delta": 5}, {"char": None, "delta": 5}, {"char": ["rig"], "delta": 5}, {"char": {"a": 1}, "delta": 5},
    {"char": "rig", "delta": 0}, {"char": "rig", "delta": "много"}, {"char": "rig", "delta": None}, {"char": "rig", "delta": True},
    {"char": "rig", "delta": [1]}, {"char": "rig", "delta": 10**10}, {"char": "rig", "delta": -10**10}, {"char": "rig", "delta": 1.5},
    {"char": "rig", "delta": 5, "date": "2075-02-30"}, {"char": "rig", "delta": 5, "date": "1999-01-01"}, {"char": "rig", "delta": 5, "date": 5},
])
def test_bad_money_is_refused_not_a_server_error(world, gm, body):
    r = gm.post("/api/gm/items/money", json=body)
    assert r.status_code == 400, (body, r.status_code, r.text[:120])


def test_money_defaults_and_text_cleanup(world, gm):
    m = add(gm, "money", char="gate", delta="2500", note="  много\nстрок  " + "я" * 300)
    assert m["delta"] == 2500 and m["date"] == state(gm)["now"]["date"] and "\n" not in m["note"] and len(m["note"]) <= 200
    assert m["title"].startswith("Гейт: +2 500 ¥")
    spent = add(gm, "money", char="gate", delta=-40)
    assert spent["title"] == "Гейт: −40 ¥"


@pytest.mark.parametrize("body", [
    {"char": "rig", "faction": "нет", "value": 1}, {"char": "rig", "faction": None, "value": 1}, {"char": "rig", "faction": ["x"], "value": 1},
    {"char": "rig", "faction": "OPEN", "value": 6}, {"char": "rig", "faction": "OPEN", "value": -6}, {"char": "rig", "faction": "OPEN", "value": "x"},
    {"char": "rig", "faction": "OPEN", "value": None}, {"char": "rig", "faction": "OPEN", "value": 1.5}, {"char": "x", "faction": "OPEN", "value": 1},
])
def test_bad_standing_is_refused(world, gm, body):
    if body["faction"] == "OPEN":
        body = dict(body, faction=world["open"])
    r = gm.post("/api/gm/items/standing", json=body)
    assert r.status_code == 400, (body, r.status_code)


def test_infinity_and_odd_json_never_crash_the_server(world, gm):
    for raw in ('{"char":"rig","delta":Infinity}', '{"char":"rig","delta":NaN}', '{"char":"rig","delta":1e999}', '[1,2]', '"строка"', 'null'):
        r = gm.post("/api/gm/items/money", content=raw.encode(), headers={"content-type": "application/json"})
        assert r.status_code in (400, 422), (raw, r.status_code)
    for body in ({"name": ["Х"]}, {"name": {"a": 1}}):
        assert gm.post("/api/gm/items/factions", json=dict(body, vis="стол")).status_code in (200, 400)


def test_one_standing_per_character_and_faction(world, gm):
    r = gm.post("/api/gm/items/standing", json={"char": "rig", "faction": world["open"], "value": 4})
    assert r.status_code == 409 and "уже записана" in r.json()["detail"]
    existing = find(state(gm), "standing", char="rig", faction=world["open"])
    again = ok(gm.post("/api/gm/items/standing", json={"id": existing["id"], "char": "rig", "faction": world["open"], "value": 4}))      # правка себя допустима
    assert find(again["state"], "standing", id=existing["id"])["value"] == 4
    assert gm.post("/api/gm/items/standing", json={"char": "karu", "faction": world["open"], "value": 1}).status_code == 200


@pytest.mark.parametrize("body", [
    {"char": "rig", "name": "", "connection": 3, "loyalty": 3}, {"char": "rig", "name": "Х", "connection": 0, "loyalty": 3},
    {"char": "rig", "name": "Х", "connection": 13, "loyalty": 3}, {"char": "rig", "name": "Х", "connection": 3, "loyalty": 0},
    {"char": "rig", "name": "Х", "connection": 3, "loyalty": 7}, {"char": "rig", "name": "Х", "connection": "а", "loyalty": 3},
    {"char": "rig", "name": "Х", "connection": 3, "loyalty": None}, {"char": "rig", "name": "Х", "connection": 3, "loyalty": 3, "card": "нет"},
    {"char": "rig", "name": "Х", "connection": 3, "loyalty": 3, "card": ["n1"]},
])
def test_bad_contacts_are_refused(world, gm, body):
    assert gm.post("/api/gm/items/contacts", json=body).status_code == 400


def test_contact_name_comes_from_the_card_when_empty(world, gm):
    c = add(gm, "contacts", char="rig", name="", card="n1", connection=2, loyalty=2)
    assert c["name"] == "Открытая карточка" and c["card"] == "n1"


@pytest.mark.parametrize("body", [
    {"name": ""}, {"name": "Х", "vis": "знают", "known": []}, {"name": "Х", "vis": "знают", "known": ["нет"]},
])
def test_bad_factions_are_refused(world, gm, body):
    assert gm.post("/api/gm/items/factions", json=body).status_code == 400


def test_faction_defaults_to_hidden_and_unknown_kind_becomes_other(world, gm):
    f = add(gm, "factions", name="Новая", kind="что-то")
    assert f["vis"] == "мастер" and f["kind"] == "other"


def test_item_count_caps(world, gm, monkeypatch):
    monkeypatch.setitem(logic.MAX_ITEMS, "money", len(state(gm)["money"]))
    r = gm.post("/api/gm/items/money", json={"char": "rig", "delta": 1})
    assert r.status_code == 409 and "предел" in r.json()["detail"]


# ---------------------------------------------------------------- журнал, корзина, связи

def test_money_edit_history_and_revert(world, gm):
    m = find(state(gm), "money", char="gate", delta=100)
    ok(gm.post("/api/gm/items/money", json={"id": m["id"], "char": "gate", "delta": 150, "note": "Подарок и ещё"}))
    hist = ok(gm.get("/api/gm/history?kind=money&limit=20"))["items"]
    edit = next(h for h in hist if h["action"] == "edit" and h["item_id"] == m["id"])
    assert {"delta"} <= {c["field"] for c in edit["changes"]}
    ok(gm.post(f"/api/gm/history/{edit['id']}/revert"))
    assert find(state(gm), "money", id=m["id"])["delta"] == 100


def test_deleted_items_go_to_the_trash_and_come_back(world, gm, rig):
    m = find(state(gm), "money", char="rig", delta=-200)
    ok(gm.post(f"/api/gm/items/money/{m['id']}/delete"))
    assert find(state(gm), "money", id=m["id"]) is None and sorted(x["delta"] for x in state(rig)["money"]) == [1500]
    t = next(t for t in ok(gm.get("/api/gm/trash"))["items"] if t["kind"] == "money" and "Ремонт" in t["title"])
    assert t["title"].startswith("Риг: −200")
    ok(gm.post(f"/api/gm/trash/{t['id']}/restore"))
    assert sorted(x["delta"] for x in state(rig)["money"]) == [-200, 1500]


def test_restoring_a_duplicate_standing_is_refused(world, gm):
    s = find(state(gm), "standing", char="rig", faction=world["open"])
    ok(gm.post(f"/api/gm/items/standing/{s['id']}/delete"))
    ok(gm.post("/api/gm/items/standing", json={"char": "rig", "faction": world["open"], "value": -1}))
    t = next(t for t in ok(gm.get("/api/gm/trash"))["items"] if t["kind"] == "standing" and t["item_id"] == s["id"])
    r = gm.post(f"/api/gm/trash/{t['id']}/restore")
    assert r.status_code == 409


def test_deleting_a_faction_hides_its_standing_from_players_and_restoring_brings_it_back(world, gm, rig):
    ok(gm.post(f"/api/gm/items/factions/{world['open']}/delete"))
    assert {x["faction"] for x in state(rig)["standing"]} == {world["rig"]}
    assert any(x["faction"] == world["open"] for x in state(gm)["standing"])                  # мастер видит «осиротевшую» строку и может убрать
    t = next(t for t in ok(gm.get("/api/gm/trash"))["items"] if t["kind"] == "factions" and t["item_id"] == world["open"])
    ok(gm.post(f"/api/gm/trash/{t['id']}/restore"))
    assert {x["faction"] for x in state(rig)["standing"]} == {world["open"], world["rig"]}


def test_narrowing_a_faction_hides_it_and_its_standing_at_once(world, gm, gate):
    f = find(state(gm), "factions", id=world["open"])
    ok(gm.post("/api/gm/items/factions", json=dict(f, vis="знают", known=["rig"])))
    assert state(gate)["factions"] == [] and state(gate)["standing"] == []


def test_deleted_card_drops_the_contact_link_for_players(world, gm, gate):
    ok(gm.post("/api/gm/items/dossier/n2/delete"))
    try:
        assert "card" not in {c["name"]: c for c in state(gate)["contacts"]}["Врач"]
    finally:
        t = next(t for t in ok(gm.get("/api/gm/trash"))["items"] if t["kind"] == "dossier" and t["item_id"] == "n2")
        ok(gm.post(f"/api/gm/trash/{t['id']}/restore"))
