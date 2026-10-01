"""Панель «Уведомления»: открывается кнопкой в шапке, сохраняет настройки, показывает ошибки, не ломается от вредного ввода."""
import pytest

from ui_support import open_page

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]

PAYLOAD = '"><img src=x onerror=__xss=1>'


@pytest.fixture
def page_of(browser, live_url, gm):
    opened = []

    def make(tg_id):
        problems = []
        ctx, page = open_page(browser, live_url, tg_id, problems)
        opened.append((ctx, problems))
        return page

    yield make
    for ctx, problems in opened:
        ctx.close()
        assert not problems, problems


def open_panel(page):
    page.click('#who-box [data-act="open-prefs"]')
    page.wait_for_selector("#prefs-form", timeout=10000)


def check_clean(page):
    n = page.evaluate("()=>({xss:window.__xss||0,img:document.querySelectorAll('img[src=\"x\"]').length,csp:(window.__csp||[]).length})")
    assert n == {"xss": 0, "img": 0, "csp": 0}, n


def test_panel_opens_saves_and_remembers(page_of, gm):
    page = page_of(1)
    open_panel(page)
    assert page.is_checked('input[name="chat_notify"]')                             # по умолчанию обсуждения включены
    assert page.is_checked('input[name="mode"][value="now"]')
    assert page.is_checked('input[name="remind"]') and "через 2 дня" in page.inner_text("#prefs-form")
    page.uncheck('input[name="remind"]')
    page.check('input[name="mode"][value="digest"]')
    page.select_option('select[name="digest_hour"]', "8")
    page.check('input[name="quiet_on"]')
    page.fill('input[name="tz"]', "Asia/Yekaterinburg")
    page.click('#prefs-form button[type="submit"]')
    page.wait_for_function("()=>document.getElementById('overlay').hidden", timeout=10000)
    saved = page.evaluate("async()=>(await (await fetch('/api/me/prefs',{credentials:'same-origin'})).json()).prefs")
    assert saved["digest_on"] and saved["digest_hour"] == 8 and saved["quiet_on"] and saved["tz"] == "Asia/Yekaterinburg"
    assert saved["remind"] == 0
    open_panel(page)                                                                # при повторном открытии значения на месте
    assert page.is_checked('input[name="mode"][value="digest"]')
    assert page.input_value('select[name="digest_hour"]') == "8"
    assert page.input_value('input[name="tz"]') == "Asia/Yekaterinburg"
    assert not page.is_checked('input[name="remind"]')
    page.check('input[name="mode"][value="now"]')                                   # вернуть как было, чтобы не влиять на другие тесты
    page.fill('input[name="tz"]', "Europe/Moscow")
    page.uncheck('input[name="quiet_on"]')
    page.check('input[name="remind"]')
    page.click('#prefs-form button[type="submit"]')
    page.wait_for_function("()=>document.getElementById('overlay').hidden", timeout=10000)
    check_clean(page)


def test_wrong_timezone_shows_an_error_and_keeps_the_panel_open(page_of):
    page = page_of(1)
    open_panel(page)
    page.fill('input[name="tz"]', PAYLOAD)
    page.click('#prefs-form button[type="submit"]')
    page.wait_for_function("()=>document.getElementById('form-err').textContent.length>0", timeout=10000)
    assert page.is_visible("#prefs-form")
    assert "часов" in page.inner_text("#form-err").lower() or "пояс" in page.inner_text("#form-err").lower()
    check_clean(page)


def test_test_message_reports_an_error_when_the_bot_is_off(page_of):
    page = page_of(1)
    open_panel(page)
    assert page.is_visible("#panel .err:not(#form-err)")                            # предупреждение «уведомления выключены»
    page.click('#prefs-form [data-act="prefs-test"]')
    page.wait_for_function("()=>document.getElementById('form-err').textContent.length>0", timeout=10000)
    check_clean(page)


def test_player_has_the_same_panel(page_of):
    page = page_of(101)
    open_panel(page)
    assert page.is_visible('#prefs-form input[name="tz"]')
    check_clean(page)
