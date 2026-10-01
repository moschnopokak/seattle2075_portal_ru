"""Вёрстка шапки в настоящем браузере: вкладки не прячутся за край на планшете и в узком окне, кнопки шапки не разъезжаются на телефоне.

Эти проверки появились после сравнения с прежней версией: новые вкладка «Лист» и кнопки «Мой дневник» и «Уведомления» делали шапку шире
экрана, и часть вкладок на планшете оказывалась недоступной без прокрутки, а на телефоне «Выйти» уходило на отдельную строку.
"""
import pytest

from ui_support import open_page

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]

GM, MAX, RIG = 1, 101, 103

HIDDEN_TABS = """()=>{const n=document.getElementById('nav'),r0=n.getBoundingClientRect();
  return [...n.querySelectorAll('button')].filter(t=>{const r=t.getBoundingClientRect();return r.right>r0.right+1||r.left<r0.left-1}).map(t=>t.textContent.trim());}"""
# сколько строк занимают кнопки шапки: элементы одной строки пересекаются по вертикали (выровнены по центру, поэтому верхние края разные)
ACTION_ROWS = """()=>{const els=[...document.querySelectorAll('#who-box > *')].filter(e=>e.offsetWidth>0).map(e=>e.getBoundingClientRect()).sort((a,b)=>a.top-b.top);
  const rows=[];for(const r of els){const row=rows.find(x=>r.top<x.bottom-1&&r.bottom>x.top+1);if(row){row.top=Math.min(row.top,r.top);row.bottom=Math.max(row.bottom,r.bottom);}else rows.push({top:r.top,bottom:r.bottom});}
  return rows.length;}"""
TOP_HEIGHT = "()=>document.getElementById('app-top').offsetHeight"
SCROLLS_SIDEWAYS = "()=>document.documentElement.scrollWidth>document.documentElement.clientWidth"


@pytest.fixture
def at_width(browser, live_url, gm):
    opened = []

    def make(tg_id, width, height=800):
        problems = []
        ctx, page = open_page(browser, live_url, tg_id, problems)
        opened.append((ctx, problems))
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_timeout(150)
        return page

    yield make
    for ctx, problems in opened:
        ctx.close()
        assert not problems, problems


@pytest.mark.parametrize("tg_id", [GM, MAX, RIG], ids=["мастер", "игрок с двумя персонажами", "игрок"])
@pytest.mark.parametrize("width", [761, 800, 900, 1024, 1100, 1280, 1440])
def test_no_tab_is_hidden_on_tablets_and_laptops(at_width, tg_id, width):
    page = at_width(tg_id, width)
    assert page.evaluate(HIDDEN_TABS) == [], f"при ширине {width} px вкладки не помещаются"
    assert not page.evaluate(SCROLLS_SIDEWAYS)


@pytest.mark.parametrize("tg_id,width,rows", [
    (GM, 360, 1), (GM, 390, 1), (GM, 412, 1),
    (RIG, 360, 1), (RIG, 390, 1), (RIG, 412, 1),
    (MAX, 412, 1),
    (MAX, 390, 2), (MAX, 360, 2),                                           # «Играю за», «Мой дневник», «Уведомления» и «Выйти» вместе шире 390 px: «Выйти» переходит на вторую строку
], ids=lambda v: str(v))
def test_header_buttons_do_not_scatter_on_phones(at_width, tg_id, width, rows):
    page = at_width(tg_id, width)
    assert page.evaluate(ACTION_ROWS) == rows, f"кнопки шапки при ширине {width} px занимают не {rows} строк"
    assert page.evaluate(TOP_HEIGHT) <= (145 if rows == 1 else 175)
    assert not page.evaluate(SCROLLS_SIDEWAYS)


def test_phone_tabs_scroll_instead_of_wrapping(at_width):
    page = at_width(GM, 390)
    assert page.evaluate("()=>document.getElementById('nav').scrollWidth>document.getElementById('nav').clientWidth")
    assert page.evaluate("()=>new Set([...document.querySelectorAll('#nav button')].map(b=>Math.round(b.getBoundingClientRect().top))).size") == 1


def test_background_checkbox_text_flows_after_the_box(at_width):
    page = at_width(GM, 390, 900)
    page.evaluate("()=>{UI.section='map';render();}")
    page.wait_for_function("()=>typeof MAP!=='undefined'&&MAP&&document.querySelector('#map-tools')", timeout=15000)
    page.evaluate("()=>openItemForm('places',null,{x:36500,y:52000})")
    page.wait_for_selector("form input[name=bg]")
    box = page.evaluate("""()=>{const l=document.querySelector('form input[name=bg]').closest('label');return {display:getComputedStyle(l).display,lines:Math.round(l.getBoundingClientRect().height/parseFloat(getComputedStyle(l).lineHeight||'20'))}}""")
    assert box["display"] == "block" and box["lines"] <= 3
