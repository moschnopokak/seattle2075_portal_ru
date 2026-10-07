"""Карты в браузере (строгий CSP), всё, что помогает на игре: значок «новое», фишка «Мы здесь», прогресс, вопросы мастеру, сроки, счётчик мастера,
журнал с отменой, связи с досье, картинка карты. Игрок не видит счётчиков и скрытых сроков ни на экране, ни в данных страницы."""
import pytest

from app import db
from conftest import GM, RIG
from helpers import ok
from test_locmaps import SECRET, SVG_GM, add, detail, make_map, upload
from test_ui_locmaps import click_drawing, drawing_ready, make_page, no_leaks, zone_objects

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]

TRI = [[100, 100], [400, 100], [250, 350]]
SQUARE = [[500, 400], [700, 400], [700, 560], [500, 560]]


@pytest.fixture(autouse=True)
def clean_tables(started):
    yield
    for table in ("locmap_files", "locmap_feed", "locmap_pins", "locmap_log", "outbox"):
        db.conn().execute(f"DELETE FROM {table}")


@pytest.fixture
def play(gm, sandbox):
    mid = make_map(gm, name="Роща", vis="стол")
    ok(upload(gm, mid, "player"))
    ok(upload(gm, mid, "gm", SVG_GM))
    ok(gm.post("/api/gm/items/locmaps", json={"id": mid, "name": "Роща", "vis": "стол", "counter": "Фон"}))
    add(gm, mid, name="Опушка", key="О1", vis="стол", play=True, shape={"player": TRI}, at={}, count=3, fx=[{"to": "self", "delta": -2}], note="Видно всем")
    add(gm, mid, name="Глубина", key="Г1", vis="стол", play=True, shape={"player": SQUARE}, at={}, count=4,
        fx=[{"to": "self", "delta": -2}, {"to": "Сердце", "delta": -1}])
    add(gm, mid, name="Сердце", key="Сердце", vis="мастер", at={"player": [650, 100]}, count=5, gm_note=f"{SECRET}-сердце")
    return mid


def counts(gm, mid):
    return {o["key"]: o["count"] for o in zone_objects(gm, mid).values()}


def badge(page):
    return page.evaluate("()=>{const b=[...document.querySelectorAll('#nav button')].find(x=>x.dataset.nav==='maps');const n=b&&b.querySelector('.nav-badge');return n?n.textContent:''}")


def wait_zone(page):
    drawing_ready(page)
    page.wait_for_selector("#lm-map .lm-zone", timeout=10000)


def open_card(page, x, y):
    click_drawing(page, x, y)
    page.wait_for_selector("#panel h2", timeout=5000)
    page.wait_for_function("()=>document.getAnimations().every(a=>a.playState!=='running')", timeout=5000)


# ---------------------------------------------------------------- значок «новое»

def test_the_tab_shows_new_entries_until_they_are_seen(browser, live_url, gm, rig, play):
    ok(gm.post(f"/api/gm/locmaps/{play}/feed", json={"text": "Патруль сменился"}))
    ctx, page, problems = make_page(browser, live_url, RIG)
    try:
        page.evaluate("()=>{UI.section='now';render()}")
        n = int(badge(page))
        assert n >= 1                                                                         # записи ленты, которых человек ещё не видел
        page.click('#nav [data-nav="maps"]')
        wait_zone(page)
        page.wait_for_function("()=>![...document.querySelectorAll('#nav button')].find(x=>x.dataset.nav==='maps').querySelector('.nav-badge')", timeout=10000)
        page.evaluate("()=>{UI.section='now';render()}")
        assert badge(page) == ""                                                              # просмотрено: значка нет
        ok(gm.post(f"/api/gm/locmaps/{play}/feed", json={"text": "Ворота открылись"}))
        page.evaluate("()=>poll()")
        page.wait_for_function("()=>!!document.querySelector('#nav .nav-badge')", timeout=10000)
        assert badge(page) == "1"
    finally:
        ctx.close()
    assert not problems


def test_the_master_badge_counts_due_deadlines_and_open_questions(browser, live_url, gm, rig, play):
    ok(gm.post(f"/api/gm/locmaps/{play}/deadlines", json={"date": "2075-07-15", "title": "Давно пора"}))
    ok(rig.post(f"/api/locmaps/{play}/pins", json={"text": "Куда идти?", "x": 10, "y": 10, "kind": "question"}))
    ctx, page, problems = make_page(browser, live_url)
    try:
        assert badge(page) == "2"
        wait_zone(page)
        assert "(1)" in page.inner_text('[data-act="lm-tab"][data-v="deadlines"]') and "(1)" in page.inner_text('[data-act="lm-tab"][data-v="pins"]')
    finally:
        ctx.close()
    assert not problems


