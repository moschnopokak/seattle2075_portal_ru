"""Линейка на карте в настоящем браузере: щелчки, расчёт, режимы, выбор вида транспорта, кнопка в карточке места."""
import pytest

from helpers import ok
from ui_support import open_page

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]

PAYLOAD = '"><img src=x onerror=__xss=1>'


@pytest.fixture
def map_page(browser, live_url, gm):
    """Страница игрока Рига с открытой картой. Возвращает (page, problems)."""
    problems = []
    ctx, page = open_page(browser, live_url, 103, problems)
    page.evaluate("()=>{UI.section='map';render();}")
    page.wait_for_function("()=>typeof MAP!=='undefined'&&MAP&&MAPDATA&&document.querySelector('#map-tools [data-act=map-measure]')", timeout=15000)
    yield page, problems
    ctx.close()
    assert not problems, problems


def click_map(page, x, y):
    """Настоящий щелчок мышью по точке карты с координатами (x, y) в метрах."""
    pos = page.evaluate("""([x,y])=>{const c=MAP.latLngToContainerPoint(LL(x,y)),r=document.getElementById('leaflet').getBoundingClientRect();
        return {x:r.left+c.x,y:r.top+c.y,inside:c.x>0&&c.y>0&&c.x<r.width&&c.y<r.height}}""", [x, y])
    assert pos["inside"], f"точка {x},{y} вне видимой части карты"
    page.mouse.click(pos["x"], pos["y"])


def fit(page, a, b):
    page.evaluate("([a,b])=>MAP.fitBounds(L.latLngBounds(LL(a[0],a[1]),LL(b[0],b[1])).pad(0.35),{animate:false})", [a, b])
    page.wait_for_timeout(150)


def label(page, slug):
    return page.evaluate("s=>MAPDATA.labels.find(l=>l.slug===s).xy", slug)


def test_ruler_measures_and_estimates_travel_time(map_page):
    page, _ = map_page
    page.click('[data-act="map-measure"]')
    assert page.is_visible("#map-measure") and "Щёлкните по карте" in page.inner_text("#map-measure")
    downtown, everett = label(page, "downtown"), label(page, "everett")
    fit(page, downtown, everett)
    click_map(page, *downtown)
    click_map(page, *everett)
    assert page.evaluate("()=>MEASURE.pts.length") == 2
    text = page.inner_text("#map-measure")
    for name in ("Пешком", "Велосипед", "Мотоцикл", "Автомобиль", "Вертолёт"):
        assert name in text, name
    assert "по прямой" in text and "по дорогам для выбранного вида" in text and "магистрали" in text
    # время автомобиля правдоподобно: от получаса до полутора часов
    car = page.evaluate("()=>MEASURE.res[(S.travel.find(t=>t.name==='Автомобиль')).id].minutes")
    assert 30 < car < 90, car
    walk = page.evaluate("()=>MEASURE.res[(S.travel.find(t=>t.name==='Пешком')).id].minutes")
    assert walk > 6 * 60
    assert page.locator("#leaflet path.m-route").count() == 1                  # маршрут нарисован
    assert page.locator("#leaflet .mm").count() == 2                           # две нумерованные метки
    # другой вид транспорта: маршрут перерисовывается по его пути
    page.click('.mm-row:has-text("Вертолёт")')
    assert "m-route-straight" in page.get_attribute("#leaflet path.m-route", "class")
    page.click('.mm-row:has-text("Автомобиль")')
    assert "m-route-straight" not in page.get_attribute("#leaflet path.m-route", "class")


def test_ruler_straight_mode_and_editing_points(map_page):
    page, _ = map_page
    page.click('[data-act="map-measure"]')
    a, b = label(page, "bellevue"), label(page, "tacoma")
    fit(page, a, b)
    click_map(page, *a)
    click_map(page, *b)
    page.click('[data-act="measure-mode"][data-v="straight"]')
    assert page.get_attribute('[data-act="measure-mode"][data-v="straight"]', "aria-pressed") == "true"
    assert "по дорогам для выбранного вида" not in page.inner_text("#map-measure")
    assert "m-route-straight" in page.get_attribute("#leaflet path.m-route", "class")
    direct = page.evaluate("()=>MEASURE.direct")
    expected = page.evaluate("()=>geoDist([MEASURE.pts[0].x,MEASURE.pts[0].y],[MEASURE.pts[1].x,MEASURE.pts[1].y])")
    assert abs(direct - expected) < 1
    assert abs(direct - page.evaluate("([a,b])=>geoDist(a,b)", [a, b])) < 300       # щелчок точен до пикселя карты
    # убрать точку, поменять местами, очистить
    second_x = page.evaluate("()=>MEASURE.pts[1].x")
    page.click('[data-act="measure-reverse"]')
    assert page.evaluate("()=>MEASURE.pts[0].x") == second_x
    page.click('[data-act="measure-del"][data-i="0"]')
    assert page.evaluate("()=>MEASURE.pts.length") == 1 and "Поставьте вторую точку" in page.inner_text("#map-measure")
    page.click('[data-act="measure-clear"]')
    assert page.evaluate("()=>MEASURE.pts.length") == 0
    page.keyboard.press("Escape")
    assert page.is_hidden("#map-measure") and page.evaluate("()=>MEASURE.on") is False


