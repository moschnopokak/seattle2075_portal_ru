"""«Кто свободен» в форме новой записи: занятость по видимым записям, маски мастера, чужие личные дела, вредные названия."""
import pytest

from helpers import entry, ok, remove
from ui_support import open_page

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]

PAYLOAD = "<b>свободен</b><img src=x onerror=__xss=1>"      # не повторяет вредные строки других тестов: корзина у них общая
TITLES = {PAYLOAD, "СЕКРЕТ-личное дело", "Моя встреча"}
DAY = "2075-09-03"                       # среда


def clean_trash(gm):
    for t in ok(gm.get("/api/gm/trash"))["items"]:
        if t["title"] in TITLES or t["title"].startswith("Тайный план"):
            gm.post(f"/api/gm/trash/{t['id']}/purge")


@pytest.fixture
def scene(gm, gate, rig, hag):
    """Риг и Хаганэ встречаются вечером 3 сентября (видно всем); у Хаганэ есть личное дело 4 сентября; у Рига облава 5-го."""
    ids = []
    shared = ok(rig.post("/api/entries", json=entry(char="rig", title=PAYLOAD, who=["hagane"], **{"from": DAY, "to": DAY}, tod="вечер")))
    ids.append(next(e["id"] for e in shared["state"]["entries"] if e["title"] == PAYLOAD))
    private = ok(hag.post("/api/entries", json=entry(char="hagane", title="СЕКРЕТ-личное дело", who=["elijah"], vis="лично",
                                                    **{"from": "2075-09-04", "to": "2075-09-04"}, tod="вечер")))
    ids.append(next(e["id"] for e in private["state"]["entries"] if e["title"] == "СЕКРЕТ-личное дело"))
    plan = ok(gm.post("/api/gm/items/plan", json={"title": "Тайный план", "from": "2075-09-05", "to": "2075-09-05", "note": "СЕКРЕТ-детали",
                                                 "cover": {"title": "Облава", "note": "", "who": ["rig", "gate"]}}))
    plan_ids = [next(p["id"] for p in plan["state"]["plan"] if p["title"] == "Тайный план")]
    only_rig = ok(gm.post("/api/gm/items/plan", json={"title": "Тайный план для Рига", "from": "2075-09-06", "to": "2075-09-06", "note": "СЕКРЕТ-детали",
                                                     "cover": {"title": "Личная маска Рига", "note": "", "who": ["rig"]}}))
    plan_ids.append(next(p["id"] for p in only_rig["state"]["plan"] if p["title"] == "Тайный план для Рига"))
    yield
    for i in ids:
        remove(gm, i)
    for i in plan_ids:
        gm.post(f"/api/gm/items/plan/{i}/delete")
    clean_trash(gm)


@pytest.fixture
def page(browser, live_url, scene):
    problems = []
    ctx, pg = open_page(browser, live_url, 102, problems)           # Гейт
    pg.evaluate("async()=>{const r=await fetch('/api/state',{credentials:'same-origin'});applyState(await r.json());}")
    yield pg
    ctx.close()
    assert not problems, problems


def open_form(page, day=DAY):
    page.evaluate("d=>{UI.section='cal';render();openForm(d)}", day)
    page.wait_for_selector("#entry-form", timeout=10000)


def pick(page, char, on=True):
    box = page.locator(f'#entry-form input[name="who"][value="{char}"]')
    box.check() if on else box.uncheck()


def free_text(page):
    return page.inner_text("#free-box")


def check_clean(page):
    n = page.evaluate("()=>({xss:window.__xss||0,img:document.querySelectorAll('img[src=\"x\"]').length,csp:(window.__csp||[]).length})")
    assert n == {"xss": 0, "img": 0, "csp": 0}, n


def test_free_box_starts_with_the_author_only(page):
    open_form(page, "2075-09-20")
    text = free_text(page)
    assert "Гейт" in text and "свободен(а)" in text and "свободны все" in text


def test_busy_participant_is_shown_with_the_reason_and_hostile_title_stays_text(page):
    open_form(page)
    page.select_option('#entry-form select[name="tod"]', "вечер")
    pick(page, "rig")
    text = free_text(page)
    assert "Риг" in text and "занят(а)" in text and PAYLOAD in text and "вечер" in text
    assert "Ближайшие дни, когда свободны все" in text
    check_clean(page)


def test_other_time_of_day_is_free(page):
    open_form(page)
    page.select_option('#entry-form select[name="tod"]', "утро")
    pick(page, "rig")
    assert "Риг свободен(а)" in free_text(page).replace("\n", " ") or "свободны все" in free_text(page)


def test_someone_elses_private_entry_is_not_shown(page):
    open_form(page, "2075-09-04")
    page.select_option('#entry-form select[name="tod"]', "вечер")
    pick(page, "hagane")
    text = free_text(page)
    assert "Хаганэ" in text and "свободен(а)" in text and "СЕКРЕТ" not in text
    assert "СЕКРЕТ" not in page.inner_text("body")
    check_clean(page)


def test_gm_mask_is_shown_as_a_common_event_without_details(page):
    open_form(page, "2075-09-05")
    pick(page, "rig")
    text = free_text(page)
    assert "Гейт занят(а)" in text.replace("\n", " ") and "Риг занят(а)" in text.replace("\n", " ")     # маска касается и Гейта, и Рига
    assert "общее событие «Облава»" in text and "СЕКРЕТ" not in text and "Тайный план" not in text


def test_a_mask_meant_for_someone_else_is_invisible_to_the_viewer(page):
    open_form(page, "2075-09-06")
    pick(page, "rig")
    text = free_text(page)
    assert "Риг свободен(а)" in text.replace("\n", " ") and "маска" not in text.lower() and "СЕКРЕТ" not in text


def test_suggested_day_fills_the_dates_and_everyone_is_free_there(page):
    open_form(page)
    page.select_option('#entry-form select[name="tod"]', "вечер")
    pick(page, "rig")
    button = page.locator('#free-box [data-act="free-pick"]').first
    chosen = button.get_attribute("data-d")
    assert chosen > DAY or chosen < DAY
    button.click()
    assert page.input_value('#entry-form select[name="from"]') == chosen and page.input_value('#entry-form select[name="to"]') == chosen
    assert "свободны все" in free_text(page)


def test_free_box_follows_changes_of_the_form(page):
    open_form(page)
    page.select_option('#entry-form select[name="tod"]', "вечер")
    pick(page, "rig")
    assert "занят(а)" in free_text(page)
    page.select_option('#entry-form select[name="from"]', "2075-09-10")
    page.select_option('#entry-form select[name="to"]', "2075-09-10")
    assert "занят(а)" not in free_text(page)
    pick(page, "rig", False)
    assert "Риг" not in free_text(page)


def test_editing_an_entry_does_not_count_it_against_itself(page, gate, gm):
    mine = ok(gate.post("/api/entries", json=entry(char="gate", title="Моя встреча", who=["rig"], **{"from": "2075-09-12", "to": "2075-09-12"}, tod="вечер")))
    eid = next(e["id"] for e in mine["state"]["entries"] if e["title"] == "Моя встреча")
    try:
        page.evaluate("async()=>{const r=await fetch('/api/state',{credentials:'same-origin'});applyState(await r.json());}")
        page.evaluate("id=>{UI.section='cal';render();openForm('2075-09-12',S.entries.find(e=>e.id===id))}", eid)
        page.wait_for_selector("#entry-form", timeout=10000)
        text = free_text(page)
        assert "занят(а)" not in text and "свободны все" in text
    finally:
        remove(gm, eid)
        clean_trash(gm)