# ---------------------------------------------------------------- фишка группы и прогресс

def test_the_party_token_is_placed_seen_by_everyone_and_removed(browser, live_url, gm, rig, play):
    ctx, page, problems = make_page(browser, live_url, RIG)
    try:
        wait_zone(page)
        assert page.locator("#lm-map .lm-party").count() == 0 and "Группа:" not in page.inner_text("#lm-info")
        page.click('[data-act="lm-mode"][data-v="party"]')
        assert "здесь сейчас группа" in page.inner_text(".lm-tools")
        click_drawing(page, 250, 180)                                                         # внутри «Опушки»
        page.wait_for_selector("#lm-map .lm-party span", timeout=10000)
        assert "Группа: Опушка" in page.inner_text("#lm-info") and "отметил Риг" in page.inner_text("#lm-info")
        assert zone_objects(gm, play) and detail(gm, play)["party"]["x"] in range(240, 260)
    finally:
        ctx.close()
    ctx, page, problems2 = make_page(browser, live_url)
    try:
        wait_zone(page)
        page.wait_for_selector("#lm-map .lm-party span", timeout=10000)
        assert "Группа: Опушка" in page.inner_text("#lm-info")
        page.click('[data-act="lm-party-clear"]')
        page.wait_for_function("()=>!document.querySelector('#lm-map .lm-party')", timeout=10000)
        assert detail(gm, play)["party"] is None
    finally:
        ctx.close()
    assert not problems and not problems2


def test_progress_follows_the_marks(browser, live_url, gm, rig, play):
    ctx, page, problems = make_page(browser, live_url, RIG)
    try:
        wait_zone(page)
        assert "Расчищено 0 из 2" in page.inner_text("#lm-info")                              # скрытое «Сердце» без контура не считается зоной
        open_card(page, 250, 180)
        page.click('#panel [data-act="lm-mark"][data-v="cleared"]')
        page.wait_for_function("()=>document.querySelector('#lm-info').textContent.includes('Расчищено 1 из 2')", timeout=10000)
        assert page.get_attribute("#lm-info progress", "value") == "1" and page.get_attribute("#lm-info progress", "max") == "2"
    finally:
        ctx.close()
    assert not problems


# ---------------------------------------------------------------- вопросы мастеру

def test_a_question_gets_an_answer_everyone_can_read(browser, live_url, gm, rig, gate, play):
    ctx, page, problems = make_page(browser, live_url, RIG)
    try:
        wait_zone(page)
        page.click('[data-act="lm-mode"][data-v="pin"]')
        click_drawing(page, 600, 100)
        page.wait_for_selector('.lm-form[data-lm="pin"]', timeout=5000)
        page.check('.lm-form[data-lm="pin"] input[name="kind"][value="question"]')
        page.fill('.lm-form[data-lm="pin"] [name="text"]', "Что за звук у ворот?")
        page.click('.lm-form[data-lm="pin"] button[type="submit"]')
        page.wait_for_selector("#lm-map .lm-note.lm-n-question span", timeout=10000)
        assert "? Что за звук у ворот?" in page.inner_text("#lm-map .lm-note span")
        page.click('[data-act="lm-tab"][data-v="pins"]')
        assert "Мастер пока не ответил" in page.inner_text("#lm-tab")
    finally:
        ctx.close()
    ctx, page, problems2 = make_page(browser, live_url)
    try:
        wait_zone(page)
        page.click('[data-act="lm-tab"][data-v="pins"]')
        page.click('#lm-tab [data-act="lm-answer"]')
        page.fill('.lm-form[data-lm="answer"] [name="text"]', "Цепи на ветру")
        page.click('.lm-form[data-lm="answer"] button[type="submit"]')
        page.wait_for_function("()=>document.querySelector('#lm-tab').textContent.includes('Цепи на ветру')", timeout=10000)
    finally:
        ctx.close()
    ctx, page, problems3 = make_page(browser, live_url, 102)
    try:
        wait_zone(page)
        page.click('[data-act="lm-tab"][data-v="pins"]')
        assert "Мастер: Цепи на ветру" in page.inner_text("#lm-tab") and page.locator('#lm-tab [data-act="lm-answer"]').count() == 0
        page.click('[data-act="lm-tab"][data-v="feed"]')
        assert "Ответ мастера на вопрос «Что за звук у ворот?»: Цепи на ветру" in page.inner_text("#lm-tab")
    finally:
        ctx.close()
    assert not problems and not problems2 and not problems3


