"""«Что видят игроки вперёд» в браузере: переключатель в панели мастера, календарь игрока, предпросмотр мастера."""
import pytest

from helpers import entry, ok
from ui_support import open_page

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]

H, BEYOND = "2075-08-31", "2075-09-10"


@pytest.fixture
def far(gm, sandbox):
    """Мастерская запись на следующий этап; после теста ограничение выключается, а запись убирает sandbox."""
    ok(gm.post("/api/entries", json=entry(char="gm", title="Далёкая встреча", who=["rig"], **{"from": BEYOND, "to": BEYOND})))
    yield
    ok(gm.post("/api/gm/horizon", json={"mode": "off"}))


def plain(text):
    return text.replace("\xa0", " ")


def make_page(browser, live_url, tg_id, section="cal"):
    problems = []
    ctx, page = open_page(browser, live_url, tg_id, problems)
    page.evaluate("s=>{UI.extrasVer=-1;UI.section=s;render()}", section)
    return ctx, page, problems


def test_master_switches_it_on_and_off(browser, live_url, gm, far):
    ctx, page, problems = make_page(browser, live_url, 1, "gm")
    try:
        assert "Что видят игроки вперёд" in page.inner_text("#gm-horizon h2")
        assert page.get_attribute('#gm-horizon [data-v="off"]', "aria-pressed") == "true"
        assert "до конца кампании" in plain(page.inner_text("#hz-line")) and "31 августа" in plain(page.inner_text("#hz-line"))
        page.click('#gm-horizon [data-v="window"]')
        page.wait_for_function("()=>document.querySelector('#gm-horizon [data-v=\"window\"]').getAttribute('aria-pressed')==='true'", timeout=10000)
        line = plain(page.inner_text("#hz-line"))
        assert "Игроки видят календарь до" in line and "31 августа" in line and "Промежуточная арка" in line and "Скрыто от них: 1 запись" in line
        assert page.evaluate("()=>CAL_END") == "2075-12-31"                                  # у мастера календарь прежний
        page.click('#gm-horizon [data-v="off"]')
        page.wait_for_function("()=>document.querySelector('#gm-horizon [data-v=\"off\"]').getAttribute('aria-pressed')==='true'", timeout=10000)
    finally:
        ctx.close()
    assert not problems


def test_player_calendar_ends_at_the_border_and_says_so(browser, live_url, gm, far):
    ok(gm.post("/api/gm/horizon", json={"mode": "window"}))
    ctx, page, problems = make_page(browser, live_url, 103)
    try:
        assert page.evaluate("()=>CAL_END") == H
        assert "Календарь открыт до" in plain(page.inner_text(".hz-note")) and "31 августа" in plain(page.inner_text(".hz-note"))
        assert "Далёкая встреча" not in page.inner_text("#main")
        page.evaluate("()=>openForm('2075-08-05')")
        page.wait_for_selector("#entry-form")
        days = page.evaluate("()=>[...document.querySelectorAll('#entry-form select[name=\"from\"] option')].map(o=>o.value)")
        assert days and max(days) == H and BEYOND not in days                              # дальше границы дату не выбрать
    finally:
        ctx.close()
    assert not problems


def test_master_sees_the_same_as_the_player_in_the_preview(browser, live_url, gm, far):
    ok(gm.post("/api/gm/horizon", json={"mode": "window"}))
    ctx, page, problems = make_page(browser, live_url, 1, "cal")
    try:
        assert page.evaluate("()=>CAL_END") == "2075-12-31"
        assert page.evaluate("()=>S.entries.filter(canSee).some(e=>e.title==='Далёкая встреча')") is True
        page.select_option("#who-select", "rig")
        assert page.evaluate("()=>CAL_END") == H
        assert page.evaluate("()=>S.entries.filter(canSee).some(e=>e.title==='Далёкая встреча')") is False
        assert page.evaluate("()=>MONTH_LIST.length") == 2                                  # июль и август
        page.select_option("#who-select", "gm")
        assert page.evaluate("()=>CAL_END") == "2075-12-31" and page.evaluate("()=>MONTH_LIST.length") == 6
    finally:
        ctx.close()
    assert not problems


def test_turning_it_off_gives_players_the_whole_calendar_back(browser, live_url, gm, far):
    ok(gm.post("/api/gm/horizon", json={"mode": "window"}))
    ctx, page, problems = make_page(browser, live_url, 103)
    try:
        assert page.evaluate("()=>CAL_END") == H
        ok(gm.post("/api/gm/horizon", json={"mode": "off"}))
        page.evaluate("()=>poll()")
        page.wait_for_function("()=>CAL_END==='2075-12-31'", timeout=10000)
        assert page.locator(".hz-note").count() == 0
    finally:
        ctx.close()
    assert not problems
