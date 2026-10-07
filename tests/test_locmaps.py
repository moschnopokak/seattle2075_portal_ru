"""Карты локаций (app/locmaps.py): рисунок игроков и рисунок мастера, метки, лента общих обновлений, пометки группы.
Главное: рисунок и заметки мастера не доходят до игрока, скрытые метки не видны, загруженный SVG не может выполнить код."""
import json
import re
from pathlib import Path

import pytest

from app import db, locmaps, notify, outbox
from conftest import GATE, RIG
from helpers import ok

SECRET = "СЕКРЕТ"
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600"><title>Роща</title><defs>'
       '<symbol id="s" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="#333"/></symbol>'
       '<pattern id="h" width="4" height="4" patternUnits="userSpaceOnUse"><path d="M0 0L4 4" stroke="#999"/></pattern>'
       '<marker id="m" markerWidth="4" markerHeight="4"><path d="M0 0L4 2L0 4z"/></marker><clipPath id="c"><rect width="800" height="600"/></clipPath></defs>'
       '<rect width="800" height="600" fill="url(#h)"/><use href="#s" x="10" y="10" width="10" height="10"/>'
       '<path d="M10 10L300 300" stroke="#000" marker-end="url(#m)" clip-path="url(#c)"/><text x="20" y="40" font-size="20">Роща</text></svg>')
SVG_GM = SVG.replace("Роща</text>", f"{SECRET}-для мастера</text>")


def clean(svg):
    return locmaps.sanitize_svg(svg.encode())


# ---------------------------------------------------------------- очистка рисунка

def test_a_normal_drawing_keeps_its_parts_and_gets_clean_dimensions():
    text, w, h, removed = clean(SVG)
    assert (w, h, removed) == (800, 600, {})
    for part in ("<symbol", "<pattern", "<marker", "<clipPath", "<use", "<text", 'href="#s"', "url(#h)", "Роща", 'viewBox="0 0 800 600"', 'width="800"', 'height="600"'):
        assert part in text, part
    assert text.startswith('<svg xmlns="http://www.w3.org/2000/svg"')


def test_dangerous_parts_are_removed_and_reported():
    dirty = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 100 100" onload="alert(1)">'
             '<script>alert(1)</script><foreignObject><div>x</div></foreignObject><image href="http://evil.example/a.png"/><a href="http://evil.example"><rect/></a>'
             '<animate attributeName="x"/><iframe src="x"/><rect width="5" height="5" onclick="alert(2)" fill="red"/>'
             '<use xlink:href="http://evil.example/x.svg#a"/><use href="javascript:alert(3)"/><use href="data:image/svg+xml;base64,AAAA"/>'
             '<circle r="3" fill="url(http://evil.example/p)" stroke="url(#ok)" style="fill:url(http://evil.example/q)"/><path d="M0 0" style="stroke:red"/></svg>')
    text, _w, _h, removed = clean(dirty)
    assert {"script", "foreignObject", "image", "a", "animate", "iframe"} <= set(removed)
    for bad in ("alert", "script", "foreignObject", "evil.example", "javascript", "onload", "onclick", "<image", "<a ", "iframe"):
        assert bad not in text, bad
    assert 'stroke="url(#ok)"' in text and 'stroke:red' in text and 'fill="red"' in text


