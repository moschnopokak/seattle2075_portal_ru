"""Карты локаций в браузере (строгий CSP): мастер собирает карту, игрок видит только своё, предпросмотр, пометки группы, телефон.
Рисунок показывается как картинка, поэтому код внутри SVG выполниться не может; проверяем и это."""
import json

import pytest

from app import db
from conftest import GM, RIG
from helpers import ok
from test_locmaps import SECRET, SVG, SVG_GM, add, make_map, upload
from ui_support import open_page

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]

EVIL = "<img src=x onerror=__xss=1 id=lm>"
EVIL_SVG = SVG.replace("</svg>", '<script>window.__xss=1</script><rect width="5" height="5" onload="window.__xss=1"/></svg>')


@pytest.fixture(autouse=True)
def clean_tables(started):
    yield
    for table in ("locmap_files", "locmap_feed", "locmap_pins", "outbox"):
        db.conn().execute(f"DELETE FROM {table}")


@pytest.fixture
def world(gm, sandbox):
    mid = make_map(gm, name="Роща", vis="стол")
    ok(upload(gm, mid, "player", EVIL_SVG))
    ok(upload(gm, mid, "gm", SVG_GM))
    add(gm, mid, name="Открытая", key="О1", vis="стол", note="Видно всем", at={"player": [200, 150], "gm": [220, 160]})
    add(gm, mid, name="Скрытая", key="О2", vis="мастер", at={"player": [400, 300], "gm": [420, 310]})
    return mid


def make_page(browser, live_url, tg_id=GM, width=1100):
    problems = []
    ctx, page = open_page(browser, live_url, tg_id, problems)
    if width != 1100:
        page.set_viewport_size({"width": width, "height": 800})
    page.evaluate("()=>{UI.section='maps';render()}")
    return ctx, page, problems


def drawing_ready(page):
    page.wait_for_function("()=>{const i=document.querySelector('#lm-map img.leaflet-image-layer');return !!i&&i.complete&&i.naturalWidth>0}", timeout=15000)


def no_leaks(page):
    n = page.evaluate("()=>({xss:window.__xss||0,img:document.querySelectorAll('img[src=\"x\"]').length,csp:(window.__csp||[]).length})")
    assert n == {"xss": 0, "img": 0, "csp": 0}, n


def test_master_builds_a_map_from_nothing(browser, live_url, gm, sandbox):
    ctx, page, problems = make_page(browser, live_url)
    try:
        assert "Карт локаций пока нет" in page.inner_text("#main")
        page.click('#main [data-act="lm-map-new"]')
        page.fill('.lm-form[data-lm="map"] [name="name"]', "Роща")
        page.fill('.lm-form[data-lm="map"] [name="note"]', "Парк на окраине")
        page.check('.lm-form[data-lm="map"] input[name="vis"][value="стол"]')
        page.click('.lm-form[data-lm="map"] button[type="submit"]')
        page.wait_for_selector("#lm-map >> text=Рисунок игроков не загружен", timeout=10000)
        page.click('[data-act="lm-files"]')
        page.set_input_files('[data-lm-file="player"]', files=[{"name": "g.svg", "mimeType": "image/svg+xml", "buffer": EVIL_SVG.encode()}])
        page.wait_for_selector("#panel >> text=загружен, 800×600", timeout=10000)
        page.click('#panel [data-act="close"]')
        drawing_ready(page)
        assert page.evaluate("()=>window.__xss||0") == 0                                  # код из SVG не выполнился
        page.click('[data-act="lm-mode"]')
        page.click("#lm-map", position={"x": 300, "y": 200})
        page.wait_for_selector('.lm-form[data-lm="obj"]', timeout=10000)
        page.fill('.lm-form[data-lm="obj"] [name="name"]', "Ворота")
        page.fill('.lm-form[data-lm="obj"] [name="key"]', "О1")
        page.fill('.lm-form[data-lm="obj"] [name="note"]', "Железные, на цепи")
        page.fill('.lm-form[data-lm="obj"] [name="gm_note"]', f"{SECRET}-метка")
        page.click('.lm-form[data-lm="obj"] button[type="submit"]')
        page.wait_for_selector("#lm-map .lm-pin span", timeout=10000)
        assert page.locator("#lm-map .lm-pin").count() == 1 and "О1" in page.inner_text("#lm-map .lm-pin span")
        assert "скрыта от игроков" in page.inner_text("#lm-tab")                          # новая метка по умолчанию скрыта
        mid = ok(gm.get("/api/state"))["locmaps"][0]["id"]
        obj = ok(gm.get(f"/api/locmaps/{mid}"))["objects"][0]
        assert obj["vis"] == "мастер" and obj["name"] == "Ворота" and obj["at"]["player"] and obj["gm_note"] == f"{SECRET}-метка"
        page.click("#lm-map .lm-pin span >> nth=0")
        page.wait_for_selector("#panel >> text=Заметка мастера", timeout=5000)
        page.click('#panel [data-act="lm-obj-show"]')
        page.wait_for_function("()=>!document.querySelector('#lm-tab').textContent.includes('скрыта от игроков')", timeout=10000)
        feed = ok(gm.get(f"/api/locmaps/{mid}"))["feed"]
        assert [f["text"] for f in feed] and "Ворота" in feed[0]["text"]                  # открытие записано в ленту
        no_leaks(page)
    finally:
        ctx.close()
    assert not problems


