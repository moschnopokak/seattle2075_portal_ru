"""Раздатки-файлы в браузере: карточки, просмотр картинки, звука, PDF, загрузка мастером через форму."""
import pytest

from helpers import ok
from media import HTML, PDF, png_bytes, wav_bytes
from ui_support import open_page

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]

TITLES = ("Рисунок", "Запись голоса", "Письмо в PDF", "Страница", "Загруженная мастером")


def clean(gm):
    for h in ok(gm.get("/api/state"))["handouts"]:
        if h["title"] in TITLES:
            gm.post(f"/api/gm/items/handouts/{h['id']}/delete")
    for t in ok(gm.get("/api/gm/trash"))["items"]:
        if t["title"] in TITLES:
            gm.post(f"/api/gm/trash/{t['id']}/purge")


@pytest.fixture
def files(gm):
    made = {}
    for title, raw in (("Рисунок", png_bytes((120, 60))), ("Запись голоса", wav_bytes()), ("Письмо в PDF", PDF), ("Страница", HTML)):
        data = ok(gm.post("/api/gm/items/handouts", json={"title": title, "date": "2075-08-01", "vis": "стол", "known": [], "note": "", "gm_note": ""}))
        hid = next(h["id"] for h in data["state"]["handouts"] if h["title"] == title)
        ok(gm.post(f"/api/gm/handouts/{hid}/file", content=raw, headers={"X-File-Name": "f"}))
        made[title] = hid
    yield made
    clean(gm)


def make_page(browser, live_url, tg_id):
    problems = []
    ctx, page = open_page(browser, live_url, tg_id, problems)
    page.evaluate("async()=>{const r=await fetch('/api/state',{credentials:'same-origin'});applyState(await r.json());}")
    return ctx, page, problems


@pytest.fixture
def player(browser, live_url, files):
    ctx, page, problems = make_page(browser, live_url, 103)           # Риг
    yield page
    ctx.close()
    assert not problems, problems


@pytest.fixture
def master(browser, live_url, files):
    ctx, page, problems = make_page(browser, live_url, 1)
    yield page
    ctx.close()
    assert not problems, problems


def open_viewer(page, hid):
    page.evaluate("id=>{UI.section='handouts';render();openHandout(id)}", hid)
    page.wait_for_selector(".hv", timeout=10000)


def csp_clean(page):
    assert page.evaluate("()=>(window.__csp||[]).length") == 0


def test_cards_show_the_kind(player, files):
    player.evaluate("()=>{UI.section='handouts';render()}")
    meta = {t: player.locator(".hc", has_text=t).first.locator(".hc-meta").inner_text() for t in TITLES[:4]}
    assert "картинка" in meta["Рисунок"] and "аудио" in meta["Запись голоса"] and "PDF" in meta["Письмо в PDF"]
    assert "картинка" not in meta["Страница"] and "PDF" not in meta["Страница"] and "аудио" not in meta["Страница"]
    csp_clean(player)


def test_image_opens_in_the_viewer_and_zooms(player, files):
    open_viewer(player, files["Рисунок"])
    img = player.locator(".hv .hv-img")
    player.wait_for_function("()=>{const i=document.querySelector('.hv .hv-img');return i&&i.complete&&i.naturalWidth>0}", timeout=10000)
    assert img.evaluate("i=>[i.naturalWidth,i.naturalHeight]") == [120, 60]
    assert player.locator(".hv iframe").count() == 0
    img.click()
    assert "full" in img.get_attribute("class")
    img.click()
    assert "full" not in img.get_attribute("class")
    link = player.locator('.hv-acts a[download]')
    assert link.count() == 1 and link.get_attribute("href").startswith("/handout/")
    assert player.locator('.hv-acts a[target="_blank"]').count() == 1
    csp_clean(player)


def test_audio_has_a_player_and_loads(player, files):
    open_viewer(player, files["Запись голоса"])
    player.wait_for_selector(".hv audio.hv-audio[controls]", timeout=10000)
    player.wait_for_function("()=>{const a=document.querySelector('.hv audio');return a.readyState>=1&&a.duration>0}", timeout=10000)
    assert player.locator(".hv audio").get_attribute("src").startswith("/handout/")
    csp_clean(player)


def test_pdf_is_in_a_plain_frame_and_html_stays_sandboxed(player, files):
    open_viewer(player, files["Письмо в PDF"])
    frame = player.locator(".hv iframe.hv-frame")
    assert frame.count() == 1 and frame.get_attribute("sandbox") is None and frame.get_attribute("src").startswith("/handout/")
    assert player.locator('.hv-acts a[download]').count() == 1
    player.evaluate("()=>closeHandout()")
    open_viewer(player, files["Страница"])
    html = player.locator(".hv iframe.hv-frame")
    assert "allow-scripts" in html.get_attribute("sandbox") and "allow-same-origin" not in html.get_attribute("sandbox")
    assert player.locator('.hv-acts a[download]').count() == 0                    # у страницы кнопки «Скачать» нет
    csp_clean(player)


def test_master_uploads_a_picture_through_the_form(master, gm):
    master.evaluate("()=>{UI.section='handouts';render();openHandoutForm()}")
    form = master.locator("#handout-form")
    assert "pdf" in form.locator('input[type="file"]').get_attribute("accept") and "audio" in form.locator('input[type="file"]').get_attribute("accept")
    form.locator('input[type="file"]').set_input_files({"name": "Загруженная мастером.png", "mimeType": "image/png", "buffer": png_bytes((30, 30))})
    assert form.locator('input[name="title"]').input_value() == "Загруженная мастером"
    form.locator('input[name="vis"][value="стол"]').check()
    form.locator('button[type="submit"]').click()
    master.wait_for_function("()=>(S.handouts||[]).some(h=>h.title==='Загруженная мастером'&&h.kind==='image'&&h.file)", timeout=15000)
    master.wait_for_function("()=>document.getElementById('overlay').hidden", timeout=10000)
    assert "картинка" in master.locator(".hc", has_text="Загруженная мастером").first.inner_text()
    csp_clean(master)
    clean(gm)


def test_master_gets_a_clear_error_for_a_bad_file(master, gm):
    master.evaluate("()=>{UI.section='handouts';render();openHandoutForm()}")
    form = master.locator("#handout-form")
    form.locator('input[type="file"]').set_input_files({"name": "сломанная.png", "mimeType": "image/png", "buffer": b"\x89PNG\r\n\x1a\n" + b"x" * 40})
    form.locator('input[name="title"]').fill("Загруженная мастером")
    form.locator('button[type="submit"]').click()
    master.wait_for_function("()=>document.getElementById('form-err').textContent.length>0", timeout=10000)
    assert "не читается" in master.inner_text("#form-err")
    clean(gm)
