"""Импорт мест на карту в настоящем браузере (строгий CSP): набор «Seattle 2072», KML, фоновые места и слой «Фон»."""
import json
from pathlib import Path

import pytest

from helpers import ok
from ui_support import open_page

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]

MAP_DIR = Path(__file__).resolve().parent.parent / "static" / "map"
GRID = json.loads((MAP_DIR / "llgrid.json").read_text(encoding="utf-8"))
PAYLOAD = '"><img src=x onerror=__xss=1>'
URL = "/api/gm/places/import"


def places(gm):
    return gm.get("/api/state").json()["places"]


def kml_point_near(x, y):
    """Долгота и широта узла сетки, ближайшего к точке карты (x, y): так KML ложится внутрь карты."""
    nx = GRID["nx"]
    k = min(range(len(GRID["x"])), key=lambda n: (GRID["x"][n] - x) ** 2 + (GRID["y"][n] - y) ** 2)
    return GRID["lon0"] + (k % nx) * GRID["step"] + 0.001, GRID["lat0"] + (k // nx) * GRID["step"] + 0.001


def kml(*placemarks):
    body = "".join(f"<Folder><name>{folder}</name>" + "".join(f"<Placemark><name>{name}</name><description>{desc}</description><Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>"
                                                              for name, desc, lon, lat in items) + "</Folder>" for folder, items in placemarks)
    return f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Тест</name>{body}</Document></kml>'.encode()


@pytest.fixture
def gm_page(browser, live_url, gm, sandbox):
    """Страница мастера с открытой картой. Возвращает (page, problems)."""
    problems = []
    ctx, page = open_page(browser, live_url, 1, problems)
    page.evaluate("()=>{UI.section='map';render();}")
    page.wait_for_function("()=>typeof MAP!=='undefined'&&MAP&&MAPDATA&&document.querySelector('#map-tools [data-act=map-add]')", timeout=15000)
    yield page, problems
    ctx.close()
    assert not problems, problems


def open_import(page):
    page.click('[data-act="map-import"]')
    page.wait_for_selector("#imp .imp-g", timeout=15000)


def test_only_the_gm_gets_the_import_button(browser, live_url, gm_page):
    page, _ = gm_page
    assert page.locator('[data-act="map-import"]').count() == 1
    problems = []
    ctx, rig = open_page(browser, live_url, 103, problems)
    try:
        rig.evaluate("()=>{UI.section='map';render();}")
        rig.wait_for_function("()=>typeof MAP!=='undefined'&&MAP&&document.querySelector('#map-tools')", timeout=15000)
        assert rig.locator('[data-act="map-import"]').count() == 0
        assert rig.locator('[data-layer="bg"]').count() == 1                    # а переключатель «Фон» есть у всех
    finally:
        ctx.close()
    assert not problems, problems


def test_canon_set_is_listed_and_counted(gm_page):
    page, _ = gm_page
    open_import(page)
    assert "Импорт мест" in page.inner_text("#panel") and "Seattle 2072" in page.inner_text("#imp")
    n = page.evaluate("()=>IMP.on.size")
    assert n > 20 and page.inner_text('[data-act="imp-go"]') == f"Добавить выбранные: {n}"
    assert page.locator(".imp-g").count() >= 8
    assert page.locator(".imp-items:not([hidden])").count() == 0               # группы свёрнуты
    page.click(".imp-tog")
    assert page.locator(".imp-items:not([hidden]) .imp-row").count() >= 1
    assert page.evaluate("()=>POI.items.every(i=>i.type in PLACE_TYPES)")      # у каждой точки набора есть тип, который знает интерфейс


def test_import_selected_places(gm_page, gm):
    page, _ = gm_page
    before = len(places(gm))
    open_import(page)
    page.click(".imp-tog")
    n = page.evaluate("()=>IMP.on.size")
    first = page.locator(".imp-items:not([hidden]) .imp-row input").first
    was_on = first.is_checked()
    first.click()
    expected = n - 1 if was_on else n + 1
    assert page.inner_text('[data-act="imp-go"]') == f"Добавить выбранные: {expected}"
    page.click('[data-act="imp-go"]')
    page.wait_for_function("()=>typeof IMP!=='undefined'&&IMP===null", timeout=15000)
    assert page.inner_text("#toast") == f"Добавлено мест: {expected}"
    assert len(places(gm)) == before + expected
    assert page.evaluate("()=>S.places.length") == before + expected          # карта обновилась без перезагрузки страницы
    assert page.locator("#overlay").is_hidden()


def test_imported_places_are_not_offered_twice(gm_page, gm):
    page, _ = gm_page
    open_import(page)
    first_count = page.evaluate("()=>IMP.on.size")
    page.click('[data-act="imp-go"]')
    page.wait_for_function("()=>IMP===null", timeout=15000)
    open_import(page)
    assert page.evaluate("()=>IMP.on.size") < first_count                      # то, что уже на карте, заранее не отмечено
    assert page.evaluate("()=>IMP.items.filter(i=>i.dup).length") >= first_count


def test_background_layer_hides_background_places_and_is_remembered(gm_page, gm):
    page, _ = gm_page
    ok(gm.post(URL, json={"items": [{"name": "Фоновая лавка", "type": "shop", "x": 36100, "y": 50100, "vis": "стол", "bg": True},
                                    {"name": "Обычная лавка", "type": "shop", "x": 36300, "y": 50300, "vis": "стол", "bg": False}]}))
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("#nav button", timeout=15000)
    page.evaluate("()=>{UI.section='map';render();}")
    page.wait_for_function("()=>typeof MAP!=='undefined'&&MAP&&document.querySelector('#leaflet .pl')", timeout=15000)
    assert page.locator("#leaflet .pl-bg").count() >= 1
    page.uncheck('[data-layer="bg"]')
    assert page.locator("#leaflet .pl-bg").count() == 0
    assert page.locator("#leaflet .pl:not(.pl-bg)").count() >= 1               # обычные места остались
    assert json.loads(page.evaluate("()=>localStorage.getItem('seattle2075-map-layers')"))["bg"] is False
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("#nav button", timeout=15000)
    page.evaluate("()=>{UI.section='map';render();}")
    page.wait_for_function("()=>typeof MAP!=='undefined'&&MAP&&document.querySelector('#map-tools [data-layer=bg]')", timeout=15000)
    assert not page.is_checked('[data-layer="bg"]') and page.locator("#leaflet .pl-bg").count() == 0
    page.check('[data-layer="bg"]')
    assert page.locator("#leaflet .pl-bg").count() >= 1


def test_place_card_marks_background_places(gm_page, gm):
    page, _ = gm_page
    data = ok(gm.post("/api/gm/items/places", json={"name": "Карточка фона", "type": "leisure", "x": 36000, "y": 50000, "vis": "стол", "bg": True}))
    pid = next(p["id"] for p in data["state"]["places"] if p["name"] == "Карточка фона")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("#nav button", timeout=15000)
    page.evaluate("p=>{UI.section='map';render();setTimeout(()=>openPlace(p),50);}", pid)
    page.wait_for_selector("#panel h2", timeout=15000)
    text = page.inner_text("#panel")
    assert "Карточка фона" in text and "Еда и отдых" in text and "фон" in text


def test_place_form_has_the_background_checkbox(gm_page, gm):
    page, _ = gm_page
    page.evaluate("()=>openItemForm('places',null,{x:36200,y:50200})")
    page.wait_for_selector("#item-form input[name=bg], form input[name=bg]", timeout=10000)
    page.fill("input[name=name]", "Форма фона")
    page.select_option("select[name=type]", "medical")
    page.check("input[name=bg]")
    page.click('form button[type="submit"]')
    page.wait_for_function("()=>S.places.some(p=>p.name==='Форма фона')", timeout=10000)
    saved = next(p for p in places(gm) if p["name"] == "Форма фона")
    assert saved["bg"] is True and saved["type"] == "medical"


def test_kml_import_with_hostile_text(gm_page, gm):
    page, _ = gm_page
    lon, lat = kml_point_near(40000, 60000)
    data = kml(("Слой " + PAYLOAD.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;"),
                [(PAYLOAD.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;"), "описание", lon, lat),
                 ("Вторая", "<![CDATA[строка<br>два]]>", lon + 0.002, lat + 0.002)]))
    open_import(page)
    page.click('[data-act="imp-src"][data-v="kml"]')
    page.wait_for_selector("#imp-file")
    page.set_input_files("#imp-file", files=[{"name": "my.kml", "mimeType": "application/vnd.google-earth.kml+xml", "buffer": data}])
    page.wait_for_selector("#imp .imp-g", timeout=15000)
    assert "my.kml" in page.inner_text("#imp") and "точек 2" in page.inner_text("#imp")
    page.select_option("select[data-imp-type]", "medical")
    page.click(".imp-tog")
    shown = page.inner_text("#imp")
    assert PAYLOAD in shown                                                   # чужой текст показан буквами, а не разметкой
    assert page.evaluate("()=>window.__xss") is None
    assert page.locator("#imp img").count() == 0
    before = len(places(gm))
    page.click('[data-act="imp-go"]')
    page.wait_for_function("()=>IMP===null", timeout=15000)
    new = places(gm)[before:]
    assert len(new) == 2 and all(p["type"] == "medical" and p["vis"] == "стол" for p in new)
    assert {p["name"] for p in new} == {PAYLOAD, "Вторая"}
    assert all(p["gm_note"].startswith("Из KML") for p in new)
    assert page.evaluate("()=>window.__xss") is None


def test_kml_visible_only_to_the_gm_when_chosen(gm_page, gm, rig):
    page, _ = gm_page
    lon, lat = kml_point_near(45000, 65000)
    open_import(page)
    page.click('[data-act="imp-src"][data-v="kml"]')
    page.wait_for_selector("#imp-file")
    page.set_input_files("#imp-file", files=[{"name": "secret.kml", "mimeType": "application/vnd.google-earth.kml+xml",
                                              "buffer": kml(("Тайное", [("Явка СЕКРЕТ", "x", lon, lat)]))}])
    page.wait_for_selector("#imp .imp-g")
    page.check('input[name="imp-vis"][value="мастер"]')
    page.click('[data-act="imp-go"]')
    page.wait_for_function("()=>IMP===null", timeout=15000)
    assert any(p["name"] == "Явка СЕКРЕТ" for p in places(gm))
    assert "Явка СЕКРЕТ" not in rig.get("/api/state").text


def test_kmz_archive_is_explained_not_parsed(gm_page, gm):
    page, _ = gm_page
    open_import(page)
    page.click('[data-act="imp-src"][data-v="kml"]')
    page.wait_for_selector("#imp-file")
    before = len(places(gm))
    page.set_input_files("#imp-file", files=[{"name": "my.kmz", "mimeType": "application/vnd.google-earth.kmz", "buffer": b"PK\x03\x04" + b"\x00" * 50}])
    page.wait_for_function("()=>document.getElementById('imp-err').textContent.includes('KMZ')", timeout=10000)
    assert page.inner_text('[data-act="imp-go"]') == "Добавить выбранные: 0" and page.is_disabled('[data-act="imp-go"]')
    assert len(places(gm)) == before


def test_points_outside_the_map_are_skipped_and_counted(gm_page):
    page, _ = gm_page
    lon, lat = kml_point_near(40000, 60000)
    open_import(page)
    page.click('[data-act="imp-src"][data-v="kml"]')
    page.wait_for_selector("#imp-file")
    page.set_input_files("#imp-file", files=[{"name": "far.kml", "mimeType": "application/vnd.google-earth.kml+xml",
                                              "buffer": kml(("Слой", [("Здесь", "", lon, lat), ("Очень далеко", "", 10.0, 10.0)]))}])
    page.wait_for_selector("#imp .imp-g")
    text = page.inner_text("#imp")
    assert "точек 1" in text and "за краем карты пропущено 1" in text