def test_master_switches_between_the_two_drawings(browser, live_url, gm, world):
    ctx, page, problems = make_page(browser, live_url)
    try:
        drawing_ready(page)
        assert page.get_attribute('[data-act="lm-role"][data-v="player"]', "aria-pressed") == "true"
        assert page.locator("#lm-map .lm-pin").count() == 2                              # у мастера на рисунке игроков обе метки
        page.click('[data-act="lm-role"][data-v="gm"]')
        page.wait_for_function("()=>document.querySelector('#lm-map img.leaflet-image-layer')&&document.querySelector('#lm-map img.leaflet-image-layer').src.includes('/gm.svg')", timeout=10000)
        drawing_ready(page)
        assert page.locator("#lm-map .lm-pin").count() == 2
        page.click('[data-act="lm-obj"] >> nth=1')
        page.wait_for_selector("#panel >> text=Заметка мастера", timeout=5000)
        assert SECRET in page.inner_text("#panel")
        no_leaks(page)
    finally:
        ctx.close()
    assert not problems


def test_player_sees_his_drawing_and_open_marks_only(browser, live_url, gm, rig, world):
    ctx, page, problems = make_page(browser, live_url, RIG)
    try:
        drawing_ready(page)
        assert "Локации" in page.inner_text("#nav")
        assert page.locator("#lm-map .lm-pin").count() == 1
        page.wait_for_selector("#lm-tab .lm-row", timeout=10000)
        text = page.inner_text("#main")
        assert "Открытая" in text and "Скрытая" not in text and SECRET not in text
        assert page.locator('[data-act="lm-role"], [data-act="lm-files"], [data-act="lm-import"], [data-act="lm-map-edit"], [data-act="lm-mode"][data-v="mark"]').count() == 0
        page.click("#lm-map .lm-pin span >> nth=0")
        page.wait_for_selector("#panel >> text=Видно всем", timeout=5000)
        assert SECRET not in page.inner_text("#panel") and page.locator('#panel [data-act^="lm-obj"], #panel [data-act="lm-status"]').count() == 0
        assert not any("/gm.svg" in u for u in page.recorded)                              # рисунок мастера игрок даже не запрашивал
        assert page.evaluate("()=>fetch('/locmap/%s/gm.svg').then(r=>r.status)" % world) in (403, 404)
        assert SECRET not in page.evaluate("()=>JSON.stringify(S)")
        no_leaks(page)
    finally:
        ctx.close()
    assert not problems


