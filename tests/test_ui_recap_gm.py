"""«Что было раньше» через мастера в браузере: просьба игрока, очередь и ответ у мастера, ответ у игрока.
Настоящий Claude не нужен вовсе: страница ни разу не обращается к его API, текст пересказа мастер вставляет сам."""
import pytest

from app import config, db, recap
from conftest import GM
from helpers import ok
from ui_support import open_page

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]

EVIL = "<img src=x onerror=__xss=1 id=recap>"
GM_TG, PLAYER_TG = GM, 103          # Риг


@pytest.fixture
def on(monkeypatch, gm, sandbox):
    monkeypatch.setattr(config, "RECAP_MANUAL", True)
    monkeypatch.setattr(config, "RECAP_ENABLED", False)
    monkeypatch.setattr(config, "RECAP_PER_DAY", 100)

    def no_api():
        raise AssertionError("Claude API в режиме «через мастера» не вызывается")
    monkeypatch.setattr(recap, "_client", no_api)
    recap._recent.clear()
    db.conn().execute("DELETE FROM recap_requests")
    ok(gm.post("/api/gm/items/past", json={"title": "Налёт на склад", "from": "2075-07-25", "to": "2075-07-25", "note": "Груз захвачен", "gm_note": "СЕКРЕТ-мастера", "session": "Сессия 2"}))
    yield
    db.conn().execute("DELETE FROM recap_requests")


def make_page(browser, live_url, tg_id, section):
    problems = []
    ctx, page = open_page(browser, live_url, tg_id, problems)
    page.evaluate("s=>{UI.section=s;render()}", section)
    return ctx, page, problems


def poll(page):
    page.evaluate("()=>poll()")
    page.wait_for_timeout(300)


def request_as(client, char="rig", since="2075-07-20"):
    return ok(client.post("/api/me/recap", json={"char": char, "since": since}))


# ---------------------------------------------------------------- игрок просит

def test_player_asks_and_sees_that_the_master_has_it(browser, live_url, on):
    ctx, page, problems = make_page(browser, live_url, PLAYER_TG, "chron")
    try:
        assert page.inner_text('[data-act="open-recap"]') == "Что было раньше"
        page.click('[data-act="open-recap"]')
        page.wait_for_selector("#recap-form", timeout=10000)
        form = page.inner_text("#recap-form")
        assert "готовит мастер" in form and "видит ровно то, что видите вы" in form and "Anthropic" not in form
        assert page.inner_text('#recap-form button[type="submit"]') == "Попросить пересказ"
        page.click('#recap-form button[type="submit"]')
        page.wait_for_selector("#panel >> text=Просьба отправлена мастеру", timeout=10000)
        page.click('#panel [data-act="close"]')
        poll(page)
        assert page.inner_text('[data-act="open-recap"]') == "Что было раньше (ждёт мастера)"
        page.click('[data-act="open-recap"]')
        page.wait_for_selector("#recap-mine .recap-req", timeout=10000)
        assert "ждёт мастера" in page.inner_text("#recap-mine") and page.locator("#recap-mine [data-act]").count() == 0
        assert len(db.conn().execute("SELECT * FROM recap_requests WHERE status='open'").fetchall()) == 1
    finally:
        ctx.close()
    assert not problems


def test_no_button_for_the_master_and_in_preview(browser, live_url, on):
    ctx, page, problems = make_page(browser, live_url, GM_TG, "chron")
    try:
        assert page.locator('[data-act="open-recap"]').count() == 0
        page.evaluate("()=>{V='rig';render()}")
        assert page.locator('[data-act="open-recap"]').count() == 0                      # в предпросмотре за игрока просить нельзя
    finally:
        ctx.close()
    assert not problems


# ---------------------------------------------------------------- мастер отвечает