def test_styles_keep_fonts_and_internal_links_but_nothing_that_loads_from_outside():
    css = ("@font-face{font-family:Hand;src:url(data:font/woff2;base64,AAAA) format('woff2')}"
           ".a{fill:url(#h);background:url(https://evil.example/x.png)}.b{font-family:Hand}")
    text, *_ = clean(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><style>{css}</style></svg>')
    assert "data:font/woff2;base64,AAAA" in text and "url(#h)" in text and "evil.example" not in text and ".b{font-family:Hand}" in text
    blocked, *_ = clean('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><style>@import url(https://evil.example/s.css);.a{fill:red}</style></svg>')
    assert "evil.example" not in blocked and "@import" not in blocked


@pytest.mark.parametrize("raw, message", [
    (b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "bbbb">]><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">&a;</svg>', "DOCTYPE"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><!ENTITY x "y"></svg>', "DOCTYPE"),
    (b"<svg", "не читается"), (b"", "не читается"), ("я".encode("cp1251") * 5, "UTF-8"),
    (b'<html xmlns="http://www.w3.org/1999/xhtml"></html>', "не SVG"), (b'<svg viewBox="0 0 1 1"/>', "не SVG"),
    (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "нет размеров"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="5 5 100 100"/>', "начинаться с 0 0"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 -4 10"/>', "от 1 до 100"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900000 10"/>', "от 1 до 100"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 abc 10"/>', "нет размеров"),
])
def test_unusable_files_are_refused_with_a_reason(raw, message):
    with pytest.raises(locmaps.SvgError, match=message):
        locmaps.sanitize_svg(raw)


def test_size_depth_and_node_limits():
    with pytest.raises(locmaps.SvgError, match="больше"):
        locmaps.sanitize_svg(b"<svg>" + b"a" * (locmaps.MAX_SVG_BYTES + 1))
    deep = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 9">' + "<g>" * 80 + "</g>" * 80 + "</svg>"
    with pytest.raises(locmaps.SvgError, match="слишком сложный"):
        clean(deep)
    many = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 9">' + "<rect/>" * (locmaps.MAX_NODES + 5) + "</svg>"
    with pytest.raises(locmaps.SvgError, match="слишком сложный"):
        clean(many)


def test_width_and_height_are_enough_when_there_is_no_viewbox():
    text, w, h, _ = clean('<svg xmlns="http://www.w3.org/2000/svg" width="640px" height="480"><rect/></svg>')
    assert (w, h) == (640, 480) and 'viewBox="0 0 640 480"' in text


def test_foreign_namespaces_and_unknown_tags_are_dropped_and_the_result_is_xml():
    import xml.etree.ElementTree as ET
    text, _, _, removed = clean('<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="http://example.com/x" viewBox="0 0 9 9"><x:thing/><filter id="f"><feImage href="http://example.com/a.png"/><feGaussianBlur/></filter><rect x:evil="1" width="1" height="1"/></svg>')
    assert "thing" in removed and "feImage" in removed and "filter" not in removed          # безопасные эффекты остаются, feImage (грузит чужое) нет
    assert "x:" not in text and "example.com" not in text and "<filter" in text and "<feGaussianBlur" in text
    assert ET.fromstring(text).tag == "{http://www.w3.org/2000/svg}svg"


# ---------------------------------------------------------------- вспомогательное

def state(client):
    return ok(client.get("/api/state"))


def make_map(gm, **kw):
    body = {"name": "Роща", "note": "Парк на окраине", "gm_note": f"{SECRET}-карта", "vis": "стол", "known": []}
    body.update(kw)
    data = ok(gm.post("/api/gm/items/locmaps", json=body))
    return next(m["id"] for m in data["state"]["locmaps"] if m["name"] == body["name"])


def upload(client, mid, role, svg=SVG):
    return client.post(f"/api/gm/locmaps/{mid}/drawing/{role}", content=svg.encode(), headers={"Content-Type": "image/svg+xml"})


def add(gm, mid, **kw):
    body = {"name": "Ворота", "key": "О1", "kind": "area", "note": "Видно всем", "gm_note": f"{SECRET}-метка", "at": {"player": [100, 100], "gm": [200, 200]}}
    body.update(kw)
    return ok(gm.post(f"/api/gm/locmaps/{mid}/objects", json=body))["object"]


def detail(client, mid):
    return ok(client.get(f"/api/locmaps/{mid}"))


@pytest.fixture(autouse=True)
def clean_tables(started):
    yield
    for table in ("locmap_files", "locmap_feed", "locmap_pins", "outbox"):
        db.conn().execute(f"DELETE FROM {table}")


@pytest.fixture
def telegram_on(monkeypatch):
    monkeypatch.setattr(notify, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(notify, "NOTIFY_DM", True)


@pytest.fixture
def world(gm, sandbox):
    """Карта для всех, оба рисунка загружены, две метки: открытая и скрытая."""
    mid = make_map(gm)
    ok(upload(gm, mid, "player"))
    ok(upload(gm, mid, "gm", SVG_GM))
    add(gm, mid, name="Открытая", key="О1", vis="стол")
    add(gm, mid, name="Скрытая", key="О2", vis="мастер", at={"player": [300, 300], "gm": [400, 400]})
    return mid


# ---------------------------------------------------------------- карта и её видимость

def test_maps_list_for_players_and_for_the_master(gm, rig, gate, sandbox):
    mid = make_map(gm, name="Для всех", vis="стол")
    hidden = make_map(gm, name="Скрытая карта", vis="мастер")
    only = make_map(gm, name="Для Риг", vis="знают", known=["rig"])
    g = {m["name"]: m for m in state(gm)["locmaps"]}
    assert {"Для всех", "Скрытая карта", "Для Риг"} <= set(g) and g["Для всех"]["gm_note"] == f"{SECRET}-карта" and g["Для всех"]["count"] == 0
    seen = {m["name"] for m in state(rig)["locmaps"]}
    assert "Для всех" in seen and "Для Риг" in seen and "Скрытая карта" not in seen
    assert "gm_note" not in next(m for m in state(rig)["locmaps"] if m["name"] == "Для всех")
    assert rig.get(f"/api/locmaps/{hidden}").status_code == 404
    assert "Для Риг" not in {m["name"] for m in state(gate)["locmaps"]}
    assert mid and only


def test_map_form_validates_and_does_not_lose_marks(gm, sandbox):
    assert gm.post("/api/gm/items/locmaps", json={"name": "", "vis": "стол"}).status_code == 400
    assert gm.post("/api/gm/items/locmaps", json={"name": "Для знающих", "vis": "знают", "known": []}).status_code == 400
    assert gm.post("/api/gm/items/locmaps", json={"name": "С чужим местом", "vis": "стол", "place": "нет-такого"}).status_code == 400
    mid = make_map(gm, name="Правка")
    ok(upload(gm, mid, "player"))
    add(gm, mid)
    ok(gm.post("/api/gm/items/locmaps", json={"id": mid, "name": "Переименована", "vis": "стол", "note": "Новое описание"}))     # форма карты меток не знает
    d = detail(gm, mid)
    assert d["name"] == "Переименована" and len(d["objects"]) == 1 and "player" in d["dw"]


def test_a_map_can_be_linked_to_a_place_the_player_knows(gm, rig, sandbox):
    ok(gm.post("/api/gm/items/places", json={"name": "Парк", "type": "other", "x": 30000, "y": 40000, "vis": "стол"}))
    ok(gm.post("/api/gm/items/places", json={"name": "Тайный парк", "type": "other", "x": 31000, "y": 41000, "vis": "мастер"}))
    pid = next(p["id"] for p in state(gm)["places"] if p["name"] == "Парк")
    secret = next(p["id"] for p in state(gm)["places"] if p["name"] == "Тайный парк")
    open_map = make_map(gm, name="У парка", place=pid)
    sneaky = make_map(gm, name="У тайного парка", place=secret)
    cards = {m["name"]: m for m in state(rig)["locmaps"]}
    assert cards["У парка"]["place"] == pid and cards["У тайного парка"]["place"] == ""            # номер скрытого места игроку не отдаётся
    assert detail(rig, open_map)["place"] == pid and detail(rig, sneaky)["place"] == ""


# ---------------------------------------------------------------- рисунки

def test_players_get_only_their_drawing_and_the_master_gets_both(gm, rig, anon, world):
    p = rig.get(f"/locmap/{world}/player.svg")
    assert p.status_code == 200 and p.headers["content-type"].startswith("image/svg+xml") and "Роща" in p.text and SECRET not in p.text
    assert rig.get(f"/locmap/{world}/gm.svg").status_code == 403
    assert anon.get(f"/locmap/{world}/player.svg").status_code == 401
    g = gm.get(f"/locmap/{world}/gm.svg")
    assert g.status_code == 200 and f"{SECRET}-для мастера" in g.text
    assert gm.get(f"/locmap/{world}/other.svg").status_code == 404
    assert SECRET not in json.dumps(detail(rig, world), ensure_ascii=False)
    assert "gm" not in detail(rig, world)["dw"] and set(detail(gm, world)["dw"]) == {"player", "gm"}


def test_drawing_is_served_in_a_sandbox_and_cannot_be_sniffed(gm, rig, world):
    r = rig.get(f"/locmap/{world}/player.svg")
    csp = r.headers["content-security-policy"]
    assert csp.startswith("sandbox;") and "default-src 'none'" in csp and "script" not in csp
    assert r.headers["x-content-type-options"] == "nosniff" and "private" in r.headers["cache-control"] and r.headers["cross-origin-resource-policy"] == "same-origin"


def test_uploaded_drawing_is_cleaned_and_the_master_is_told(gm, rig, sandbox):
    mid = make_map(gm)
    dirty = SVG.replace("</svg>", '<script>alert(1)</script><rect onclick="x()" width="1" height="1"/></svg>')
    r = ok(upload(gm, mid, "player", dirty))
    assert "убрано" in r["msg"] and "script" in r["msg"]
    served = rig.get(f"/locmap/{mid}/player.svg").text
    assert "alert" not in served and "onclick" not in served
    again = ok(upload(gm, mid, "player", SVG.replace("800 600", "1000 700")))
    assert "Размер рисунка изменился" in again["msg"] and detail(gm, mid)["dw"]["player"] == {"w": 1000, "h": 700, "v": detail(gm, mid)["dw"]["player"]["v"]}


@pytest.mark.parametrize("who", ["rig", "anon"])
def test_only_the_master_uploads(gm, rig, anon, sandbox, who):
    mid = make_map(gm)
    client = {"rig": rig, "anon": anon}[who]
    assert upload(client, mid, "player").status_code == {"rig": 403, "anon": 401}[who]
    assert "player" not in detail(gm, mid)["dw"]


@pytest.mark.parametrize("role, content, code", [("player", b"not svg", 400), ("sky", SVG.encode(), 400), ("gm", b"", 400)])
def test_bad_uploads_are_refused(gm, sandbox, role, content, code):
    mid = make_map(gm)
    r = gm.post(f"/api/gm/locmaps/{mid}/drawing/{role}", content=content)
    assert r.status_code == code and r.json()["detail"]


def test_upload_to_a_missing_map_and_too_big_body(gm, sandbox):
    assert upload(gm, "lнет", "player").status_code == 404
    mid = make_map(gm)
    big = b"<svg>" + b"a" * (locmaps.MAX_SVG_BYTES + 10)
    assert gm.post(f"/api/gm/locmaps/{mid}/drawing/player", content=big).status_code == 413


def test_removing_a_drawing_clears_the_marks_placed_on_it(gm, rig, world):
    ok(gm.post(f"/api/gm/locmaps/{world}/drawing/gm/delete"))
    d = detail(gm, world)
    assert "gm" not in d["dw"] and all("gm" not in o["at"] for o in d["objects"])
    assert gm.get(f"/locmap/{world}/gm.svg").status_code == 404
    assert gm.post(f"/api/gm/locmaps/{world}/drawing/gm/delete").status_code == 404
    assert rig.post(f"/api/gm/locmaps/{world}/drawing/player/delete").status_code == 403


# ---------------------------------------------------------------- метки

def test_players_see_only_open_marks_and_only_what_is_meant_for_them(gm, rig, world):
    d = detail(rig, world)
    assert [o["name"] for o in d["objects"]] == ["Открытая"]
    o = d["objects"][0]
    assert set(o) == {"id", "key", "name", "kind", "status", "note", "at"} and o["at"] == {"player": [100, 100]}
    assert SECRET not in json.dumps(d, ensure_ascii=False) and SECRET not in rig.get("/api/state").text
    g = detail(gm, world)
    assert [o["name"] for o in g["objects"]] == ["Открытая", "Скрытая"] and g["objects"][0]["gm_note"] == f"{SECRET}-метка" and g["objects"][0]["at"]["gm"] == [200, 200]


def test_a_mark_for_chosen_characters_only(gm, rig, gate, world):
    add(gm, world, name="Только Рига", key="Р", vis="знают", known=["rig"])
    assert "Только Рига" in [o["name"] for o in detail(rig, world)["objects"]]
    assert "Только Рига" not in [o["name"] for o in detail(gate, world)["objects"]]
    assert gm.post(f"/api/gm/locmaps/{world}/objects", json={"name": "Никому", "vis": "знают", "known": []}).status_code == 400


def test_new_marks_are_hidden_by_default(gm, rig, sandbox):
    mid = make_map(gm)
    o = add(gm, mid, name="Новая")
    assert o["vis"] == "мастер" and detail(rig, mid)["objects"] == []


def test_editing_by_number_changes_only_what_was_sent(gm, rig, world):
    first = next(o for o in detail(gm, world)["objects"] if o["name"] == "Открытая")
    ok(gm.post(f"/api/gm/locmaps/{world}/objects", json={"id": first["id"], "status": "cleared"}))
    now = next(o for o in detail(gm, world)["objects"] if o["id"] == first["id"])
    assert now["status"] == "cleared" and {k: now[k] for k in ("name", "key", "kind", "vis", "note", "gm_note", "at")} == {k: first[k] for k in ("name", "key", "kind", "vis", "note", "gm_note", "at")}
    assert gm.post(f"/api/gm/locmaps/{world}/objects", json={"id": "oнет", "name": "Х"}).status_code == 404
    ok(gm.post(f"/api/gm/locmaps/{world}/objects/{first['id']}/delete"))
    assert first["id"] not in [o["id"] for o in detail(gm, world)["objects"]]
    assert gm.post(f"/api/gm/locmaps/{world}/objects/{first['id']}/delete").status_code == 404


@pytest.mark.parametrize("body, code", [
    ({"name": ""}, 400), ({"name": "К", "key": "слишком-длинная-подпись-на-двадцать-знаков"}, 400), ({"name": "К", "key": "<b>"}, 400),
    ({"name": "К", "at": {"player": [10 ** 6, 5]}}, 400), ({"name": "К", "at": {"player": [801, 5]}}, 400), ({"name": "К", "at": {"player": [-1, 5]}}, 400),
    ({"name": "К", "at": {"player": "тут"}}, 400), ({"name": "К", "at": {"player": [1]}}, 400), ({"name": "К", "at": {"gm": [5, 601]}}, 400),
])
def test_bad_marks_are_refused(gm, world, body, code):
    assert gm.post(f"/api/gm/locmaps/{world}/objects", json=body).status_code == code


def test_unknown_kind_and_status_fall_back_and_text_is_cut(gm, world):
    o = add(gm, world, name="Н" * 200, key="Х", kind="космос", status="что-то", note="я" * 2000, gm_note="м" * 5000)
    assert o["kind"] == "place" and o["status"] == "" and len(o["name"]) == 80 and len(o["note"]) == 1000 and len(o["gm_note"]) == 2000


def test_a_key_is_unique_on_the_map_and_there_is_a_limit(gm, world, monkeypatch):
    r = gm.post(f"/api/gm/locmaps/{world}/objects", json={"name": "Дубль", "key": "о1"})
    assert r.status_code == 409 and "занята" in r.json()["detail"]
    monkeypatch.setattr(locmaps, "MAX_OBJECTS", 2)
    assert gm.post(f"/api/gm/locmaps/{world}/objects", json={"name": "Лишняя", "key": "Л"}).status_code == 409


def test_players_cannot_touch_marks(gm, rig, anon, world):
    o = detail(gm, world)["objects"][0]
    for url, body in ((f"/api/gm/locmaps/{world}/objects", {"id": o["id"], "status": "lost"}), (f"/api/gm/locmaps/{world}/objects/{o['id']}/delete", {}),
                      (f"/api/gm/locmaps/{world}/import", {"objects": []}), (f"/api/gm/locmaps/{world}/feed", {"text": "Подделка"})):
        assert rig.post(url, json=body).status_code == 403 and anon.post(url, json=body).status_code == 401
    assert detail(gm, world)["objects"][0]["status"] == o["status"]


# ---------------------------------------------------------------- общие обновления

def feed(client, mid):
    return [f["text"] for f in detail(client, mid)["feed"]]


def test_opening_a_mark_and_changing_its_state_write_to_the_feed(gm, rig, world):
    hidden = next(o for o in detail(gm, world)["objects"] if o["name"] == "Скрытая")
    assert feed(rig, world) == ["Открыто на карте: «Открытая»"]                       # первая метка была открыта сразу при создании
    ok(gm.post(f"/api/gm/locmaps/{world}/objects", json={"id": hidden["id"], "vis": "стол"}))
    ok(gm.post(f"/api/gm/locmaps/{world}/objects", json={"id": hidden["id"], "status": "cleared"}))
    assert feed(rig, world)[:2] == ["«Скрытая»: расчищено", "Открыто на карте: «Скрытая»"]


def test_hidden_marks_leave_no_trace_in_the_feed_and_announce_false_stays_quiet(gm, rig, world):
    before = feed(gm, world)
    h = next(o for o in detail(gm, world)["objects"] if o["name"] == "Скрытая")
    ok(gm.post(f"/api/gm/locmaps/{world}/objects", json={"id": h["id"], "status": "danger"}))                   # метка скрыта: сообщать нечего
    ok(gm.post(f"/api/gm/locmaps/{world}/objects", json={"id": h["id"], "vis": "стол", "announce": False}))     # открыли тихо
    assert feed(gm, world) == before and "Скрытая" not in " ".join(feed(rig, world))


def test_state_change_of_a_mark_for_chosen_characters_goes_to_them_only(gm, rig, gate, world):
    add(gm, world, name="Для Рига", key="Р", vis="знают", known=["rig"])
    assert "Открыто на карте: «Для Рига»" in feed(rig, world) and "Открыто на карте: «Для Рига»" not in feed(gate, world)


def test_master_posts_an_announcement_for_everyone_or_for_some(gm, rig, gate, world):
    ok(gm.post(f"/api/gm/locmaps/{world}/feed", json={"text": "Ночью выпала роса"}))
    ok(gm.post(f"/api/gm/locmaps/{world}/feed", json={"text": f"{SECRET}-только Рига", "vis": "знают", "known": ["rig"]}))
    assert "Ночью выпала роса" in feed(gate, world) and f"{SECRET}-только Рига" not in feed(gate, world) and f"{SECRET}-только Рига" in feed(rig, world)
    for body in ({"text": ""}, {"text": "   "}, {"text": "К", "vis": "знают", "known": []}):
        assert gm.post(f"/api/gm/locmaps/{world}/feed", json=body).status_code == 400
    item = next(f for f in detail(gm, world)["feed"] if f["text"] == "Ночью выпала роса")
    assert item["vis"] == "стол" and "vis" not in next(f for f in detail(gate, world)["feed"] if f["text"] == "Ночью выпала роса")
    ok(gm.post(f"/api/gm/locmaps/{world}/feed/{item['id']}/delete"))
    assert "Ночью выпала роса" not in feed(gm, world) and gm.post(f"/api/gm/locmaps/{world}/feed/{item['id']}/delete").status_code == 404


def test_the_feed_is_capped(gm, world, monkeypatch):
    monkeypatch.setattr(locmaps, "MAX_FEED", 5)
    for i in range(9):
        ok(gm.post(f"/api/gm/locmaps/{world}/feed", json={"text": f"Запись {i}"}))
    texts = feed(gm, world)
    assert len(texts) == 5 and texts[0] == "Запись 8" and "Запись 3" not in texts


def test_telegram_message_only_when_asked_and_only_to_those_who_see_it(gm, world, telegram_on):
    db.conn().execute("DELETE FROM outbox")
    ok(gm.post(f"/api/gm/locmaps/{world}/feed", json={"text": "Тихо"}))
    assert not outbox.pending(RIG)
    ok(gm.post(f"/api/gm/locmaps/{world}/feed", json={"text": "Громко", "notify": True}))
    row = next(r for r in outbox.pending(RIG) if r["kind"] == "map")
    assert "Громко" in row["text"] and "«Роща»" in row["text"] and row["section"] == "maps"
    db.conn().execute("DELETE FROM outbox")
    ok(gm.post(f"/api/gm/locmaps/{world}/feed", json={"text": "Только Рига", "vis": "знают", "known": ["rig"], "notify": True}))
    assert any(r["kind"] == "map" for r in outbox.pending(RIG)) and not any(r["kind"] == "map" for r in outbox.pending(GATE))


def test_a_mark_opened_with_notify_writes_to_the_right_people(gm, world, telegram_on):
    db.conn().execute("DELETE FROM outbox")
    add(gm, world, name="Новая находка", key="Н", vis="знают", known=["rig"], notify=True)
    assert any("Новая находка" in r["text"] for r in outbox.pending(RIG)) and not outbox.pending(GATE)


def test_feed_entries_from_beyond_the_horizon_are_not_shown(gm, rig, world):
    ok(gm.post("/api/gm/time", json={"date": "2075-09-05"}))
    ok(gm.post(f"/api/gm/locmaps/{world}/feed", json={"text": "Запись из сентября"}))
    ok(gm.post("/api/gm/time", json={"date": "2075-08-01"}))
    ok(gm.post("/api/gm/horizon", json={"mode": "window"}))
    try:
        assert "Запись из сентября" not in feed(rig, world) and "Запись из сентября" in feed(gm, world)
    finally:
        ok(gm.post("/api/gm/horizon", json={"mode": "off"}))
    assert "Запись из сентября" in feed(rig, world)


# ---------------------------------------------------------------- пометки группы

def pin(client, mid, text="Тропы врут", x=120, y=130, **kw):
    return client.post(f"/api/locmaps/{mid}/pins", json={"text": text, "x": x, "y": y, **kw})        # персонаж по умолчанию: единственный у игрока


def test_players_pin_notes_and_everyone_with_access_sees_them(gm, rig, gate, world):
    ok(pin(rig, world))
    pins = detail(gate, world)["pins"]
    assert len(pins) == 1 and pins[0]["text"] == "Тропы врут" and pins[0]["char"] == "rig" and (pins[0]["x"], pins[0]["y"]) == (120, 130)
    assert detail(gm, world)["pins"] == pins


def test_pin_checks(gm, rig, anon, world, sandbox):
    assert pin(gm, world).status_code == 403
    assert pin(anon, world).status_code == 401
    for kw in ({"text": ""}, {"text": "  "}, {"x": 900}, {"y": -2}, {"x": "тут"}, {"char": "gate"}):
        assert pin(rig, world, **kw).status_code in (400, 403), kw
    ok(pin(rig, world, text="я" * 500, x=5, y=5))
    assert len(detail(rig, world)["pins"][0]["text"]) == 120
    nodraw = make_map(gm, name="Без рисунка")
    assert pin(rig, nodraw).status_code == 400
    secret = make_map(gm, name="Закрытая", vis="мастер")
    assert pin(rig, secret).status_code == 404


def test_pin_limit(rig, world, monkeypatch):
    monkeypatch.setattr(locmaps, "MAX_PINS", 3)
    for i in range(3):
        ok(pin(rig, world, text=f"П{i}"))
    r = pin(rig, world, text="Лишняя")
    assert r.status_code == 409 and "уже 3" in r.json()["detail"]


def test_a_player_removes_only_his_own_pin_and_the_master_any(gm, rig, gate, world):
    ok(pin(rig, world, text="Моя"))
    ok(pin(gate, world, text="Чужая", char="gate"))
    mine, theirs = detail(rig, world)["pins"]
    assert rig.post(f"/api/locmaps/{world}/pins/{theirs['id']}/delete").status_code == 403
    ok(rig.post(f"/api/locmaps/{world}/pins/{mine['id']}/delete"))
    ok(gm.post(f"/api/locmaps/{world}/pins/{theirs['id']}/delete"))
    assert detail(gm, world)["pins"] == [] and gm.post(f"/api/locmaps/{world}/pins/{theirs['id']}/delete").status_code == 404


# ---------------------------------------------------------------- метки пачкой

def test_import_adds_updates_and_skips(gm, world):
    items = [{"key": "Г1", "name": "Оранжерея", "kind": "area", "note": "Стеклянная", "gm_note": "тайна", "at": {"gm": [10, 10], "player": [20, 20]}},
             {"key": "О1", "name": "Ворота (новое имя)", "at": {"player": [111, 111]}},
             {"key": "Г2", "name": "Пруд", "vis": "стол", "status": "cleared"}]
    rep = ok(gm.post(f"/api/gm/locmaps/{world}/import", json={"objects": items}))["report"]
    assert (rep["add"], rep["update"], rep["error"]) == (2, 1, 0)
    objs = {o["key"]: o for o in detail(gm, world)["objects"]}
    assert objs["Г1"]["vis"] == "мастер" and objs["Г2"]["vis"] == "мастер" and objs["Г2"]["status"] == ""         # видимость и состояние из файла не берутся
    assert objs["О1"]["name"] == "Ворота (новое имя)" and objs["О1"]["vis"] == "стол" and objs["О1"]["at"] == {"player": [111, 111], "gm": [200, 200]}
    again = ok(gm.post(f"/api/gm/locmaps/{world}/import", json={"objects": items}))["report"]
    assert (again["add"], again["update"], again["skip"]) == (0, 0, 3)


def test_import_names_the_bad_ones_and_adds_the_rest(gm, world):
    items = [{"key": "Н1", "name": "Нормальная"}, {"key": "Н2", "name": ""}, "не метка", {"key": "Н3", "name": "За краем", "at": {"player": [9999, 1]}},
             {"key": "Н1", "name": "Повтор подписи"}]
    rep = ok(gm.post(f"/api/gm/locmaps/{world}/import", json={"objects": items}))["report"]
    assert (rep["add"], rep["error"]) == (1, 4)
    assert [i["status"] for i in rep["items"]] == ["add", "error", "error", "error", "error"] and "за краем" in rep["items"][3]["msg"].lower()


@pytest.mark.parametrize("body", [{"objects": []}, {"objects": "метки"}, {}, {"objects": None}])
def test_import_needs_a_list(gm, world, body):
    assert gm.post(f"/api/gm/locmaps/{world}/import", json=body).status_code == 400


def test_import_is_limited(gm, world):
    many = [{"key": f"К{i}", "name": f"М{i}"} for i in range(locmaps.MAX_IMPORT + 1)]
    assert gm.post(f"/api/gm/locmaps/{world}/import", json={"objects": many}).status_code == 400


# ---------------------------------------------------------------- корзина, журнал

def test_deleting_a_map_closes_it_and_restoring_brings_everything_back(gm, rig, world):
    ok(pin(rig, world))
    ok(gm.post(f"/api/gm/items/locmaps/{world}/delete"))
    assert world not in [m["id"] for m in state(rig)["locmaps"]]
    assert rig.get(f"/api/locmaps/{world}").status_code == 404 and rig.get(f"/locmap/{world}/player.svg").status_code == 404
    tid = next(t["id"] for t in ok(gm.get("/api/gm/trash"))["items"] if t["kind"] == "locmaps" and t["item_id"] == world)
    ok(gm.post(f"/api/gm/trash/{tid}/restore"))
    d = detail(rig, world)
    assert [o["name"] for o in d["objects"]] == ["Открытая"] and len(d["pins"]) == 1 and rig.get(f"/locmap/{world}/player.svg").status_code == 200


def test_purging_from_the_trash_deletes_drawings_pins_and_feed(gm, rig, world):
    ok(pin(rig, world))
    ok(gm.post(f"/api/gm/items/locmaps/{world}/delete"))
    tid = next(t["id"] for t in ok(gm.get("/api/gm/trash"))["items"] if t["kind"] == "locmaps" and t["item_id"] == world)
    ok(gm.post(f"/api/gm/trash/{tid}/purge"))
    for table in ("locmap_files", "locmap_feed", "locmap_pins"):
        assert db.conn().execute(f"SELECT COUNT(*) FROM {table} WHERE map_id=?", (world,)).fetchone()[0] == 0, table


def test_history_keeps_marks_out_and_a_revert_does_not_wipe_them(gm, world):
    ok(gm.post("/api/gm/items/locmaps", json={"id": world, "name": "Новое имя", "vis": "стол", "note": "Другое"}))
    rec = next(h for h in ok(gm.get("/api/gm/history?kind=locmaps&limit=50"))["items"] if h["action"] == "edit" and h["item_id"] == world)
    assert {c["field"] for c in rec["changes"]} >= {"name"} and "objects" not in json.dumps(rec, ensure_ascii=False)
    ok(gm.post(f"/api/gm/history/{rec['id']}/revert"))
    d = detail(gm, world)
    assert d["name"] == "Роща" and len(d["objects"]) == 2 and set(d["dw"]) == {"player", "gm"}


def test_the_state_tells_players_which_drawings_exist(gm, rig, sandbox):
    mid = make_map(gm)
    assert state(rig)["locmaps"][-1]["dw"] == {}
    ok(upload(gm, mid, "gm", SVG_GM))
    assert next(m for m in state(rig)["locmaps"] if m["id"] == mid)["dw"] == {}                    # про рисунок мастера игрок не узнаёт
    ok(upload(gm, mid, "player"))
    assert next(m for m in state(rig)["locmaps"] if m["id"] == mid)["dw"]["player"]["w"] == 800


def test_every_new_route_needs_a_login(anon, gm, world):
    for method, url in (("get", f"/api/locmaps/{world}"), ("get", f"/locmap/{world}/player.svg"), ("post", f"/api/locmaps/{world}/pins"),
                        ("post", f"/api/locmaps/{world}/pins/1/delete"), ("post", f"/api/gm/locmaps/{world}/objects"), ("post", f"/api/gm/locmaps/{world}/drawing/player")):
        r = anon.get(url) if method == "get" else anon.post(url, json={})
        assert r.status_code == 401, url


def test_markup_in_names_and_notes_is_stored_as_text(gm, rig, world):
    evil = "<img src=x onerror=alert(1)>"
    add(gm, world, name=evil[:80], key="Э", note=evil, vis="стол")
    d = detail(rig, world)
    shown = next(o for o in d["objects"] if o["key"] == "Э")
    assert shown["name"] == evil[:80] and shown["note"] == evil                         # хранится буквами; страница выводит их через экранирование


# ---------------------------------------------------------------- промпт для чата и импорт говорят на одном языке

PROMPT = Path(__file__).resolve().parent.parent / "ПРОМПТ_КАРТА_ЛОКАЦИИ.md"


def prompt_example():
    text = PROMPT.read_text(encoding="utf-8")
    return json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1)), text


def test_the_example_from_the_map_prompt_loads_without_a_single_complaint(gm, sandbox):
    example, _ = prompt_example()
    big = SVG.replace('viewBox="0 0 800 600"', 'viewBox="0 0 1684 1190"')
    mid = make_map(gm)
    ok(upload(gm, mid, "player", big))
    ok(upload(gm, mid, "gm", big))
    rep = ok(gm.post(f"/api/gm/locmaps/{mid}/import", json=example))["report"]
    assert (rep["add"], rep["error"], rep["skip"]) == (3, 0, 0)
    again = ok(gm.post(f"/api/gm/locmaps/{mid}/import", json=example))["report"]
    assert (again["add"], again["skip"], again["error"]) == (0, 3, 0)               # повторная загрузка ничего не меняет
    objs = {o["key"]: o for o in detail(gm, mid)["objects"]}
    assert all(o["vis"] == "мастер" for o in objs.values())                            # всё приходит скрытым
    assert objs["О1"]["at"] == {"player": [842, 1010], "gm": [842, 1010]} and objs["Тайник"]["at"] == {"gm": [1190, 480]}


def test_map_prompt_names_the_same_kinds_and_limits_as_the_portal():
    example, text = prompt_example()
    for kind in locmaps.OBJ_KINDS:
        assert f'`"{kind}"`' in text, kind
    for word in (str(locmaps.MAX_OBJECTS), "3 МБ", "100 000", "viewBox", "Метки из JSON", "«Локации»"):
        assert word in text, word
    assert {k for o in example["objects"] for k in o} <= {"key", "name", "kind", "note", "gm_note", "at"}
    for tag in ("mask", "foreignObject", "script", "image"):
        assert tag not in locmaps.ALLOWED_TAGS


@pytest.mark.parametrize("bad_at", [True, 5, "zzz", [1, 2], {"player": "x"}, {"player": [1]}, {"player": [99999, 1]}])
def test_import_with_a_broken_position_does_not_crash_and_keeps_the_old_one(gm, world, bad_at):
    before = next(o for o in detail(gm, world)["objects"] if o["key"] == "О1")["at"]
    r = gm.post(f"/api/gm/locmaps/{world}/import", json={"objects": [{"key": "О1", "name": "Открытая", "at": bad_at}]})
    assert r.status_code == 200, r.text
    assert next(o for o in detail(gm, world)["objects"] if o["key"] == "О1")["at"] == before