def test_feed_shows_changes_and_the_master_adds_an_announcement(browser, live_url, gm, rig, world):
    ok(gm.post(f"/api/gm/locmaps/{world}/objects", json={"id": next(o["id"] for o in ok(gm.get(f"/api/locmaps/{world}"))["objects"] if o["key"] == "О1"), "status": "cleared"}))
    ctx, page, problems = make_page(browser, live_url)
    try:
        page.click('[data-act="lm-tab"][data-v="feed"]')
        page.wait_for_selector("#lm-tab .lm-feed", timeout=10000)
        assert "расчищено" in page.inner_text("#lm-tab")
        page.fill('.lm-feedform [name="text"]', "Патруль ушёл на север")
        page.click('.lm-feedform button[type="submit"]')
        page.wait_for_function("()=>document.querySelector('#lm-tab').textContent.includes('Патруль ушёл на север')", timeout=10000)
    finally:
        ctx.close()
    assert not problems
    ctx, page, problems = make_page(browser, live_url, RIG)
    try:
        page.click('[data-act="lm-tab"][data-v="feed"]')
        page.wait_for_selector("#lm-tab .lm-feed", timeout=10000)
        text = page.inner_text("#lm-tab")
        assert "Патруль ушёл на север" in text and "расчищено" in text and "Убрать" not in text and page.locator(".lm-feedform").count() == 0
    finally:
        ctx.close()
    assert not problems


def test_player_adds_and_removes_a_group_note(browser, live_url, gm, rig, world):
    ctx, page, problems = make_page(browser, live_url, RIG)
    try:
        drawing_ready(page)
        page.click('[data-act="lm-mode"][data-v="pin"]')
        page.click("#lm-map", position={"x": 200, "y": 250})
        page.wait_for_selector('.lm-form[data-lm="pin"]', timeout=10000)
        page.fill('.lm-form[data-lm="pin"] [name="text"]', "Тропы врут")
        page.click('.lm-form[data-lm="pin"] button[type="submit"]')
        page.wait_for_selector("#lm-map .lm-note span", timeout=10000)
        assert "Тропы врут" in page.inner_text("#lm-tab")
        assert ok(gm.get(f"/api/locmaps/{world}"))["pins"][0]["text"] == "Тропы врут"
        page.click('#lm-tab [data-act="lm-pin-del"]')
        page.click('#lm-tab [data-act="lm-pin-del"]')                                      # удаление просит подтвердить
        page.wait_for_function("()=>!document.querySelector('#lm-map .lm-note')", timeout=10000)
        assert ok(gm.get(f"/api/locmaps/{world}"))["pins"] == []
    finally:
        ctx.close()
    assert not problems


def test_master_preview_shows_what_the_player_sees(browser, live_url, gm, rig, world):
    ctx, page, problems = make_page(browser, live_url)
    try:
        drawing_ready(page)
        page.select_option("#who-select", "rig")
        page.wait_for_function("()=>document.querySelectorAll('#lm-map .lm-pin').length===1", timeout=10000)
        text = page.inner_text("#main")
        assert "Скрытая" not in text and SECRET not in text and "Карта мастера" not in text
        assert page.locator('[data-act="lm-role"], [data-act="lm-files"], [data-act="lm-mode"], [data-act="lm-map-new"]').count() == 0
        assert page.evaluate("()=>document.querySelector('#lm-map img.leaflet-image-layer').src.includes('/player.svg')")
        page.select_option("#who-select", "gm")
        page.wait_for_function("()=>document.querySelectorAll('#lm-map .lm-pin').length===2", timeout=10000)
    finally:
        ctx.close()
    assert not problems


