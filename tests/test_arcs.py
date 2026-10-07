"""Импорт разбора арки (app/arcs.py): JSON из чата с разбором загружается на портал одной операцией.
Главное: каждый элемент проходит ту же проверку, что и ручное добавление; плохое пропускается и называется в отчёте, остальное добавляется;
повторная загрузка ничего не дублирует; существующее не меняется; игрокам не уходит ни уведомлений, ни скрытого."""
import copy
import json
import re
from pathlib import Path

import pytest

from app import arcs, db, notify, outbox
from conftest import GM, RIG
from helpers import ok

PREVIEW, IMPORT = "/api/gm/arc/preview", "/api/gm/arc/import"
SECRET = "СЕКРЕТ"


def good():
    """Небольшой разбор арки со всеми разделами; тайны только там, где игроки их не видят."""
    return {
        "windows": [{"name": "Арка 9. Тест", "gm": f"{SECRET}-название", "from": "2075-11-03", "to": "2075-11-09", "inter": False}],
        "plan": [
            {"title": "Ночной груз в порту", "from": "2075-11-04", "to": "2075-11-04", "session": "Арка 9, сессия 1",
             "note": f"{SECRET}-замысел плана", "cover": {"title": "Ночь на 4-е: порт закрыт", "note": "Слух о закрытии порта.", "who": []}},
            {"title": "Погоня по эстакаде", "from": "2075-11-06", "to": "2075-11-07", "session": "", "note": f"{SECRET}-погоня"},
        ],
        "clocks": [{"title": "Проверка склада", "note": f"{SECRET}-срок проверки", "when": "2075-11-10"}],
        "rhythm": [{"title": "Рынок на пирсе", "note": "Торгуют по вторникам и пятницам.", "vis": "стол", "wd": [1, 4]},
                   {"title": "Взнос синдикату", "note": f"{SECRET}-взнос", "vis": "мастер", "mode": "monthly", "monthDay": 15}],
        "entries": [{"type": "meet", "title": "Встреча с Мистером Джонсоном", "from": "2075-11-03", "to": "2075-11-03", "tod": "вечер",
                     "who": ["rig"], "where": "Бар «Мост»", "cond": "Без оружия", "goal": "Узнать условия.", "vis": "лично", "place_name": "Бар «Мост»"}],
        "past": [{"title": "Старая стычка", "from": "2075-11-01", "to": "2075-11-01", "session": "Арка 8", "note": "Все видели.", "gm_note": f"{SECRET}-хроника"}],
        "dossier": [{"name": "Мистер Джонсон", "type": "person", "role": "наниматель", "stance": "unknown", "vis": "мастер",
                     "facts": [{"text": f"{SECRET}-сведение", "vis": "мастер", "truth": f"{SECRET}-правда"}], "gm_note": f"{SECRET}-досье"}],
        "places": [{"name": "Бар «Мост»", "type": "business", "district": "downtown", "where_hint": "у моста", "note": "Тихий бар.", "gm_note": f"{SECRET}-бар"}],
        "handouts": [{"title": "Записка из бара", "date": "2075-11-03", "vis": "мастер", "note": "Мятая записка.", "text": "Приходи завтра.", "place_name": "Бар «Мост»"}],
        "questions": ["Дата встречи: поставил 2075-11-03. Верно?"],
    }


def state(client):
    return ok(client.get("/api/state"))


def post(client, data, url=IMPORT):
    return client.post(url, json={"data": data})


def names(st, kind, key="title"):
    return [x[key] for x in st[kind]]


def arc_records(gm):
    """Записи журнала об импортах разбора арки (журнал общий на весь прогон, поэтому тесты сравнивают «до» и «после»)."""
    return [h for h in ok(gm.get("/api/gm/history?limit=200"))["items"] if h["action"] == "import" and h["kind"] == "arc"]