# ---------------------------------------------------------------- сроки

def test_the_master_adds_applies_and_removes_a_deadline_and_players_see_only_shared_ones(browser, live_url, gm, rig, play):
    ctx, page, problems = make_page(browser, live_url)
    try:
        wait_zone(page)
        page.click('[data-act="lm-tab"][data-v="deadlines"]')
        page.click('#lm-tab [data-act="lm-dl-new"]')
        page.fill('.lm-form[data-lm="deadline"] [name="title"]', "Цветение: сердце +2")
        page.fill('.lm-form[data-lm="deadline"] [name="date"]', "2075-08-05")
        page.select_option('.lm-form[data-lm="deadline"] [name="obj"]', label="Сердце Сердце")
        page.fill('.lm-form[data-lm="deadline"] [name="delta"]', "2")
        page.fill('.lm-form[data-lm="deadline"] [name="note"]', f"{SECRET}-срок")
        page.click('.lm-form[data-lm="deadline"] button[type="submit"]')
        page.wait_for_selector("#lm-tab .lm-dl", timeout=10000)
        text = page.inner_text("#lm-tab")
        assert "Цветение: сердце +2" in text and "через 4 дня" in text and "скрыт от игроков" in text and "счётчик +2 у зоны" in text
        ok(gm.post(f"/api/gm/locmaps/{play}/deadlines", json={"date": "2075-08-06", "title": "Общий срок", "vis": "стол"}))
        page.evaluate("()=>poll()")
        page.wait_for_function("()=>document.querySelector('#lm-tab').textContent.includes('Общий срок')", timeout=10000)
        page.click('#lm-tab .lm-dl:has-text("Цветение") [data-act="lm-dl-apply"]')
        page.wait_for_function("()=>document.querySelector('#lm-tab .lm-dl.lm-done')", timeout=10000)
        assert counts(gm, play)["Сердце"] == 7
        assert "выполнен" in page.inner_text("#lm-tab .lm-dl.lm-done")
        page.click('#lm-tab .lm-dl:has-text("Общий срок") [data-act="lm-dl-skip"]')
        page.wait_for_function("()=>document.querySelectorAll('#lm-tab .lm-dl.lm-done').length===2", timeout=10000)
        assert counts(gm, play)["Сердце"] == 7
        no_leaks(page)
    finally:
        ctx.close()
    ctx, page, problems2 = make_page(browser, live_url, RIG)
    try:
        wait_zone(page)
        page.click('[data-act="lm-tab"][data-v="deadlines"]')
        text = page.inner_text("#lm-tab")
        assert "Общий срок" in text and "Цветение" not in text and SECRET not in text
        assert page.locator('#lm-tab [data-act^="lm-dl"]').count() == 0 and page.locator('[data-act="lm-tab"][data-v="log"]').count() == 0
    finally:
        ctx.close()
    assert not problems and not problems2


def test_a_deadline_that_has_come_is_highlighted_and_can_be_edited_and_deleted(browser, live_url, gm, play):
    d = ok(gm.post(f"/api/gm/locmaps/{play}/deadlines", json={"date": "2075-07-10", "title": "Уже наступил"}))["deadline"]
    ctx, page, problems = make_page(browser, live_url)
    try:
        wait_zone(page)
        page.click('[data-act="lm-tab"][data-v="deadlines"]')
        assert page.locator("#lm-tab .lm-dl.lm-late").count() == 1
        page.click('#lm-tab [data-act="lm-dl-edit"]')
        page.fill('.lm-form[data-lm="deadline"] [name="title"]', "Переименован")
        page.click('.lm-form[data-lm="deadline"] button[type="submit"]')
        page.wait_for_function("()=>document.querySelector('#lm-tab').textContent.includes('Переименован')", timeout=10000)
        page.click('#lm-tab [data-act="lm-dl-del"]')
        page.click('#lm-tab [data-act="lm-dl-del"]')
        page.wait_for_function("()=>!document.querySelector('#lm-tab .lm-dl')", timeout=10000)
        assert detail(gm, play)["deadlines"] == [] and d["id"]
    finally:
        ctx.close()
    assert not problems


