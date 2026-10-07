"""Любой мусор в запросе должен давать 4xx, а не 500.

Для каждого эндпоинта берётся корректное тело запроса, и каждое его поле по очереди заменяется
«неудобными» значениями (списки вместо строк, словари, null, огромные числа) или удаляется.
"""
import pytest

from helpers import entry
from conftest import KINDS

MUTANTS = [None, True, False, 0, -1, 10 ** 12, 1.5, "", "zzz", "я" * 5000, [], [[]], [1], [["a"]], [None],
           ["rig"], [{"a": 1}], {}, {"a": 1}]
ABSENT = object()

ITEM_BODIES = {
    "windows": {"name": "Этап", "gm": "для мастера", "from": "2075-12-30", "to": "2075-12-31", "inter": True},
    "rhythm": {"title": "Ритм", "note": "n", "wd": [1, 3], "vis": "стол", "from": "2075-08-01", "to": "2075-09-01", "who": "rig"},
    "clocks": {"title": "Таймер", "note": "n", "when": "2075-10-01"},
    "plan": {"title": "План", "from": "2075-09-10", "to": "2075-09-11", "note": "n", "session": "s",
             "cover": {"title": "Маска", "note": "n", "who": ["rig"]}},
    "past": {"title": "Прошло", "from": "2075-07-20", "to": "2075-07-20", "note": "n", "gm_note": "g", "session": "s"},
    "places": {"name": "Место", "type": "home", "x": 100, "y": 100, "vis": "знают", "known": ["rig"], "note": "n", "gm_note": "g"},
    "dossier": {"name": "Карточка", "alias": "а", "type": "person", "role": "р", "stance": "ally", "org": "о", "vis": "знают",
                "known": ["rig"], "met": ["rig"], "last_date": "2075-08-01", "last_place": "m1", "last_note": "n",
                "facts": [{"id": "f9", "text": "факт", "vis": "знают", "known": ["rig"], "truth": "t", "date": "2075-08-01"}],
                "gm_note": "g"},
    "travel": {"name": "Транспорт", "kind": "roads", "motorway": 80, "trunk": 60, "primary": 40, "off": 20, "delay": 3, "wall": 15,
               "vis": "стол", "note": "n"},
    "handouts": {"title": "Раздатка", "date": "2075-08-01", "vis": "знают", "known": ["rig"], "note": "n", "gm_note": "g", "place": "m1"},
    "money": {"char": "rig", "delta": -500, "note": "n", "date": "2075-08-01", "gm_note": "g"},
    "factions": {"name": "Фракция", "kind": "gang", "vis": "знают", "known": ["rig"], "note": "n", "gm_note": "g"},
    "standing": {"char": "rig", "faction": "ПОДСТАВИТЬ", "value": 3, "note": "n", "gm_note": "g"},
    "contacts": {"char": "rig", "name": "Контакт", "card": "n1", "connection": 5, "loyalty": 3, "services": "s", "note": "n", "gm_note": "g"},
    "locmaps": {"name": "Карта", "note": "n", "gm_note": "g", "vis": "знают", "known": ["rig"], "place": "m1"},
}


def variants(body):
    """Все тела запроса с одним испорченным или удалённым полем (и вложенные поля первого уровня)."""
    for key in body:
        for m in MUTANTS + [ABSENT]:
            mutated = dict(body)
            if m is ABSENT:
                del mutated[key]
            else:
                mutated[key] = m
            yield f"{key}={m!r}"[:60], mutated
        inner = body[key]
        if isinstance(inner, dict):
            for ik in inner:
                for m in MUTANTS:
                    mutated = dict(body, **{key: dict(inner, **{ik: m})})
                    yield f"{key}.{ik}={m!r}"[:60], mutated
        if isinstance(inner, list) and inner and isinstance(inner[0], dict):
            for ik in inner[0]:
                for m in MUTANTS:
                    mutated = dict(body, **{key: [dict(inner[0], **{ik: m})]})
                    yield f"{key}[0].{ik}={m!r}"[:60], mutated


def run(client, url, body):
    failures = []
    for label, mutated in variants(body):
        r = client.post(url, json=mutated)
        if r.status_code >= 500:
            failures.append(f"{url}  {label}  ->  {r.status_code}")
    return failures


def test_entry_endpoints_survive_garbage(gm, gate, rig, sandbox):
    failures = run(gate, "/api/entries", entry(char="gate", who=["rig"], place="m1", goal="цель"))
    failures += run(gate, "/api/entries", entry(type="grow", char="gate", who=["gate"], goal="цель", effect="2075-08-05"))
    base = gate.post("/api/entries", json=entry(char="gate", title="База", who=["rig"])).json()["state"]
    eid = next(e["id"] for e in base["entries"] if e["title"] == "База")
    failures += run(gate, f"/api/entries/{eid}/edit", entry(char="gate", title="База", who=["rig"]))
    failures += run(rig, f"/api/entries/{eid}/messages", {"char": "rig", "text": "привет"})
    for act in ({"act": "ans", "v": "да", "char": "rig"}, {"act": "star", "char": "gate"}, {"act": "talk", "char": "gate"},
                {"act": "kick", "v": "rig", "char": "gate"}, {"act": "join", "char": "rig"},
                {"act": "approve"}, {"act": "outcome", "v": "done"}):
        failures += run(rig if act.get("char") == "rig" else gate, f"/api/entries/{eid}/act", act)
        failures += run(gm, f"/api/entries/{eid}/act", act)
    assert not failures, "500 на некорректных данных:\n" + "\n".join(failures[:40])


