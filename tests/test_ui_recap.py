"""«Что было раньше» в браузере: кнопка, выбор периода, показ пересказа, ошибки. Claude подменён заглушкой, настоящий API не вызывается."""
from types import SimpleNamespace

import pytest

from app import config, db, recap
from helpers import ok
from ui_support import open_page

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]

EVIL = "<img src=x onerror=__xss=1 id=recap>"


class Fake:
    def __init__(self, reply):
        self.calls = []
        self.reply = reply
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self.messages = self.beta.messages

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.reply)], stop_reason="end_turn", usage=SimpleNamespace(input_tokens=10, output_tokens=5))


@pytest.fixture
def on(monkeypatch, gm, sandbox):
    monkeypatch.setattr(config, "RECAP_ENABLED", True)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-тест")
    monkeypatch.setattr(config, "RECAP_PER_DAY", 100)
    monkeypatch.setattr(config, "RECAP_DAILY_TOTAL", 100)
    recap._recent.clear()
    db.conn().execute("DELETE FROM recaps")
    ok(gm.post("/api/gm/items/past", json={"title": "Налёт на склад", "from": "2075-07-25", "to": "2075-07-25", "note": "Груз захвачен", "session": "Сессия 2"}))
    fake = Fake(f"Вы пропустили налёт.\n{EVIL}")
    monkeypatch.setattr(recap, "_client", lambda: fake)
    yield fake
    db.conn().execute("DELETE FROM recaps")


def make_page(browser, live_url, tg_id):
    problems = []
    ctx, page = open_page(browser, live_url, tg_id, problems)
    page.evaluate("()=>{UI.section='chron';render()}")
    return ctx, page, problems


def test_player_gets_a_recap(browser, live_url, on):
    ctx, page, problems = make_page(browser, live_url, 103)
    try:
        page.click('[data-act="open-recap"]')
        page.wait_for_selector("#recap-form", timeout=10000)
        labels = page.locator("#recap-form fieldset label").all_inner_texts()
        assert any("Сессия 2" in t for t in labels) and any("Начиная с даты" in t for t in labels) and "Anthropic" in page.inner_text("#recap-form")
        page.click('#recap-form button[type="submit"]')
        page.wait_for_selector(".recap-text", timeout=15000)
        text = page.inner_text(".recap-text")
        assert "Вы пропустили налёт." in text and EVIL in text                                      # разметка из ответа выведена буквами
        assert page.evaluate("()=>({xss:window.__xss||0,img:document.querySelectorAll('img[src=\"x\"]').length,csp:(window.__csp||[]).length})") == {"xss": 0, "img": 0, "csp": 0}
        assert len(on.calls) == 1 and "Налёт на склад" in on.calls[0]["messages"][0]["content"]
        page.click('#panel [data-act="open-recap"]')                                               # другой период
        page.check('input[name="since"][value="custom"]')
        assert page.is_visible("#recap-date-box")
        page.select_option('#recap-form select[name="date"]', "2075-07-25")
        page.click('#recap-form button[type="submit"]')
        page.wait_for_selector(".recap-text", timeout=15000)
        assert "ранее сделанный" in page.inner_text("#panel") and len(on.calls) == 1                # тот же материал: из памяти, второй платный запрос не нужен
    finally:
        ctx.close()
    assert not problems


def test_server_error_is_shown_in_the_form(browser, live_url, on, monkeypatch):
    def broken():
        raise recap.anthropic.APIConnectionError(request=__import__("httpx2").Request("POST", "https://api.anthropic.com/v1/messages"))
    monkeypatch.setattr(recap, "_client", broken)
    ctx, page, problems = make_page(browser, live_url, 103)
    try:
        page.click('[data-act="open-recap"]')
        page.click('#recap-form button[type="submit"]')
        page.wait_for_function("()=>document.getElementById('form-err').textContent.length>0", timeout=10000)
        assert "связаться" in page.inner_text("#form-err") and page.is_enabled('#recap-form button[type="submit"]')
    finally:
        ctx.close()
    assert not problems


def test_no_button_without_the_key_for_the_master_and_in_preview(browser, live_url, on, monkeypatch):
    ctx, page, problems = make_page(browser, live_url, 1)
    try:
        assert page.locator('[data-act="open-recap"]').count() == 0                                   # мастеру пересказ не нужен
        page.evaluate("()=>{V='rig';render()}")
        assert page.locator('[data-act="open-recap"]').count() == 0                                   # в предпросмотре тоже: он стоил бы денег
    finally:
        ctx.close()
    assert not problems
    monkeypatch.setattr(config, "RECAP_ENABLED", False)
    ctx, page, problems = make_page(browser, live_url, 103)
    try:
        assert page.locator('[data-act="open-recap"]').count() == 0
    finally:
        ctx.close()
    assert not problems
