"""Корзина и история в интерфейсе мастера: список, восстановление, откат, история отдельной карточки, вредные названия."""
import pytest

from helpers import ok
from ui_support import open_page

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]

PAYLOAD = '"><img src=x onerror=__xss=1 id=hist>'      # не совпадает со строками других тестов: корзина у них общая


@pytest.fixture
def gm_page(browser, live_url, gm):
    problems = []
    ctx, page = open_page(browser, live_url, 1, problems)
    yield page, problems
    ctx.close()
    assert not problems, problems


def refresh_state(page):
    """Данные созданы через API уже после загрузки страницы: подтянуть свежее состояние."""
    page.evaluate("async()=>{const r=await fetch('/api/state',{credentials:'same-origin'});applyState(await r.json());}")


def open_gm_panel(page):
    refresh_state(page)
    page.evaluate("()=>{UI.extrasVer=-1;UI.section='gm';render();}")
    page.wait_for_function("()=>document.querySelector('#trash-list')&&!document.querySelector('#trash-list').textContent.includes('Загружаю')", timeout=10000)
    page.wait_for_function("()=>document.querySelector('#hist-list')&&!document.querySelector('#hist-list').textContent.includes('Загружаю')", timeout=10000)


def check_clean(page):
    n = page.evaluate("()=>({xss:window.__xss||0,img:document.querySelectorAll('img[src=\"x\"]').length,csp:(window.__csp||[]).length})")
    assert n == {"xss": 0, "img": 0, "csp": 0}, n


def test_trash_lists_and_restores_a_deleted_card(gm_page, gm):
    page, _ = gm_page
    data = ok(gm.post("/api/gm/items/dossier", json={"name": PAYLOAD, "vis": "стол", "role": "роль"}))
    cid = next(c["id"] for c in data["state"]["dossier"] if c["name"] == PAYLOAD)
    ok(gm.post(f"/api/gm/items/dossier/{cid}/delete"))
    try:
        open_gm_panel(page)
        row = page.locator("#trash-list .hist-row", has_text="Карточка досье")
        assert row.count() >= 1
        assert PAYLOAD in row.first.inner_text()                            # название видно буквами
        assert "Корзина (" in page.inner_text("#gm-trash h2")
        check_clean(page)
        page.locator('#trash-list [data-act="trash-restore"]').first.click()
        page.wait_for_function("id=>S.dossier.some(c=>c.id===id)", arg=cid, timeout=10000)
        assert page.evaluate("id=>S.dossier.find(c=>c.id===id).role", cid) == "роль"
        page.wait_for_function("id=>!document.querySelector('#trash-list').textContent.includes(id)", arg=PAYLOAD, timeout=10000)
        check_clean(page)
    finally:
        gm.post(f"/api/gm/items/dossier/{cid}/delete")
        for t in ok(gm.get("/api/gm/trash"))["items"]:
            if t["title"] == PAYLOAD:
                gm.post(f"/api/gm/trash/{t['id']}/purge")


def test_history_shows_changes_and_reverts(gm_page, gm):
    page, _ = gm_page
    data = ok(gm.post("/api/gm/items/clocks", json={"title": "Часы для истории", "note": "было", "when": "2075-10-01"}))
    cid = next(c["id"] for c in data["state"]["clocks"] if c["title"] == "Часы для истории")
    ok(gm.post("/api/gm/items/clocks", json={"id": cid, "title": "Часы для истории", "note": PAYLOAD, "when": "2075-10-01"}))
    try:
        open_gm_panel(page)
        page.fill("#hist-q", "Часы для истории")
        page.wait_for_function("()=>document.querySelectorAll('#hist-list .hist-row').length===2", timeout=10000)
        first = page.locator("#hist-list .hist-row").first
        assert "изменил(а)" in first.inner_text() and "скрытый таймер" in first.inner_text()
        first.locator("summary").click()
        table = first.locator("table").inner_text()
        assert "Описание" in table and "было" in table and PAYLOAD in table      # было/стало, вредный текст буквами
        check_clean(page)
        first.locator('[data-act="hist-revert"]').click()
        page.wait_for_function("id=>(S.clocks.find(c=>c.id===id)||{}).note==='было'", arg=cid, timeout=10000)
        page.wait_for_function("()=>document.querySelector('#hist-list .hist-row').textContent.includes('откатил(а)')", timeout=10000)
        check_clean(page)
    finally:
        gm.post(f"/api/gm/items/clocks/{cid}/delete")
        for t in ok(gm.get("/api/gm/trash"))["items"]:
            if t["title"] == "Часы для истории":
                gm.post(f"/api/gm/trash/{t['id']}/purge")


def test_item_history_opens_from_a_dossier_card(gm_page, gm):
    page, _ = gm_page
    data = ok(gm.post("/api/gm/items/dossier", json={"name": "История карточки", "vis": "стол", "role": "один"}))
    cid = next(c["id"] for c in data["state"]["dossier"] if c["name"] == "История карточки")
    ok(gm.post("/api/gm/items/dossier", json={"id": cid, "name": "История карточки", "vis": "стол", "role": "два"}))
    try:
        refresh_state(page)
        page.evaluate("id=>{UI.section='dossier';render();openDossier(id)}", cid)
        page.click('#panel [data-act="item-history"]')
        page.wait_for_function("()=>document.querySelector('#panel').textContent.includes('История')&&document.querySelectorAll('#panel .hist-row').length>=2", timeout=10000)
        text = page.inner_text("#panel")
        assert "изменил(а)" in text and "добавил(а)" in text
        check_clean(page)
    finally:
        gm.post(f"/api/gm/items/dossier/{cid}/delete")
        for t in ok(gm.get("/api/gm/trash"))["items"]:
            if t["title"] == "История карточки":
                gm.post(f"/api/gm/trash/{t['id']}/purge")
