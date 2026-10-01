"""Лист персонажа и броски кубов в браузере: что видит игрок и мастер, формы мастера, экранирование, кубики в обсуждении."""
import pytest

from helpers import create, ok, remove
from ui_support import open_page

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]

EVIL = "<img src=x onerror=__xss=1 id=sheet>"
TITLES = {f"Фракция {k}" for k in ("открытая", "для Рига", "скрытая")}


def put(gm, section, **body):
    return ok(gm.post(f"/api/gm/items/{section}", json=body))["state"][section][-1]


def wipe(gm):
    state = ok(gm.get("/api/state"))
    for kind in ("money", "standing", "contacts", "factions"):
        for x in state[kind]:
            gm.post(f"/api/gm/items/{kind}/{x['id']}/delete")
    for t in ok(gm.get("/api/gm/trash"))["items"]:
        if t["kind"] in ("money", "standing", "contacts", "factions"):
            gm.post(f"/api/gm/trash/{t['id']}/purge")


@pytest.fixture
def world(gm, sandbox):
    wipe(gm)
    f = {}
    f["open"] = put(gm, "factions", name="Фракция открытая", kind="corp", vis="стол", note=f"Публично {EVIL}", gm_note="СЕКРЕТ-фракция")["id"]
    f["rig"] = put(gm, "factions", name="Фракция для Рига", kind="gang", vis="знают", known=["rig"])["id"]
    f["hidden"] = put(gm, "factions", name="Фракция скрытая", kind="corp", vis="мастер")["id"]
    put(gm, "standing", char="rig", faction=f["open"], value=2, note="Помог с эвакуацией", gm_note="СЕКРЕТ-репутация")
    put(gm, "standing", char="rig", faction=f["rig"], value=-3)
    put(gm, "standing", char="rig", faction=f["hidden"], value=5)
    put(gm, "money", char="rig", delta=1500, note="Награда", gm_note="СЕКРЕТ-деньги")
    put(gm, "money", char="rig", delta=-200, note=f"Ремонт {EVIL}")
    put(gm, "money", char="gate", delta=999, note="Чужие деньги")
    put(gm, "contacts", char="rig", name="Фиксер Ли", card="n2", connection=4, loyalty=2, services="Достаёт железо", note=f"Заметка {EVIL}", gm_note="СЕКРЕТ-контакт")
    put(gm, "contacts", char="rig", name="Открытый знакомый", card="n1", connection=2, loyalty=3)
    yield f
    wipe(gm)


def make_page(browser, live_url, tg_id):
    problems = []
    ctx, page = open_page(browser, live_url, tg_id, problems)
    page.evaluate("async()=>{const r=await fetch('/api/state',{credentials:'same-origin'});applyState(await r.json());}")
    return ctx, page, problems


@pytest.fixture
def player(browser, live_url, world):
    ctx, page, problems = make_page(browser, live_url, 103)           # Риг
    yield page
    ctx.close()
    assert not problems, problems


@pytest.fixture
def master(browser, live_url, world):
    ctx, page, problems = make_page(browser, live_url, 1)
    yield page
    ctx.close()
    assert not problems, problems


def open_sheet(page):
    page.evaluate("()=>{UI.section='sheet';render()}")
    page.wait_for_selector(".sheet", timeout=10000)


def clean(page):
    n = page.evaluate("()=>({xss:window.__xss||0,img:document.querySelectorAll('img[src=\"x\"]').length,csp:(window.__csp||[]).length})")
    assert n == {"xss": 0, "img": 0, "csp": 0}, n


def text(page):
    return page.inner_text(".sheet")


# ---------------------------------------------------------------- игрок

def test_player_sees_his_sheet_and_nothing_else(player):
    assert player.locator('#nav button[data-nav="sheet"]').count() == 1
    open_sheet(player)
    t = text(player)
    assert "Риг" in t and "1 300 ¥" in t.replace(" ", " ")                       # 1500 − 200
    assert "Награда" in t and "Ремонт" in t and EVIL in t                                            # вредная строка выведена буквами
    assert "Фракция открытая" in t and "Фракция для Рига" in t and "Фракция скрытая" not in t
    assert "Помог с эвакуацией" in t and "Достаёт железо" in t
    assert "СЕКРЕТ" not in t and "Чужие деньги" not in t and "999" not in t
    assert player.locator('.sheet [data-act^="sr-new"],.sheet [data-act="sr-edit"],.sheet [data-act="del-item"]').count() == 0
    assert player.locator(".sh-char").count() == 1
    clean(player)


def test_contact_links_only_to_visible_cards(player):
    open_sheet(player)
    names = {b.inner_text(): b for b in player.locator(".sheet .ct-top .dlink").all()}
    assert set(names) == {"Открытый знакомый"}                                                         # карточка n2 игроку закрыта: Ли без ссылки
    assert "Фиксер Ли" in text(player)
    names["Открытый знакомый"].click()
    player.wait_for_function("()=>document.querySelector('#panel h2')&&document.querySelector('#panel h2').textContent.includes('Открытая карточка')", timeout=10000)