@pytest.mark.parametrize("kind", KINDS)
def test_gm_item_endpoints_survive_garbage(gm, sandbox, kind):
    body = dict(ITEM_BODIES[kind])
    if kind == "standing":                                                    # репутация ссылается на существующую фракцию
        made = gm.post("/api/gm/items/factions", json={"name": "Для репутации", "vis": "стол"}).json()["state"]["factions"]
        body["faction"] = made[-1]["id"]
    failures = run(gm, f"/api/gm/items/{kind}", body)
    assert not failures, "500 на некорректных данных:\n" + "\n".join(failures[:40])


def test_map_endpoints_survive_garbage(gm, rig, sandbox):
    from test_locmaps import SVG, add, make_map, upload
    mid = make_map(gm, vis="стол")
    upload(gm, mid, "player", SVG)
    upload(gm, mid, "gm", SVG)
    add(gm, mid, key="Н1", name="Своя", vis="стол")
    mark = {"name": "Метка", "key": "М1", "kind": "area", "status": "found", "vis": "знают", "known": ["rig"], "note": "n", "gm_note": "g",
            "at": {"player": [10, 10], "gm": [20, 20]}, "announce": True, "notify": False}
    failures = run(gm, f"/api/gm/locmaps/{mid}/objects", mark)
    failures += run(gm, f"/api/gm/locmaps/{mid}/import", {"objects": [{k: v for k, v in mark.items() if k not in ("announce", "notify")}]})
    failures += run(gm, f"/api/gm/locmaps/{mid}/feed", {"text": "объявление", "vis": "знают", "known": ["rig"], "notify": False})
    failures += run(rig, f"/api/locmaps/{mid}/pins", {"text": "пометка", "x": 100, "y": 100, "char": "rig"})
    assert not failures, "500 на некорректных данных:\n" + "\n".join(failures[:40])


def test_place_import_survives_garbage(gm, sandbox):
    body = {"items": [{"name": "Импорт", "type": "shop", "x": 31000, "y": 41000, "vis": "знают", "known": ["rig"], "note": "n", "gm_note": "g", "bg": True}]}
    failures = run(gm, "/api/gm/places/import", body)
    assert not failures, "500 на некорректных данных:\n" + "\n".join(failures[:40])


def test_dice_endpoint_survives_garbage(gate, rig, gm, sandbox):
    base = gate.post("/api/entries", json=entry(char="gate", title="Для кубов", who=["rig"])).json()["state"]
    eid = next(e["id"] for e in base["entries"] if e["title"] == "Для кубов")
    from app import logic
    saved = logic.ROLLS_PER_MINUTE
    logic.ROLLS_PER_MINUTE = 10 ** 6                                          # частоту не проверяем: тут нужны все варианты
    try:
        failures = run(rig, f"/api/entries/{eid}/roll", {"char": "rig", "dice": 4, "edge": True, "limit": 3, "threshold": 2, "label": "метка"})
    finally:
        logic.ROLLS_PER_MINUTE = saved
    assert not failures, "500 на некорректных данных:\n" + "\n".join(failures[:40])


def test_gm_time_and_district_survive_garbage(gm, sandbox):
    failures = []
    for body in ({"shift": 1}, {"date": "2075-08-02"}, {"tod": "ночь"}, {"quiet": "2075-08-07"}):
        failures += run(gm, "/api/gm/time", body)
    failures += run(gm, "/api/gm/district/downtown", {"text": "т", "gm_text": "г"})
    assert not failures, "\n".join(failures[:40])


def test_raw_bodies(gm):
    """Не JSON, не объект, числа за пределами double: 4xx."""
    cases = [b"not json", b"[1,2]", b'"text"', b"123", b"null", b'{"shift": 1e999}', b'{"x": 1e999, "y": 1}',
             b'{"shift": -1e999}', b'{"a":' + b"[" * 3000 + b"]" * 3000 + b"}", b"\xff\xfe", b""]
    for url in ("/api/entries", "/api/gm/time", "/api/gm/items/places", "/api/gm/items/rhythm", "/api/auth/widget",
                "/api/entries/x/act", "/api/gm/district/downtown"):
        for content in cases:
            r = gm.post(url, content=content, headers={"Content-Type": "application/json"})
            assert r.status_code < 500, (url, content[:30], r.status_code)
    r = gm.post("/api/gm/time", content=b'{"shift": 1e999}', headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_unexpected_error_returns_clean_json(gm, monkeypatch):
    """Если всё же что-то сломается, наружу идёт короткий JSON без трейсбека."""
    from app import logic

    def boom(*a, **k):
        raise RuntimeError("секретные внутренности")

    monkeypatch.setattr(logic, "state_for", boom)
    r = gm.get("/api/state")
    assert r.status_code == 500
    assert r.json() == {"detail": "Что-то пошло не так на портале. Попробуйте ещё раз."}
    assert "секретные" not in r.text