# ---------------------------------------------------------------- счётчик мастера

def test_the_master_sees_and_changes_counters_and_players_never_do(browser, live_url, gm, rig, play):
    ctx, page, problems = make_page(browser, live_url)
    try:
        wait_zone(page)
        assert page.locator("#lm-map .lm-cnt").count() == 3
        open_card(page, 250, 180)
        assert "Фон:" in page.inner_text("#panel .lm-counter") and "3" in page.inner_text("#panel .lm-cval") and "при расчистке: этой −2" in page.inner_text("#panel .lm-counter")
        page.click('#panel [data-act="lm-count"][data-d="1"]')
        page.wait_for_function("()=>document.querySelector('#panel .lm-cval').textContent==='4'", timeout=10000)
        assert counts(gm, play)["О1"] == 4
        page.click('#panel [data-act="close"]')
        page.click('.lm-bump [data-act="lm-bump"][data-v="-1"]')
        page.wait_for_function("()=>[...document.querySelectorAll('#lm-map .lm-cnt')].map(n=>n.textContent).sort().join()==='3,3,4'", timeout=10000)
        assert counts(gm, play) == {"О1": 3, "Г1": 3, "Сердце": 4}
    finally:
        ctx.close()
    ctx, page, problems2 = make_page(browser, live_url, RIG)
    try:
        wait_zone(page)
        assert page.locator("#lm-map .lm-cnt, .lm-bump, .lm-counter").count() == 0
        open_card(page, 250, 180)
        assert page.locator("#panel .lm-counter").count() == 0
        data = page.evaluate("()=>JSON.stringify({s:S.locmaps,d:LM.data})")
        assert '"count"' not in data and '"fx"' not in data and '"counter"' not in data and SECRET not in data
    finally:
        ctx.close()
    assert not problems and not problems2


def test_the_object_form_saves_counter_and_rules_and_explains_a_mistake(browser, live_url, gm, play):
    ctx, page, problems = make_page(browser, live_url)
    try:
        wait_zone(page)
        open_card(page, 250, 180)
        page.click('#panel [data-act="lm-obj-edit"]')
        page.fill('.lm-form[data-lm="obj"] [name="fx"]', "этой очень много")
        page.click('.lm-form[data-lm="obj"] button[type="submit"]')
        page.wait_for_function("()=>document.querySelector('#form-err').textContent.includes('Не понял')", timeout=5000)
        page.fill('.lm-form[data-lm="obj"] [name="fx"]', "этой −3; Сердце −1")
        page.fill('.lm-form[data-lm="obj"] [name="count"]', "8")
        page.click('.lm-form[data-lm="obj"] button[type="submit"]')
        page.wait_for_function("()=>document.getElementById('overlay').hidden", timeout=10000)
        o = zone_objects(gm, play)["О1"]
        assert o["count"] == 8 and o["fx"] == [{"to": "self", "delta": -3}, {"to": "Сердце", "delta": -1}]
    finally:
        ctx.close()
    assert not problems


# ---------------------------------------------------------------- журнал и отмена

def test_the_master_undoes_a_player_mistake_from_the_log(browser, live_url, gm, rig, play):
    ok(rig.post(f"/api/locmaps/{play}/objects/{zone_objects(gm, play)['Г1']['id']}/mark", json={"status": "cleared", "text": "Чисто"}))
    assert counts(gm, play) == {"О1": 3, "Г1": 2, "Сердце": 4}
    ctx, page, problems = make_page(browser, live_url)
    try:
        wait_zone(page)
        page.click('[data-act="lm-tab"][data-v="log"]')
        page.wait_for_selector('#lm-tab [data-act="lm-undo"]', timeout=5000)
        assert "Риг: «Глубина», расчищено. Чисто" in page.inner_text("#lm-tab")
        page.click('#lm-tab [data-act="lm-undo"]')
        page.wait_for_function("()=>document.querySelector('#lm-tab').textContent.includes('(отменено)')", timeout=10000)
        assert zone_objects(gm, play)["Г1"]["status"] == "" and counts(gm, play) == {"О1": 3, "Г1": 4, "Сердце": 5}
    finally:
        ctx.close()
    assert not problems


# ---------------------------------------------------------------- связи