def test_master_copies_the_request_and_sends_the_answer(browser, live_url, on, rig):
    request_as(rig)
    ctx, page, problems = make_page(browser, live_url, GM_TG, "gm")
    try:
        ctx.grant_permissions(["clipboard-read", "clipboard-write"])
        page.wait_for_selector("#recap-queue .recap-q", timeout=10000)
        assert "Просьбы о пересказе (1)" in page.inner_text("#gm-recap h2")
        item = page.inner_text("#recap-queue .recap-q")
        assert "Риг" in item and "просит пересказ с" in item
        page.click('#recap-queue [data-act="recap-copy-prompt"]')
        page.wait_for_selector("#toast >> text=Запрос скопирован", timeout=5000)
        copied = page.evaluate("()=>navigator.clipboard.readText()")
        assert copied.startswith("Ты помощник ведущего") and "Персонаж: Риг" in copied and "Налёт на склад" in copied
        assert "СЕКРЕТ" not in copied                                                   # заметки мастера в запрос не попадают
        page.fill("#recap-queue .recap-answer", f"Вы пропустили налёт.\n{EVIL}")
        page.click('#recap-queue [data-act="recap-send"]')
        page.wait_for_selector("#toast >> text=Пересказ отправлен: Риг", timeout=10000)
        page.wait_for_function("()=>!document.querySelector('#recap-queue .recap-q')", timeout=10000)
        assert "Просьб нет" in page.inner_text("#recap-queue") and "Просьбы о пересказе" in page.inner_text("#gm-recap h2") and "(" not in page.inner_text("#gm-recap h2")
        assert page.evaluate("()=>window.__xss||0") == 0
    finally:
        ctx.close()
    assert not problems


def test_player_reads_the_answer_as_plain_text(browser, live_url, on, rig, gm):
    req = request_as(rig)
    ok(gm.post(f"/api/gm/recap/{req['id']}/answer", json={"text": f"Вы пропустили налёт.\n{EVIL}"}))
    ctx, page, problems = make_page(browser, live_url, PLAYER_TG, "chron")
    try:
        assert page.inner_text('[data-act="open-recap"]') == "Что было раньше (ответ готов)"
        assert "primary" in page.get_attribute('[data-act="open-recap"]', "class")
        page.click('[data-act="open-recap"]')
        page.wait_for_selector("#recap-mine .recap-req", timeout=10000)
        assert "пересказ готов" in page.inner_text("#recap-mine")
        page.wait_for_function("()=>document.querySelector('[data-act=\"open-recap\"]').textContent==='Что было раньше'", timeout=5000)   # открыл список: метка погасла
        page.click('#recap-mine [data-act="recap-show"]')
        page.wait_for_selector(".recap-text", timeout=10000)
        text = page.inner_text(".recap-text")
        assert "Вы пропустили налёт." in text and EVIL in text                           # разметка из ответа выведена буквами
        assert page.evaluate("()=>({xss:window.__xss||0,img:document.querySelectorAll('img[src=\"x\"]').length,csp:(window.__csp||[]).length})") == {"xss": 0, "img": 0, "csp": 0}
        assert "готовит мастер" in page.inner_text("#panel")
        page.click('#panel [data-act="recap-copy"]')
        page.wait_for_selector("#toast >> text=Пересказ скопирован", timeout=5000)
    finally:
        ctx.close()
    assert not problems


def test_the_same_request_after_an_answer_shows_it_at_once(browser, live_url, on, rig, gm):
    req = request_as(rig, since="2075-07-25")                                            # тот же период, что предлагает форма: «последняя сессия»
    ok(gm.post(f"/api/gm/recap/{req['id']}/answer", json={"text": "Готовый пересказ."}))
    ctx, page, problems = make_page(browser, live_url, PLAYER_TG, "chron")
    try:
        page.click('[data-act="open-recap"]')
        page.wait_for_selector("#recap-form")
        page.click('#recap-form button[type="submit"]')
        page.wait_for_selector(".recap-text", timeout=10000)
        assert page.inner_text(".recap-text") == "Готовый пересказ." and "ранее сделанный" in page.inner_text("#panel")
    finally:
        ctx.close()
    assert not problems


def test_decline_shows_the_reason_to_the_player(browser, live_url, on, rig):
    request_as(rig)
    ctx, page, problems = make_page(browser, live_url, GM_TG, "gm")
    try:
        page.wait_for_selector("#recap-queue .recap-q", timeout=10000)
        page.fill("#recap-queue .recap-note", "Расскажу на игре")
        page.click('#recap-queue [data-act="recap-decline"]')
        page.wait_for_selector("#toast >> text=Просьба отклонена: Риг", timeout=10000)
    finally:
        ctx.close()
    assert not problems
    ctx, page, problems = make_page(browser, live_url, PLAYER_TG, "chron")
    try:
        assert page.inner_text('[data-act="open-recap"]') == "Что было раньше (ответ готов)"
        page.click('[data-act="open-recap"]')
        page.wait_for_selector("#recap-mine .recap-req.no", timeout=10000)
        assert "мастер пока не может" in page.inner_text("#recap-mine") and "Расскажу на игре" in page.inner_text("#recap-mine")
    finally:
        ctx.close()
    assert not problems