def test_names_and_notes_with_markup_are_text(browser, live_url, gm, rig, world):
    add(gm, world, name=EVIL[:80], key="Э", note=EVIL, vis="стол", at={"player": [500, 100], "gm": [500, 100]})
    for tg in (GM, RIG):
        ctx, page, problems = make_page(browser, live_url, tg)
        try:
            drawing_ready(page)
            page.wait_for_selector("#lm-tab .lm-row", timeout=10000)
            page.click('#lm-tab .lm-row >> text=onerror')
            page.wait_for_selector("#panel >> text=onerror", timeout=5000)
            no_leaks(page)
        finally:
            ctx.close()
        assert not problems


def test_import_of_marks_from_pasted_json(browser, live_url, gm, world):
    data = {"objects": [{"key": "О1", "name": "Ворота (уточнено)", "kind": "area", "at": {"player": [210, 160]}},
                        {"key": "О9", "name": "Новая", "kind": "thing", "note": "из чата", "at": {"player": [50, 50]}},
                        {"key": "", "name": ""}]}
    ctx, page, problems = make_page(browser, live_url)
    try:
        page.click('[data-act="lm-import"]')
        page.fill('.lm-form[data-lm="import"] [name="json"]', json.dumps(data, ensure_ascii=False))
        page.click('.lm-form[data-lm="import"] button[type="submit"]')
        page.wait_for_selector("#panel >> text=Метки загружены", timeout=10000)
        text = page.inner_text("#panel")
        assert "Добавлено: 1" in text and "Обновлено: 1" in text and "Не прошло проверку: 1" in text
        objs = {o["key"]: o for o in ok(gm.get(f"/api/locmaps/{world}"))["objects"]}
        assert objs["О1"]["name"] == "Ворота (уточнено)" and objs["О1"]["vis"] == "стол"   # видимость при загрузке не меняется
        assert objs["О9"]["vis"] == "мастер"
        page.click('#panel [data-act="close"]')
        page.click('[data-act="lm-import"]')
        page.fill('.lm-form[data-lm="import"] [name="json"]', "{не json")
        page.click('.lm-form[data-lm="import"] button[type="submit"]')
        page.wait_for_function("()=>document.querySelector('#panel .err').textContent.includes('Это не JSON')", timeout=5000)
    finally:
        ctx.close()
    assert not problems


def test_place_card_opens_its_map(browser, live_url, gm, rig, sandbox):
    place = ok(gm.post("/api/gm/items/places", json={"name": "Роща у реки", "type": "other", "x": 900, "y": 1200, "vis": "стол", "note": "", "gm_note": ""}))
    pid = next(p["id"] for p in place["state"]["places"] if p["name"] == "Роща у реки")
    mid = make_map(gm, name="Роща-карта", vis="стол", place=pid)
    ok(upload(gm, mid, "player"))
    ctx, page, problems = make_page(browser, live_url, RIG)
    try:
        page.evaluate("id=>{closePanel();openPlace(id)}", pid)
        page.wait_for_selector('#panel [data-act="lm-open"]', timeout=5000)
        assert "Роща-карта" in page.inner_text("#panel")
        page.click('#panel [data-act="lm-open"]')
        page.wait_for_selector("#lm-map", timeout=10000)
        assert page.evaluate("()=>UI.section") == "maps" and "Роща-карта" in page.inner_text("#main")
    finally:
        ctx.close()
    assert not problems


def test_a_hidden_map_is_not_listed_for_players(browser, live_url, gm, rig, sandbox):
    make_map(gm, name="Секретная", vis="мастер")
    ctx, page, problems = make_page(browser, live_url, RIG)
    try:
        assert "Локации" not in page.inner_text("#nav")                                    # пока открытых карт нет, раздела нет
        assert "Секретная" not in page.evaluate("()=>JSON.stringify(S.locmaps)")
    finally:
        ctx.close()
    assert not problems