@pytest.fixture(autouse=True)
def clean_outbox(started):
    db.conn().execute("DELETE FROM outbox")
    yield
    db.conn().execute("DELETE FROM outbox")


@pytest.fixture
def telegram_on(monkeypatch):
    monkeypatch.setattr(notify, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(notify, "NOTIFY_DM", True)


# ---------------------------------------------------------------- что добавляется

def test_everything_is_added_and_the_report_matches(gm, sandbox):
    before = state(gm)
    data = ok(post(gm, good()))
    rep = data["report"]
    assert data["msg"] == f"Добавлено: {rep['add']}" and rep["add"] == 11 and rep["skip"] == 0 and rep["error"] == 0
    assert {k: c["add"] for k, c in rep["counts"].items()} == {"windows": 1, "plan": 2, "clocks": 1, "rhythm": 2, "entries": 1, "past": 1, "dossier": 1,
                                                                  "places": 1, "handouts": 1}
    assert rep["questions"] == ["Дата встречи: поставил 2075-11-03. Верно?"]
    st = data["state"]
    assert len(st["windows"]) == len(before["windows"]) + 1 and "Арка 9. Тест" in names(st, "windows", "name")
    assert {"Ночной груз в порту", "Погоня по эстакаде"} <= set(names(st, "plan"))
    assert "Проверка склада" in names(st, "clocks") and {"Рынок на пирсе", "Взнос синдикату"} <= set(names(st, "rhythm"))
    assert "Старая стычка" in names(st, "past") and "Мистер Джонсон" in names(st, "dossier", "name") and "Бар «Мост»" in names(st, "places", "name")
    assert "Записка из бара" in names(st, "handouts")
    assert [e for e in st["entries"] if e["title"] == "Встреча с Мистером Джонсоном"]


def test_report_lists_every_item_in_the_order_of_the_prompt(gm, sandbox):
    rep = ok(post(gm, good(), PREVIEW))["report"]
    kinds = [i["kind"] for i in rep["items"]]
    assert kinds == sorted(kinds, key=[k for k, _ in arcs.LABELS].index) and len(kinds) == 11
    assert all(i["status"] == "add" for i in rep["items"]) and {i["title"] for i in rep["items"]} >= {"Мистер Джонсон", "Бар «Мост»", "Ночной груз в порту"}


def test_preview_writes_nothing(gm, sandbox):
    version, records = state(gm)["version"], len(arc_records(gm))
    ok(post(gm, good(), PREVIEW))
    st = state(gm)
    assert st["version"] == version and "Мистер Джонсон" not in names(st, "dossier", "name") and "Ночной груз в порту" not in names(st, "plan")
    assert len(arc_records(gm)) == records


def test_existing_records_are_not_touched(gm, sandbox):
    old = state(gm)
    ok(post(gm, good()))
    new = state(gm)
    for kind in ("windows", "plan", "clocks", "rhythm", "past", "dossier", "places", "handouts"):
        assert [x for x in new[kind] if x["id"] in {o["id"] for o in old[kind]}] == old[kind], kind
    assert [e for e in new["entries"] if e["id"] in {o["id"] for o in old["entries"]}] == old["entries"]


def test_plan_past_and_windows_stay_sorted_by_date(gm, sandbox):
    ok(post(gm, {"plan": [{"title": "Поздно", "from": "2075-12-01", "to": "2075-12-01"}, {"title": "Рано", "from": "2075-07-02", "to": "2075-07-02"}]}))
    plan = state(gm)["plan"]
    assert [p["from"] for p in plan] == sorted(p["from"] for p in plan)


# ---------------------------------------------------------------- повторная загрузка и повторы

def test_loading_the_same_arc_twice_adds_nothing_the_second_time(gm, sandbox):
    ok(post(gm, good()))
    first = state(gm)
    rep = ok(post(gm, good(), PREVIEW))["report"]
    assert rep["add"] == 0 and rep["skip"] == 11 and all(i["status"] == "skip" for i in rep["items"])
    r = post(gm, good())
    assert r.status_code == 400 and "Добавлять нечего" in r.json()["detail"]
    second = state(gm)
    for kind in ("windows", "plan", "clocks", "rhythm", "past", "dossier", "places", "handouts", "entries"):
        assert len(second[kind]) == len(first[kind]), kind


def test_repeats_inside_one_arc_are_loaded_once(gm, sandbox):
    data = {"plan": [{"title": "Дубль", "from": "2075-11-04", "to": "2075-11-04"}, {"title": "Дубль", "from": "2075-11-04", "to": "2075-11-04"},
                     {"title": "Дубль", "from": "2075-11-05", "to": "2075-11-05"}],
            "dossier": [{"name": "Лу"}, {"name": "  лу "}], "places": [{"name": "Склад", "district": "renton"}, {"name": "склад", "district": "renton"}]}
    rep = ok(post(gm, data))["report"]
    assert (rep["add"], rep["skip"]) == (4, 3)
    assert [i["msg"] for i in rep["items"] if i["status"] == "skip"] == ["повтор в этом же разборе"] * 3


def test_existing_dossier_card_wins_and_is_not_overwritten(gm, sandbox):
    ok(gm.post("/api/gm/items/dossier", json={"name": "Мэри-Лу", "type": "person", "role": "прежняя роль", "vis": "мастер", "gm_note": "прежняя заметка"}))
    rep = ok(post(gm, {"dossier": [{"name": "мэри-лу", "role": "новая роль", "gm_note": "новая заметка"}]}, PREVIEW))["report"]
    assert rep["items"][0]["status"] == "skip" and "уже есть" in rep["items"][0]["msg"]
    card = next(c for c in state(gm)["dossier"] if c["name"] == "Мэри-Лу")
    assert card["role"] == "прежняя роль" and card["gm_note"] == "прежняя заметка"


def test_existing_place_by_name_is_skipped_and_still_found_by_entries(gm, sandbox):
    ok(gm.post("/api/gm/items/places", json={"name": "Старый бар", "type": "business", "x": 30000, "y": 40000, "vis": "стол"}))
    data = {"places": [{"name": "старый бар", "district": "downtown"}],
            "entries": [{"type": "deal", "title": "Дело в старом баре", "from": "2075-11-05", "to": "2075-11-05", "who": ["rig"], "place_name": "Старый бар"}]}
    rep = ok(post(gm, data))["report"]
    assert (rep["add"], rep["skip"]) == (1, 1)
    st = state(gm)
    pid = next(p["id"] for p in st["places"] if p["name"] == "Старый бар")
    assert next(e for e in st["entries"] if e["title"] == "Дело в старом баре")["place"] == pid
    assert len([p for p in st["places"] if p["name"].lower() == "старый бар"]) == 1


# ---------------------------------------------------------------- ошибки: плохое пропускается, остальное добавляется

def test_a_bad_item_is_skipped_and_named_and_the_rest_is_added(gm, sandbox):
    data = good()
    data["plan"].append({"title": "Вне календаря", "from": "2099-01-01", "to": "2099-01-01"})
    data["plan"].append({"title": "", "from": "2075-11-05", "to": "2075-11-05"})
    data["plan"].append("не событие")
    data["dossier"].append({"name": "Тайный гость", "vis": "знают", "known": []})
    rep = ok(post(gm, data))["report"]
    assert (rep["add"], rep["error"]) == (11, 4)
    errors = [i for i in rep["items"] if i["status"] == "error"]
    assert {i["title"] for i in errors} >= {"Вне календаря", "Тайный гость"}
    assert "вне календаря" in next(i for i in errors if i["title"] == "Вне календаря")["msg"].lower()
    assert any("неверно" in i["msg"] for i in errors) and any("Укажите название" in i["msg"] for i in errors)
    st = state(gm)
    assert "Вне календаря" not in names(st, "plan") and "Тайный гость" not in names(st, "dossier", "name") and "Мистер Джонсон" in names(st, "dossier", "name")


def test_nothing_valid_means_nothing_is_added(gm, sandbox):
    before = state(gm)
    r = post(gm, {"plan": [{"title": "Плохая дата", "from": "вчера", "to": "завтра"}]})
    assert r.status_code == 400 and "Добавлять нечего" in r.json()["detail"]
    assert state(gm)["version"] == before["version"]


@pytest.mark.parametrize("data, text", [
    (None, "Не нашёл разбор"), ("строка", "Не нашёл разбор"), ([], "Не нашёл разбор"), ({}, "нет ни одного события"),
    ({"plan": "не список"}, "должен быть списком"), ({"plan": {"a": 1}}, "должен быть списком"), ({"questions": ["только вопросы"]}, "нет ни одного события"),
    ({"plan": [{"title": "x", "from": "2075-11-04", "to": "2075-11-04"}] * 401}, "не больше 400"),
])
def test_unusable_input_is_refused_with_a_reason(gm, sandbox, data, text):
    for url in (PREVIEW, IMPORT):
        r = post(gm, data, url)
        assert r.status_code == 400 and text in r.json()["detail"], (url, r.text)


def test_garbage_bodies_do_not_break_anything(gm):
    for url in (PREVIEW, IMPORT):
        for content in ("не json".encode(), b"[1,2]", b"null", b""):
            assert gm.post(url, content=content, headers={"Content-Type": "application/json"}).status_code < 500
        assert gm.post(url, json={}).status_code == 400


# ---------------------------------------------------------------- этапы

def test_windows_overlap_is_an_error_but_an_identical_window_is_a_repeat(gm, sandbox):
    ok(post(gm, {"windows": [{"name": "Этап А", "from": "2075-11-03", "to": "2075-11-09"}]}))
    data = {"windows": [{"name": "Этап А", "from": "2075-11-03", "to": "2075-11-09"},
                        {"name": "Этап Б", "from": "2075-11-08", "to": "2075-11-12"},
                        {"name": "Этап В", "from": "2075-11-10", "to": "2075-11-12"},
                        {"name": "Этап Г", "from": "2075-11-11", "to": "2075-11-13"}]}
    rep = ok(post(gm, data))["report"]
    assert [i["status"] for i in rep["items"]] == ["skip", "error", "add", "error"]
    assert "пересекается" in rep["items"][1]["msg"] and "пересекается" in rep["items"][3]["msg"]


# ---------------------------------------------------------------- места

def test_places_without_coordinates_are_put_near_the_center_of_the_district(gm, sandbox):
    centers = arcs._district_centers()
    rep = ok(post(gm, {"places": [{"name": f"Точка {i}", "district": "bellevue"} for i in range(8)] + [{"name": "Далёкая", "district": "tacoma"}]}))["report"]
    assert rep["add"] == 9 and all("рядом с центром района" in i["msg"] for i in rep["items"])
    places = {p["name"]: p for p in state(gm)["places"]}
    cx, cy = centers["bellevue"]
    pts = [(places[f"Точка {i}"]["x"], places[f"Точка {i}"]["y"]) for i in range(8)]
    assert len(set(pts)) == 8                                                          # не лежат одна на другой
    assert all(abs(x - cx) <= 2000 and abs(y - cy) <= 2000 for x, y in pts)
    assert abs(places["Далёкая"]["x"] - centers["tacoma"][0]) <= 2000


def test_place_defaults_hint_and_unknown_type(gm, rig, sandbox):
    rep = ok(post(gm, {"places": [{"name": "Тихое место", "type": "космопорт", "district": "dogtown", "where_hint": "за мостом", "gm_note": "заметка"}]}))["report"]
    assert "неизвестен" in rep["items"][0]["msg"]
    place = next(p for p in state(gm)["places"] if p["name"] == "Тихое место")
    assert place["vis"] == "мастер" and place["type"] == "other" and place["bg"] is False
    assert place["gm_note"] == "Ориентир: за мостом\nзаметка"
    assert "Тихое место" not in names(state(rig), "places", "name")                    # игрокам по умолчанию не показано


@pytest.mark.parametrize("raw, text", [({"name": "Без района"}, "Укажите район"), ({"name": "Не тот район", "district": "луна"}, "Укажите район"),
                                       ({"name": "За краем", "x": 10 ** 9, "y": 5}, "за краем карты")])
def test_places_that_cannot_be_put_on_the_map_are_errors(gm, sandbox, raw, text):
    rep = ok(post(gm, {"places": [raw], "plan": [{"title": "Для надёжности", "from": "2075-11-04", "to": "2075-11-04"}]}, PREVIEW))["report"]
    err = next(i for i in rep["items"] if i["kind"] == "places")
    assert err["status"] == "error" and text in err["msg"]


def test_given_coordinates_are_used(gm, sandbox):
    ok(post(gm, {"places": [{"name": "С координатами", "x": 31000, "y": 41000}]}))
    place = next(p for p in state(gm)["places"] if p["name"] == "С координатами")
    assert (place["x"], place["y"]) == (31000, 41000)


def test_place_limit_is_respected(gm, sandbox, monkeypatch):
    monkeypatch.setitem(arcs.logic.MAX_ITEMS, "places", len(state(gm)["places"]) + 1)
    rep = ok(post(gm, {"places": [{"name": "Одно", "district": "renton"}, {"name": "Другое", "district": "renton"}]}))["report"]
    assert [i["status"] for i in rep["items"]] == ["add", "error"] and "не больше" in rep["items"][1]["msg"]


# ---------------------------------------------------------------- записи календаря и раздатки

def test_entry_is_a_normal_master_entry_for_its_participants(gm, rig, sandbox):
    ok(post(gm, good()))
    e = next(e for e in state(rig)["entries"] if e["title"] == "Встреча с Мистером Джонсоном")
    assert e["author"] == "gm" and e["who"] == ["rig"] and e["tod"] == "вечер" and e["vis"] == "лично" and e["answers"] == {"rig": "да"} and e["status"] == "ok"
    place = next(p for p in state(gm)["places"] if p["name"] == "Бар «Мост»")
    assert next(x for x in state(gm)["entries"] if x["id"] == e["id"])["place"] == place["id"]


def test_private_entry_is_not_shown_to_other_players(gm, gate, sandbox):
    ok(post(gm, good()))
    assert "Встреча с Мистером Джонсоном" not in names(state(gate), "entries")


@pytest.mark.parametrize("raw, text", [({"type": "grow", "title": "Развитие", "who": ["rig"]}, "Тип записи"), ({"title": "Без типа", "who": ["rig"]}, "Тип записи"),
                                       ({"type": "meet", "title": "Без участников", "who": []}, "участник"),
                                       ({"type": "meet", "title": "С чужими", "who": ["никто"]}, "участник"),
                                       ({"type": "meet", "title": "Ночь", "who": ["rig"], "tod": "полдник"}, "время суток")])
def test_bad_entries_are_errors(gm, sandbox, raw, text):
    rep = ok(post(gm, {"entries": [dict({"from": "2075-11-04", "to": "2075-11-04"}, **raw)], "plan": [{"title": "Для надёжности", "from": "2075-11-04", "to": "2075-11-04"}]}))["report"]
    err = next(i for i in rep["items"] if i["kind"] == "entries")
    assert err["status"] == "error" and text.lower() in err["msg"].lower()


def test_open_entry_needs_no_participants(gm, rig, sandbox):
    ok(post(gm, {"entries": [{"type": "deal", "title": "Открытое дело", "from": "2075-11-05", "to": "2075-11-05", "who": [], "open": True}]}))
    e = next(e for e in state(rig)["entries"] if e["title"] == "Открытое дело")
    assert e["open"] is True and e["vis"] == "стол"


def test_unknown_place_name_leaves_the_field_empty_with_a_note(gm, sandbox):
    rep = ok(post(gm, {"entries": [{"type": "meet", "title": "Где-то", "from": "2075-11-05", "to": "2075-11-05", "who": ["rig"], "place_name": "Нет такого"}]}))["report"]
    assert rep["add"] == 1 and "не найдено на карте" in rep["items"][0]["msg"]
    assert next(e for e in state(gm)["entries"] if e["title"] == "Где-то")["place"] == ""


def test_handout_draft_goes_to_the_master_note_and_stays_hidden(gm, rig, sandbox):
    ok(post(gm, good()))
    h = next(h for h in state(gm)["handouts"] if h["title"] == "Записка из бара")
    assert h["vis"] == "мастер" and "Приходи завтра." in h["gm_note"] and h["note"] == "Мятая записка." and "file" not in h or not h.get("file")
    assert "Записка из бара" not in names(state(rig), "handouts")


def test_long_handout_draft_is_cut_with_a_warning(gm, sandbox):
    rep = ok(post(gm, {"handouts": [{"title": "Длинная", "date": "2075-11-03", "text": "я" * 4000}]}))["report"]
    assert rep["add"] == 1 and "обрезан" in rep["items"][0]["msg"]
    assert len(next(h for h in state(gm)["handouts"] if h["title"] == "Длинная")["gm_note"]) == 3000


# ---------------------------------------------------------------- видимость и уведомления

def test_players_see_nothing_secret_from_an_imported_arc(gm, rig, gate, sandbox):
    ok(post(gm, good()))
    for client in (rig, gate):
        text = client.get("/api/state").text
        assert SECRET not in text
        st = state(client)
        assert "Ночной груз в порту" not in names(st, "plan") and st["plan"] == [] and st["clocks"] == []
        assert "Мистер Джонсон" not in names(st, "dossier", "name") and "Бар «Мост»" not in names(st, "places", "name")
        assert "Взнос синдикату" not in names(st, "rhythm") and "Рынок на пирсе" in names(st, "rhythm")
    old_chron = next(p for p in state(rig)["past"] if p["title"] == "Старая стычка")
    assert old_chron["note"] == "Все видели." and "gm_note" not in old_chron


def test_cover_event_shows_only_what_the_cover_says(gm, rig, sandbox):
    ok(post(gm, good()))
    blocks = state(rig)["blocks"]
    assert [b["title"] for b in blocks if "порт" in b["title"]] == ["Ночь на 4-е: порт закрыт"]
    assert "Ночной груз в порту" not in json.dumps(blocks, ensure_ascii=False)


def test_unknown_character_ids_are_dropped_with_a_note(gm, sandbox):
    rep = ok(post(gm, {"plan": [{"title": "С чужим", "from": "2075-11-04", "to": "2075-11-04", "cover": {"title": "Общее", "who": ["rig", "призрак"]}}]}))["report"]
    assert rep["add"] == 1 and "неизвестные персонажи" in rep["items"][0]["msg"] and "призрак" in rep["items"][0]["msg"]
    assert next(p for p in state(gm)["plan"] if p["title"] == "С чужим")["cover"]["who"] == ["rig"]


def test_nobody_is_notified_by_an_import(gm, sandbox, telegram_on):
    ok(post(gm, good()))
    assert db.conn().execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    for tg in (GM, RIG, 102):
        assert outbox.pending(tg) == []


# ---------------------------------------------------------------- журнал, корзина, права

def test_one_history_record_and_nothing_to_revert(gm, sandbox):
    records = len(arc_records(gm))
    ok(post(gm, good()))
    found = arc_records(gm)
    assert len(found) == records + 1
    rec = found[0]                                                                      # свежие первыми
    assert rec["title"] == "Импорт разбора арки: 11" and rec["role"] == "gm"
    assert gm.post(f"/api/gm/history/{rec['id']}/revert").status_code == 400


def test_imported_items_can_be_deleted_to_the_trash_and_restored(gm, sandbox):
    ok(post(gm, good()))
    pid = next(p["id"] for p in state(gm)["plan"] if p["title"] == "Погоня по эстакаде")
    ok(gm.post(f"/api/gm/items/plan/{pid}/delete"))
    assert "Погоня по эстакаде" not in names(state(gm), "plan")
    tid = next(t["id"] for t in ok(gm.get("/api/gm/trash"))["items"] if t["title"] == "Погоня по эстакаде")
    ok(gm.post(f"/api/gm/trash/{tid}/restore"))
    assert "Погоня по эстакаде" in names(state(gm), "plan")


def test_only_the_master_can_use_it(rig, anon, gm, sandbox):
    before = state(gm)["version"]
    for url in (PREVIEW, IMPORT):
        assert post(rig, good(), url).status_code == 403
        assert post(anon, good(), url).status_code == 401
    assert state(gm)["version"] == before and "Мистер Джонсон" not in names(state(gm), "dossier", "name")


def test_a_failure_in_the_middle_leaves_nothing_behind(gm, sandbox, monkeypatch):
    before, records = state(gm), len(arc_records(gm))

    def boom(entry):
        raise RuntimeError("сбой записи")
    monkeypatch.setattr(db, "save_entry", boom)
    assert post(gm, good()).status_code == 500
    monkeypatch.undo()
    after = state(gm)
    for kind in ("windows", "plan", "clocks", "rhythm", "past", "dossier", "places", "handouts", "entries"):
        assert after[kind] == before[kind], kind
    assert len(arc_records(gm)) == records


def test_questions_are_cleaned_and_limited(gm, sandbox):
    data = {"plan": [{"title": "Хоть что-то", "from": "2075-11-04", "to": "2075-11-04"}], "questions": ["Вопрос?", 5, "", None, "я" * 1000] + [f"Ещё {i}" for i in range(50)]}
    rep = ok(post(gm, data, PREVIEW))["report"]
    assert len(rep["questions"]) == arcs.MAX_QUESTIONS and rep["questions"][0] == "Вопрос?" and len(rep["questions"][1]) == 400


def test_long_text_is_cut_like_in_the_forms(gm, sandbox):
    ok(post(gm, {"plan": [{"title": "т" * 500, "from": "2075-11-04", "to": "2075-11-04", "note": "н" * 5000}]}))
    p = next(p for p in state(gm)["plan"] if p["title"].startswith("тттт"))
    assert len(p["title"]) == 120 and len(p["note"]) == 2000


# ---------------------------------------------------------------- промпт и импорт говорят на одном языке

PROMPT = Path(__file__).resolve().parent.parent / "ПРОМПТ_РАЗБОР_АРОК.md"


def prompt_example():
    text = PROMPT.read_text(encoding="utf-8")
    return json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1)), text


def test_the_example_from_the_prompt_loads_without_a_single_complaint(gm, sandbox):
    example, _ = prompt_example()
    rep = ok(post(gm, example))["report"]
    assert rep["error"] == 0 and rep["skip"] == 0 and rep["add"] >= 6
    assert {i["kind"] for i in rep["items"]} >= {"plan", "clocks", "rhythm", "entries", "dossier", "places"}
    assert rep["questions"] == example["questions"]


def test_prompt_documents_every_section_the_importer_reads():
    example, text = prompt_example()
    for kind in arcs.ORDER:
        assert f"`{kind}`" in text and kind in example, kind
    assert "Импорт разбора арки" in text or "Загрузить разбор арки" in text


def test_prompt_example_is_not_changed_by_loading_it_into_a_copy():
    example, _ = prompt_example()
    assert copy.deepcopy(example) == example