def test_reputation_shows_value_label_and_bar(player):
    open_sheet(player)
    rows = player.locator(".st-row")
    assert rows.count() == 2
    first = rows.filter(has_text="Фракция открытая")
    assert "+2" in first.inner_text() and "Доверие" in first.inner_text() and first.locator(".st-bar").get_attribute("aria-label").startswith("Репутация +2")
    assert "−3" in rows.filter(has_text="Фракция для Рига").inner_text()


def test_player_without_a_character_has_no_sheet_tab(browser, live_url, world):
    ctx, page, problems = make_page(browser, live_url, 106)
    try:
        assert page.locator('#nav button[data-nav="sheet"]').count() == 0
    finally:
        ctx.close()
    assert not problems


# ---------------------------------------------------------------- мастер

def test_master_sees_everything_with_notes_and_summary(master):
    open_sheet(master)
    assert master.locator(".sh-sum tbody tr").count() >= 6
    master.locator('.sheet .seg [data-act="sr-char"]', has_text="Риг").click()
    t = text(master)
    assert "СЕКРЕТ-деньги" in t and "СЕКРЕТ-репутация" in t and "СЕКРЕТ-контакт" in t and "Фракция скрытая" in t
    assert master.locator('.sheet [data-act="sr-new"]').count() >= 4                                    # деньги, репутация, контакт, фракция
    clean(master)


def test_master_adds_an_expense_through_the_form(master, world):
    open_sheet(master)
    master.locator('.sheet .seg [data-act="sr-char"]', has_text="Риг").click()
    master.locator('.sheet [data-act="sr-new"][data-kind="money"]').click()
    form = master.locator("#sr-form")
    form.locator('input[name="sign"][value="-1"]').check()
    form.locator('button[type="submit"]').click()
    master.wait_for_function("()=>document.getElementById('form-err').textContent.length>0", timeout=10000)
    assert "сумму" in master.inner_text("#form-err")                                                      # без суммы форма не уходит
    form.locator('input[name="amount"]').fill("300")
    form.locator('input[name="note"]').fill("Кофе")
    form.locator('button[type="submit"]').click()
    master.wait_for_function("()=>(S.money||[]).some(m=>m.note==='Кофе'&&m.delta===-300&&m.char==='rig')", timeout=10000)
    master.wait_for_function("()=>document.getElementById('overlay').hidden", timeout=10000)
    assert "1 000 ¥" in text(master) and "−300 ¥" in text(master)


def test_master_records_reputation_and_a_contact(master, world):
    open_sheet(master)
    master.locator('.sheet .seg [data-act="sr-char"]', has_text="Гейт").click()
    master.locator('.sheet [data-act="sr-new"][data-kind="standing"]').click()
    form = master.locator("#sr-form")
    form.locator('select[name="faction"]').select_option(label="Фракция открытая")
    form.locator('select[name="value"]').select_option("4")
    form.locator('button[type="submit"]').click()
    master.wait_for_function("()=>(S.standing||[]).some(s=>s.char==='gate'&&s.value===4)", timeout=10000)
    master.locator('.sheet [data-act="sr-new"][data-kind="contacts"]').click()
    form = master.locator("#sr-form")
    form.locator('select[name="card"]').select_option("n1")
    form.locator('input[name="connection"]').fill("7")
    form.locator('input[name="loyalty"]').fill("5")
    form.locator('button[type="submit"]').click()
    master.wait_for_function("()=>(S.contacts||[]).some(c=>c.char==='gate'&&c.card==='n1'&&c.name==='Открытая карточка'&&c.connection===7)", timeout=10000)
    t = text(master)
    assert "Связи 7 · Лояльность 5" in t and "+4" in t and "Друг" in t


def test_server_errors_are_shown_in_the_form(master, world):
    open_sheet(master)
    master.locator('.sheet .seg [data-act="sr-char"]', has_text="Риг").click()
    master.locator('.sheet [data-act="sr-new"][data-kind="standing"]').click()
    form = master.locator("#sr-form")
    form.locator('select[name="faction"]').select_option(label="Фракция открытая")                       # у Рига она уже записана
    form.locator('button[type="submit"]').click()
    master.wait_for_function("()=>document.getElementById('form-err').textContent.length>0", timeout=10000)
    assert "уже записана" in master.inner_text("#form-err")
    assert master.locator("#sr-form").count() == 1                                                        # форма осталась открытой


def test_master_edits_and_deletes_a_ledger_row_with_confirmation(master, world, gm):
    open_sheet(master)
    master.locator('.sheet .seg [data-act="sr-char"]', has_text="Риг").click()
    row = master.locator(".ledger li", has_text="Награда")
    row.locator('[data-act="sr-edit"]').click()
    form = master.locator("#sr-form")
    assert form.locator('input[name="amount"]').input_value() == "1500" and form.locator('input[name="sign"][value="1"]').is_checked()
    form.locator('input[name="amount"]').fill("1800")
    form.locator('button[type="submit"]').click()
    master.wait_for_function("()=>(S.money||[]).some(m=>m.note==='Награда'&&m.delta===1800)", timeout=10000)
    row = master.locator(".ledger li", has_text="Награда")
    row.locator('[data-act="del-item"]').click()
    assert "ещё раз" in row.locator('[data-act="del-item"]').inner_text()
    row.locator('[data-act="del-item"]').click()
    master.wait_for_function("()=>!(S.money||[]).some(m=>m.note==='Награда')", timeout=10000)
    assert any(t["kind"] == "money" for t in ok(gm.get("/api/gm/trash"))["items"])                     # ушло в корзину, а не навсегда


