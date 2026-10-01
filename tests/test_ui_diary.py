"""«Мой дневник» в браузере: кнопка, окно, скачивание Markdown и PDF, ошибки."""
import pytest
from pypdf import PdfReader

from helpers import create, ok, remove
from ui_support import open_page

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]


@pytest.fixture
def thread(gate, gm, sandbox):
    e = create(gate, char="gate", title="Дело для дневника", who=["rig"], goal="Цель [[Открытая карточка]]")
    ok(gm.post("/api/gm/items/money", json={"char": "rig", "delta": 4200, "note": "Для дневника", "gm_note": "СЕКРЕТ-деньги"}))
    yield e
    remove(gm, e["id"])
    state = ok(gm.get("/api/state"))
    for m in state["money"]:
        gm.post(f"/api/gm/items/money/{m['id']}/delete")
    for t in ok(gm.get("/api/gm/trash"))["items"]:
        if t["kind"] == "money" or t["title"] == "Дело для дневника":
            gm.post(f"/api/gm/trash/{t['id']}/purge")


def make_page(browser, live_url, tg_id):
    problems = []
    ctx, page = open_page(browser, live_url, tg_id, problems)
    return ctx, page, problems


def test_markdown_download(browser, live_url, thread, tmp_path):
    ctx, page, problems = make_page(browser, live_url, 103)
    try:
        page.click('#who-box [data-act="open-diary"]')
        page.wait_for_selector("#diary-form", timeout=10000)
        assert page.is_checked('input[name="part"][value="sheet"]') and not page.is_checked('input[name="part"][value="chat"]')
        with page.expect_download(timeout=15000) as dl:
            page.click('#diary-form button[type="submit"]')
        d = dl.value
        assert d.suggested_filename.startswith("Дневник-Риг-2075-") and d.suggested_filename.endswith(".md")
        path = tmp_path / "d.md"
        d.save_as(path)
        text = path.read_text(encoding="utf-8")
        assert "# Дневник: Риг" in text and "Дело для дневника" in text and "4\u00a0200\u00a0¥" in text
        assert "СЕКРЕТ" not in text
        page.wait_for_function("()=>document.getElementById('overlay').hidden", timeout=10000)
        assert page.evaluate("()=>(window.__csp||[]).length") == 0
    finally:
        ctx.close()
    assert not problems


def test_pdf_download(browser, live_url, thread, tmp_path):
    ctx, page, problems = make_page(browser, live_url, 103)
    try:
        page.click('#who-box [data-act="open-diary"]')
        page.check('input[name="fmt"][value="pdf"]')
        page.check('input[name="part"][value="chat"]')
        with page.expect_download(timeout=20000) as dl:
            page.click('#diary-form button[type="submit"]')
        d = dl.value
        assert d.suggested_filename.endswith(".pdf")
        path = tmp_path / "d.pdf"
        d.save_as(path)
        text = "\n".join(p.extract_text() for p in PdfReader(str(path)).pages)
        assert "Дневник: Риг" in text and "Дело для дневника" in text and "СЕКРЕТ" not in text
    finally:
        ctx.close()
    assert not problems


def test_nothing_selected_shows_an_error(browser, live_url, thread):
    ctx, page, problems = make_page(browser, live_url, 103)
    try:
        page.click('#who-box [data-act="open-diary"]')
        for part in ("chron", "entries", "dossier", "handouts", "sheet"):
            page.uncheck(f'input[name="part"][value="{part}"]')
        page.click('#diary-form button[type="submit"]')
        assert "Отметьте" in page.inner_text("#form-err") and page.locator("#diary-form").count() == 1
    finally:
        ctx.close()
    assert not problems


def test_server_error_is_shown(browser, live_url, thread, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "DIARIES_PER_MINUTE", 0)
    ctx, page, problems = make_page(browser, live_url, 103)
    try:
        page.click('#who-box [data-act="open-diary"]')
        page.click('#diary-form button[type="submit"]')
        page.wait_for_function("()=>document.getElementById('form-err').textContent.length>0", timeout=10000)
        assert "Слишком часто" in page.inner_text("#form-err")
        assert page.locator('#diary-form button[type="submit"]').is_enabled()                        # кнопка снова доступна
    finally:
        ctx.close()
    assert not problems


def test_button_is_for_characters_only(browser, live_url, thread):
    for tg, expected in ((1, 0), (106, 0), (103, 1)):                                                # мастер, игрок без персонажа, игрок
        ctx, page, problems = make_page(browser, live_url, tg)
        try:
            assert page.locator('#who-box [data-act="open-diary"]').count() == expected, tg
        finally:
            ctx.close()
        assert not problems


def test_master_previewing_a_player_can_download_that_players_diary(browser, live_url, thread, tmp_path):
    ctx, page, problems = make_page(browser, live_url, 1)
    try:
        page.evaluate("()=>{V='rig';render()}")
        page.click('#who-box [data-act="open-diary"]')
        with page.expect_download(timeout=15000) as dl:
            page.click('#diary-form button[type="submit"]')
        path = tmp_path / "d.md"
        dl.value.save_as(path)
        text = path.read_text(encoding="utf-8")
        assert "Дневник: Риг" in text and "предпросмотр мастера" in text and "СЕКРЕТ" not in text
    finally:
        ctx.close()
    assert not problems