def test_ruler_snaps_to_place_markers_and_starts_from_place_card(map_page, gm):
    page, _ = map_page
    data = ok(gm.post("/api/gm/items/places", json={"name": "Склад «Тест»", "type": "business", "x": 36000, "y": 60000, "vis": "стол"}))
    pid = next(p["id"] for p in data["state"]["places"] if p["name"] == "Склад «Тест»")
    try:
        # место добавлено после загрузки страницы: подтянуть свежее состояние
        page.evaluate("async()=>{const r=await fetch('/api/state',{credentials:'same-origin'});applyState(await r.json());refreshPlaces();}")
        page.wait_for_function("id=>!!placeById(id)", arg=pid)
        page.evaluate("id=>openPlace(id)", pid)
        page.click('[data-act="measure-from"]')
        assert page.evaluate("()=>MEASURE.on") is True and page.is_hidden("#overlay")
        assert "Склад «Тест»" in page.inner_text("#map-measure")
        # вторая точка щелчком по самой метке другого места: берётся его название, а не координаты
        page.evaluate("id=>focusPlace(placeById(id))", pid)
        assert page.evaluate("()=>MEASURE.pts[0].place") == pid
    finally:
        gm.post(f"/api/gm/items/places/{pid}/delete")


def test_hostile_place_name_is_shown_as_text_in_ruler(map_page, gm):
    page, problems = map_page
    data = ok(gm.post("/api/gm/items/places", json={"name": PAYLOAD, "type": "other", "x": 40000, "y": 50000, "vis": "стол"}))
    pid = next(p["id"] for p in data["state"]["places"] if p["name"] == PAYLOAD)
    try:
        page.evaluate("async()=>{const r=await fetch('/api/state',{credentials:'same-origin'});applyState(await r.json());refreshPlaces();}")
        page.wait_for_function("id=>!!placeById(id)", arg=pid)
        page.evaluate("id=>measureStartFrom(id)", pid)
        page.wait_for_timeout(200)
        assert PAYLOAD in page.inner_text("#map-measure")                     # видно буквами
        n = page.evaluate("()=>({xss:window.__xss||0,img:document.querySelectorAll('img[src=\"x\"]').length})")
        assert n == {"xss": 0, "img": 0}
    finally:
        gm.post(f"/api/gm/items/places/{pid}/delete")
    assert not problems


def test_gm_edits_travel_profiles_in_the_panel(browser, live_url, gm):
    problems = []
    ctx, page = open_page(browser, live_url, 1, problems)
    try:
        page.evaluate("()=>{UI.section='gm';render();}")
        assert "Транспорт и скорости" in page.inner_text("#main") and "Автомобиль" in page.inner_text("#main")
        page.click('[data-act="new-item"][data-kind="travel"]')
        page.fill('#item-form [name="name"]', "Тестовый катер")
        page.fill('#item-form [name="motorway"]', "0")
        page.fill('#item-form [name="trunk"]', "0")
        page.fill('#item-form [name="primary"]', "12")
        page.fill('#item-form [name="off"]', "9.5")
        page.fill('#item-form [name="delay"]', "7")
        page.click('#item-form [type="submit"]')
        page.wait_for_function("()=>S.travel.some(t=>t.name==='Тестовый катер')", timeout=5000)
        made = page.evaluate("()=>S.travel.find(t=>t.name==='Тестовый катер')")
        assert (made["primary"], made["off"], made["delay"], made["kind"]) == (12, 9.5, 7, "roads")
        # переключение на «по прямой» прячет дорожные скорости
        page.evaluate("id=>openItemForm('travel',id)", made["id"])
        page.check('#item-form [name="tkind"][value="straight"]')
        assert page.is_hidden("#road-speeds") and page.is_visible("#speed-box")
        page.fill('#item-form [name="speed"]', "55")
        page.click('#item-form [type="submit"]')
        page.wait_for_function("id=>S.travel.find(t=>t.id===id).kind==='straight'", arg=made["id"], timeout=5000)
        assert page.evaluate("id=>S.travel.find(t=>t.id===id).off", made["id"]) == 55
        gm.post(f"/api/gm/items/travel/{made['id']}/delete")
    finally:
        ctx.close()
    assert not problems, problems