@pytest.mark.parametrize("who", [GM, RIG])
def test_nothing_overflows_on_a_phone(browser, live_url, gm, rig, world, who):
    add(gm, world, name="Очень длинное название метки " + "слово" * 12, key="Д", note="Описание " * 80, vis="стол", at={"player": [100, 100]})
    ok(gm.post(f"/api/gm/locmaps/{world}/feed", json={"text": "Длинное объявление " + "слово" * 20, "vis": "стол"}))
    for width in (360, 390):
        ctx, page, problems = make_page(browser, live_url, who, width)
        try:
            drawing_ready(page)
            for tab in ("marks", "feed", "pins"):
                page.click(f'[data-act="lm-tab"][data-v="{tab}"]')
                over = page.evaluate("()=>({page:document.documentElement.scrollWidth-document.documentElement.clientWidth,"
                                     "box:[...document.querySelectorAll('.lm *:not(.leaflet-container *)')].filter(e=>e.getBoundingClientRect().right>document.documentElement.clientWidth+1).map(e=>e.className||e.tagName)})")
                assert over["page"] <= 0 and over["box"] == [], (who, width, tab, over)
            page.click('[data-act="lm-tab"][data-v="marks"]')
            page.click("#lm-tab .lm-row >> nth=0")
            page.wait_for_selector("#panel .lm-notebody", timeout=5000)
            page.wait_for_function("()=>document.getAnimations().every(a=>a.playState!=='running')", timeout=5000)   # панель выезжает сбоку
            over = page.evaluate("()=>[...document.querySelectorAll('#panel *')].filter(e=>e.getBoundingClientRect().right>document.documentElement.clientWidth+1).map(e=>e.className||e.tagName)")
            assert over == [], (who, width, over)
        finally:
            ctx.close()
        assert not problems


def test_master_moves_a_mark_and_the_other_drawing_keeps_its_place(browser, live_url, gm, world):
    obj = next(o for o in ok(gm.get(f"/api/locmaps/{world}"))["objects"] if o["key"] == "О1")
    ctx, page, problems = make_page(browser, live_url)
    try:
        drawing_ready(page)
        page.click("#lm-map .lm-pin span >> nth=0")
        page.wait_for_selector('#panel [data-act="lm-move"]', timeout=5000)
        assert "Переставить" in page.inner_text('#panel [data-act="lm-move"]')
        page.click('#panel [data-act="lm-move"]')
        page.wait_for_selector("#lm-map.lm-adding", timeout=5000)
        assert "сюда встанет метка" in page.inner_text(".lm-tools")
        page.click("#lm-map", position={"x": 600, "y": 100})
        page.wait_for_function("()=>!document.querySelector('#lm-map.lm-adding')", timeout=10000)
        page.wait_for_function("()=>document.querySelector('.toast, #toast')&&document.querySelector('#toast').textContent.includes('Метка сохранена')", timeout=10000)
        now = next(o for o in ok(gm.get(f"/api/locmaps/{world}"))["objects"] if o["key"] == "О1")
        assert now["at"]["player"] != obj["at"]["player"] and now["at"]["gm"] == obj["at"]["gm"]
        page.click('[data-act="lm-mode"][data-v="mark"]')                                   # Esc отменяет режим
        page.wait_for_selector("#lm-map.lm-adding", timeout=5000)
        page.keyboard.press("Escape")
        page.wait_for_function("()=>!document.querySelector('#lm-map.lm-adding')", timeout=5000)
    finally:
        ctx.close()
    assert not problems


def test_a_map_without_the_master_drawing_does_not_trap_the_master(browser, live_url, gm, sandbox):
    mid = make_map(gm, name="Без второго", vis="стол")
    ok(upload(gm, mid, "player"))
    ctx, page, problems = make_page(browser, live_url)
    try:
        page.evaluate("()=>{LM.role='gm';render(true)}")                                  # мастер выбрал «Карту мастера» на другой карте
        drawing_ready(page)
        assert page.locator('[data-act="lm-role"]').count() == 0
        assert "не загружен" not in page.inner_text("#lm-map")
    finally:
        ctx.close()
    assert not problems