def test_a_linked_dossier_card_opens_from_the_zone_card(browser, live_url, gm, rig, play):
    card = ok(gm.post("/api/gm/items/dossier", json={"name": "Тедди Мур", "type": "person", "role": "музыкант", "vis": "стол"}))["state"]["dossier"][-1]["id"]
    hidden = ok(gm.post("/api/gm/items/dossier", json={"name": "Секретный контакт", "type": "person", "vis": "мастер"}))["state"]["dossier"][-1]["id"]
    ctx, page, problems = make_page(browser, live_url)
    try:
        wait_zone(page)
        open_card(page, 250, 180)
        page.click('#panel [data-act="lm-links"]')
        page.wait_for_selector('#panel [data-act="lm-link"]', timeout=5000)
        page.click(f'#panel [data-act="lm-link"][data-ref="{card}"]')
        page.wait_for_function(f"()=>document.querySelector('#panel [data-ref=\"{card}\"]').getAttribute('aria-pressed')==='true'", timeout=10000)
        page.click(f'#panel [data-act="lm-link"][data-ref="{hidden}"]')
        page.wait_for_function(f"()=>document.querySelector('#panel [data-ref=\"{hidden}\"]').getAttribute('aria-pressed')==='true'", timeout=10000)
    finally:
        ctx.close()
    ctx, page, problems2 = make_page(browser, live_url, RIG)
    try:
        wait_zone(page)
        open_card(page, 250, 180)
        assert "Связано" in page.inner_text("#panel") and "Тедди Мур" in page.inner_text("#panel") and "Секретный контакт" not in page.inner_text("#panel")
        page.click('#panel [data-open^="n:"]')
        page.wait_for_selector("#panel h2:has-text('Тедди Мур')", timeout=5000)
    finally:
        ctx.close()
    assert not problems and not problems2


def test_entries_for_the_linked_place_are_listed_under_the_map(browser, live_url, gm, rig, play):
    place = ok(gm.post("/api/gm/items/places", json={"name": "Роща у реки", "type": "other", "x": 900, "y": 1200, "vis": "стол"}))["state"]["places"][-1]["id"]
    ok(gm.post("/api/gm/items/locmaps", json={"id": play, "name": "Роща", "vis": "стол", "counter": "Фон", "place": place}))
    ok(gm.post("/api/entries", json={"char": "gm", "type": "meet", "title": "Встреча в Роще", "who": ["rig"], "from": "2075-08-02", "to": "2075-08-02", "tod": "вечер",
                                     "where": "Роща", "place": place, "vis": "стол", "goal": "обсудить"}))
    ctx, page, problems = make_page(browser, live_url, RIG)
    try:
        wait_zone(page)
        assert "Записи календаря по этому месту (1)" in page.inner_text(".lm-entries summary")
        page.click(".lm-entries summary")
        assert "Встреча в Роще" in page.inner_text(".lm-entries")
    finally:
        ctx.close()
    assert not problems


# ---------------------------------------------------------------- картинка карты

def test_the_map_picture_is_a_real_png_without_hidden_things(browser, live_url, gm, rig, play):
    ok(rig.post(f"/api/locmaps/{play}/objects/{zone_objects(gm, play)['О1']['id']}/mark", json={"status": "cleared"}))
    ctx, page, problems = make_page(browser, live_url)
    try:
        wait_zone(page)
        page.click('[data-act="lm-export"]')
        page.wait_for_selector("#panel img.lm-export", timeout=15000)
        page.wait_for_function("()=>document.querySelector('#panel img.lm-export').naturalWidth>0", timeout=10000)
        assert "как карту видят игроки" in page.inner_text("#panel").lower() or "Как карту видят игроки" in page.inner_text("#panel")
        size = page.evaluate("()=>{const i=document.querySelector('#panel img.lm-export');return [i.naturalWidth,i.naturalHeight,i.src.startsWith('blob:')]}")
        assert size == [800, 664, True]                                                       # рисунок 800×600 и подпись внизу; браузер прочитал картинку как PNG
        assert page.get_attribute("#panel a[download]", "download").endswith(".png")
        assert page.evaluate("()=>window.__csp||[]") == []
    finally:
        ctx.close()
    assert not problems


# ---------------------------------------------------------------- предпросмотр