def test_item_history_opens_for_a_sheet_row(master, world):
    open_sheet(master)
    master.locator('.sheet .seg [data-act="sr-char"]', has_text="Риг").click()
    master.locator(".ledger li", has_text="Награда").locator('[data-act="item-history"]').click()
    master.wait_for_selector("#panel .hist-row", timeout=10000)
    assert "запись о деньгах" in master.inner_text("#panel") and "добавил" in master.inner_text("#panel")


def test_preview_as_a_player_hides_the_masters_view(master, world):
    master.evaluate("()=>{V='rig';UI.section='sheet';render()}")
    master.wait_for_selector(".sheet", timeout=10000)
    t = text(master)
    assert "СЕКРЕТ" not in t and "Фракция скрытая" not in t and "Чужие деньги" not in t and "1 300 ¥" in t
    assert master.locator('.sheet [data-act="sr-new"]').count() == 0
    clean(master)


def test_hostile_text_in_every_field_is_inert(master, world):
    open_sheet(master)
    master.locator('.sheet .seg [data-act="sr-char"]', has_text="Риг").click()
    assert master.locator(".sheet img").count() == 0
    clean(master)


# ---------------------------------------------------------------- кубики в обсуждении

@pytest.fixture
def thread(gate, gm):
    e = create(gate, char="gate", title="Дело для кубов", who=["rig"])
    yield e
    remove(gm, e["id"])
    for t in ok(gm.get("/api/gm/trash"))["items"]:
        if t["title"] == "Дело для кубов":
            gm.post(f"/api/gm/trash/{t['id']}/purge")


def open_thread(page, eid):
    page.evaluate("async()=>{const r=await fetch('/api/state',{credentials:'same-origin'});applyState(await r.json());}")
    page.evaluate("id=>{UI.section='cal';render();openDetail('e:'+id)}", eid)
    page.wait_for_selector("#panel .chat", timeout=10000)


def test_player_rolls_dice_in_the_discussion(browser, live_url, thread):
    ctx, page, problems = make_page(browser, live_url, 103)
    try:
        open_thread(page, thread["id"])
        page.locator("#panel .roll-box summary").click()
        form = page.locator("#roll-form")
        form.locator('input[name="dice"]').fill("0")
        form.locator('button[type="submit"]').click()
        assert "от 1 до 40" in page.inner_text("#roll-err")                                                # неверное число не уходит на сервер
        form.locator('input[name="dice"]').fill("5")
        form.locator('input[name="limit"]').fill("3")
        form.locator('input[name="threshold"]').fill("1")
        form.locator('input[name="label"]').fill(EVIL)
        form.locator('button[type="submit"]').click()
        page.wait_for_selector("#panel .chat .roll", timeout=10000)
        roll = page.locator("#panel .chat .roll").last
        assert roll.locator(".die").count() == 5 and "Бросок 5d6" in roll.inner_text() and EVIL in roll.inner_text()
        hits = roll.locator(".die.hit").count()
        assert f"Успехов: {hits}" in roll.inner_text() and "порог 1" in roll.inner_text()
        assert page.locator("#panel .roll-box").get_attribute("open") is not None                           # форма осталась раскрытой для следующего броска
        clean(page)
        form = page.locator("#roll-form")
        form.locator('input[name="dice"]').fill("4")
        form.locator('input[name="edge"]').check()
        form.locator('button[type="submit"]').click()
        page.wait_for_function("()=>document.querySelectorAll('#panel .chat .roll').length===2", timeout=10000)
        assert "с риском" in page.locator("#panel .chat .roll").last.inner_text()
        clean(page)
    finally:
        ctx.close()
    assert not problems


def test_everyone_in_the_thread_sees_the_same_dice(browser, live_url, thread, rig):
    ok(rig.post(f"/api/entries/{thread['id']}/roll", json={"char": "rig", "dice": 6, "label": "Скрытность"}))
    seen = []
    for tg in (102, 1):                                                                                    # автор записи и мастер
        ctx, page, problems = make_page(browser, live_url, tg)
        try:
            open_thread(page, thread["id"])
            roll = page.locator("#panel .chat .roll").last
            seen.append((roll.inner_text(), [d.inner_text() for d in roll.locator(".die").all()]))
        finally:
            ctx.close()
        assert not problems
    assert seen[0] == seen[1] and len(seen[0][1]) >= 6


def test_a_non_participant_has_no_roll_form(browser, live_url, thread):
    ctx, page, problems = make_page(browser, live_url, 104)                                                # Хаганэ видит запись, но не участник
    try:
        open_thread(page, thread["id"])
        assert page.locator("#roll-form").count() == 0 and page.locator("#chat-form").count() == 0
    finally:
        ctx.close()
    assert not problems