# ---------------------------------------------------------------- вёрстка и ввод

def test_typed_answer_survives_a_redraw_and_a_new_request(browser, live_url, on, rig, gate):
    request_as(rig)
    ctx, page, problems = make_page(browser, live_url, GM_TG, "gm")
    try:
        page.wait_for_selector("#recap-queue .recap-q", timeout=10000)
        area = "#recap-queue .recap-answer"
        page.click(area)
        page.keyboard.type("Начало пересказа, ")
        page.evaluate("()=>render(true)")                                               # любая перерисовка страницы
        assert page.input_value(area) == "Начало пересказа, " and page.evaluate("()=>document.activeElement.classList.contains('recap-answer')")
        page.keyboard.type("продолжение")
        request_as(gate, char="gate")                                                   # пока мастер печатает, приходит ещё одна просьба
        poll(page)
        page.wait_for_function("()=>document.querySelectorAll('#recap-queue .recap-q').length===2", timeout=10000)
        first = page.locator("#recap-queue .recap-q").first.locator(".recap-answer")
        assert first.input_value() == "Начало пересказа, продолжение"
        assert page.evaluate("()=>document.activeElement.classList.contains('recap-answer')")
        assert page.locator("#recap-queue .recap-q").nth(1).locator(".recap-answer").input_value() == ""
    finally:
        ctx.close()
    assert not problems


def test_nothing_overflows_on_a_phone(browser, live_url, on, rig):
    request_as(rig)
    for width in (360, 390):
        problems = []
        ctx, page = open_page(browser, live_url, GM_TG, problems)
        try:
            page.set_viewport_size({"width": width, "height": 800})
            page.evaluate("()=>{UI.section='gm';render()}")
            page.wait_for_selector("#recap-queue .recap-q", timeout=10000)
            page.click("#recap-queue summary")
            over = page.evaluate("()=>({page:document.documentElement.scrollWidth-document.documentElement.clientWidth,"
                                 "box:[...document.querySelectorAll('#gm-recap *')].filter(e=>e.getBoundingClientRect().right>document.documentElement.clientWidth+1).map(e=>e.className||e.tagName)})")
            assert over["page"] <= 0 and over["box"] == [], (width, over)
        finally:
            ctx.close()
        assert not problems


def test_no_queue_block_when_the_mode_is_off(browser, live_url, on, monkeypatch):
    monkeypatch.setattr(config, "RECAP_MANUAL", False)
    ctx, page, problems = make_page(browser, live_url, GM_TG, "gm")
    try:
        assert page.locator("#gm-recap").count() == 0
    finally:
        ctx.close()
    assert not problems


def test_tab_badges_show_open_requests_to_the_master_and_answers_to_the_player(browser, live_url, on, rig, gm):
    req = request_as(rig)
    ctx, page, problems = make_page(browser, live_url, GM_TG, "now")
    try:
        assert page.inner_text('#nav [data-nav="gm"]').replace("\n", " ").strip().endswith("1")
        assert page.locator('#nav [data-nav="chron"] .nav-badge').count() == 0
    finally:
        ctx.close()
    assert not problems
    ctx, page, problems = make_page(browser, live_url, PLAYER_TG, "now")
    try:
        assert page.locator('#nav [data-nav="chron"] .nav-badge').count() == 0              # ответа ещё нет
    finally:
        ctx.close()
    assert not problems
    ok(gm.post(f"/api/gm/recap/{req['id']}/answer", json={"text": "Готово."}))
    ctx, page, problems = make_page(browser, live_url, PLAYER_TG, "now")
    try:
        assert page.inner_text('#nav [data-nav="chron"] .nav-badge') == "1"
        page.evaluate("()=>{UI.section='chron';render()}")
        page.click('[data-act="open-recap"]')
        page.wait_for_selector("#recap-mine .recap-req", timeout=10000)
        page.wait_for_function("()=>!document.querySelector('#nav [data-nav=\"chron\"] .nav-badge')", timeout=5000)     # открыл список: метка погасла
    finally:
        ctx.close()
    assert not problems
    ctx, page, problems = make_page(browser, live_url, GM_TG, "now")
    try:
        assert page.locator('#nav [data-nav="gm"] .nav-badge').count() == 0                  # у мастера очередь пуста
    finally:
        ctx.close()
    assert not problems