def test_preview_as_a_player_hides_counters_log_and_secret_deadlines(browser, live_url, gm, rig, play):
    ok(gm.post(f"/api/gm/locmaps/{play}/deadlines", json={"date": "2075-08-05", "title": "Тайный срок", "note": f"{SECRET}-срок"}))
    ok(gm.post(f"/api/gm/locmaps/{play}/deadlines", json={"date": "2075-08-06", "title": "Открытый срок", "vis": "стол"}))
    ctx, page, problems = make_page(browser, live_url)
    try:
        wait_zone(page)
        page.select_option("#who-select", "rig")
        page.wait_for_function("()=>LM.as==='rig'", timeout=10000)
        page.wait_for_function("()=>document.querySelectorAll('#lm-map .lm-zone').length===2", timeout=10000)
        assert page.locator("#lm-map .lm-cnt, .lm-bump, .lm-counter").count() == 0
        assert page.locator('[data-act="lm-tab"][data-v="log"]').count() == 0 and page.locator('[data-act="lm-mode"][data-v="party"]').count() == 0
        page.click('[data-act="lm-tab"][data-v="deadlines"]')
        text = page.inner_text("#lm-tab")
        assert "Открытый срок" in text and "Тайный срок" not in text and SECRET not in text
        assert page.locator("#lm-map .lm-cnt").count() == 0
    finally:
        ctx.close()
    assert not problems


# ---------------------------------------------------------------- загрузка списком

def test_import_brings_counter_rules_and_deadlines(browser, live_url, gm, play):
    import json
    data = {"counter": "Тревога", "objects": [{"key": "Н1", "name": "Новая", "kind": "area", "count": 6, "fx": [{"to": "self", "delta": -2}], "shape": {"player": [[10, 10], [90, 10], [50, 80]]}}],
            "deadlines": [{"date": "2075-08-30", "title": "Срок из чата", "obj": "Н1", "delta": 1}, {"date": "2075-08-31", "title": "Метки нет", "obj": "Н9"}]}
    ctx, page, problems = make_page(browser, live_url)
    try:
        page.click('[data-act="lm-import"]')
        page.fill('.lm-form[data-lm="import"] [name="json"]', json.dumps(data, ensure_ascii=False))
        page.click('.lm-form[data-lm="import"] button[type="submit"]')
        page.wait_for_selector("#panel >> text=Метки загружены", timeout=10000)
        text = page.inner_text("#panel")
        assert "Сроки: добавлено 1" in text and "Не прошло проверку: 1" in text and "Метки с подписью «Н9» на карте нет" in text
        assert zone_objects(gm, play)["Н1"]["count"] == 6 and detail(gm, play)["counter"] == "Тревога"
    finally:
        ctx.close()
    assert not problems


# ---------------------------------------------------------------- телефон

@pytest.mark.parametrize("who", [GM, RIG])
def test_the_new_parts_do_not_overflow_on_a_phone(browser, live_url, gm, rig, play, who):
    ok(gm.post(f"/api/gm/locmaps/{play}/deadlines", json={"date": "2075-08-06", "title": "Очень длинное название срока " + "слово" * 14, "vis": "стол", "note": "заметка " * 40}))
    ok(rig.post(f"/api/locmaps/{play}/party", json={"x": 250, "y": 180}))
    ok(rig.post(f"/api/locmaps/{play}/pins", json={"text": "Вопрос " + "слово" * 15, "x": 600, "y": 100, "kind": "question"}))
    for width in (360, 390):
        ctx, page, problems = make_page(browser, live_url, who, width)
        try:
            wait_zone(page)
            for tab in ("marks", "feed", "pins", "deadlines") + (("log",) if who == GM else ()):
                page.click(f'[data-act="lm-tab"][data-v="{tab}"]')
                over = page.evaluate("()=>({page:document.documentElement.scrollWidth-document.documentElement.clientWidth,"
                                     "box:[...document.querySelectorAll('.lm *:not(.leaflet-container *)')].filter(e=>e.getBoundingClientRect().right>document.documentElement.clientWidth+1).map(e=>e.className||e.tagName)})")
                assert over["page"] <= 0 and over["box"] == [], (who, width, tab, over)
            open_card(page, 250, 180)
            over = page.evaluate("()=>[...document.querySelectorAll('#panel *')].filter(e=>e.getBoundingClientRect().right>document.documentElement.clientWidth+1).map(e=>e.className||e.tagName)")
            assert over == [], (who, width, over)
        finally:
            ctx.close()
        assert not problems
