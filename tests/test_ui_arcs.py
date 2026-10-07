"""Загрузка разбора арки в браузере: вставка ответа чата, отчёт, добавление, повторная загрузка, ошибки, вёрстка на телефоне."""
import json

import pytest

from conftest import GM
from helpers import ok
from test_arcs import good
from ui_support import open_page

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]

EVIL = "<img src=x onerror=__xss=1 id=arc>"


def chat_answer(data):
    """Ответ чата, каким он приходит: сначала рассказ, потом блок json, потом вопросы."""
    return f"Часть А. Кратко об арке\nГруз и погоня.\n\nЧасть Б. Данные для портала\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```\n\nЧасть В. Вопросы мастеру\n1. Верно?"


def make_page(browser, live_url, tg_id=GM):
    problems = []
    ctx, page = open_page(browser, live_url, tg_id, problems)
    page.evaluate("()=>{UI.extrasVer=-1;UI.section='gm';render()}")
    return ctx, page, problems


def paste_and_check(page, text):
    page.click('[data-act="arc-open"]')
    page.wait_for_selector("#arc-text")
    page.fill("#arc-text", text)
    page.click('[data-act="arc-check"]')


def dossier_names(gm):
    return [c["name"] for c in ok(gm.get("/api/state"))["dossier"]]


def test_paste_check_add_and_nothing_goes_to_players(browser, live_url, gm, rig, sandbox):
    ctx, page, problems = make_page(browser, live_url)
    try:
        assert "Загрузить разбор арки" in page.inner_text("#gm-arc h2")
        paste_and_check(page, chat_answer(good()))
        page.wait_for_selector("#panel .arc-row", timeout=10000)
        text = page.inner_text("#panel")
        assert "Добавится: 11" in text and "План мастера 2" in text and "Пока ничего не записано" in text
        assert page.locator("#panel .arc-row.add").count() == 11 and page.locator("#panel .arc-row.error").count() == 0
        assert "Дата встречи: поставил 2075-11-03. Верно?" in text                   # вопросы из разбора видны мастеру
        assert "Мистер Джонсон" not in dossier_names(gm)                             # проверка ничего не записала
        page.click('#panel [data-act="arc-go"]')
        page.wait_for_selector("#panel >> text=Разбор арки загружен", timeout=10000)
        assert "Добавлено: 11" in page.inner_text("#panel") and "Игрокам ничего не отправлено" in page.inner_text("#panel")
        page.wait_for_function("()=>!!document.querySelector('#toast')&&document.querySelector('#toast').textContent.includes('Добавлено: 11')", timeout=5000)
        assert "Мистер Джонсон" in dossier_names(gm)
        page.click('#panel [data-act="close"]')
        assert "Погоня по эстакаде" in page.inner_text("#main") or "Погоня по эстакаде" in json.dumps(ok(gm.get("/api/state"))["plan"], ensure_ascii=False)
        page.evaluate("()=>{UI.extrasVer=-1;render(true);gmLoadExtras(true)}")
        page.wait_for_function("()=>document.getElementById('hist-list')&&document.getElementById('hist-list').textContent.includes('Импорт разбора арки: 11')", timeout=10000)
        hist = page.inner_text("#hist-list")
        assert "загрузил(а)" in hist and "import" not in hist.replace("Импорт", "")  # в журнале по-русски, а не «import»
    finally:
        ctx.close()
    assert not problems
    assert "СЕКРЕТ" not in rig.get("/api/state").text


def test_loading_the_same_text_again_says_there_is_nothing_to_add(browser, live_url, gm, sandbox):
    ok(gm.post("/api/gm/arc/import", json={"data": good()}))
    ctx, page, problems = make_page(browser, live_url)
    try:
        paste_and_check(page, chat_answer(good()))
        page.wait_for_selector("#panel .arc-row", timeout=10000)
        assert page.locator("#panel .arc-row.skip").count() == 11 and page.locator("#panel .arc-row.add").count() == 0
        assert "Добавлять нечего" in page.inner_text("#panel") and page.locator('#panel [data-act="arc-go"]').count() == 0
    finally:
        ctx.close()
    assert not problems


def test_bad_items_are_named_and_the_rest_is_added(browser, live_url, gm, sandbox):
    data = good()
    data["plan"].append({"title": "Вне календаря", "from": "2099-01-01", "to": "2099-01-01"})
    ctx, page, problems = make_page(browser, live_url)
    try:
        paste_and_check(page, chat_answer(data))
        page.wait_for_selector("#panel .arc-row.error", timeout=10000)
        bad = page.inner_text("#panel .arc-row.error")
        assert "Вне календаря" in bad and "вне календаря кампании" in bad and "не пройдёт" in bad
        assert "Добавить: 11" in page.inner_text('#panel [data-act="arc-go"]')
        page.click('#panel [data-act="arc-go"]')
        page.wait_for_selector("#panel >> text=Разбор арки загружен", timeout=10000)
        done = page.inner_text("#panel")
        assert "Добавлено: 11, пропущено: 1" in done and "не добавлено" in page.inner_text("#panel .arc-row.error")
    finally:
        ctx.close()
    assert not problems
    assert "Вне календаря" not in json.dumps(ok(gm.get("/api/state"))["plan"], ensure_ascii=False)


@pytest.mark.parametrize("text, message", [("", "Вставьте ответ"), ("Просто рассказ без данных", "Не нашёл в тексте блок json"),
                                           ("```json\n{\"plan\": [{\"title\": \"ой\"\n```", "прочитать их не получилось"),
                                           ('{"questions": ["только вопросы"], "plan": []}', "нет ни одного события")])
def test_unusable_text_is_explained_in_the_window(browser, live_url, gm, sandbox, text, message):
    ctx, page, problems = make_page(browser, live_url)
    try:
        paste_and_check(page, text)
        page.wait_for_function("()=>document.getElementById('arc-err')&&document.getElementById('arc-err').textContent.length>0", timeout=10000)
        assert message in page.inner_text("#arc-err") and page.is_enabled('#panel [data-act="arc-check"]')
    finally:
        ctx.close()
    assert not problems


def test_another_text_keeps_what_was_pasted(browser, live_url, gm, sandbox):
    ctx, page, problems = make_page(browser, live_url)
    try:
        answer = chat_answer(good())
        paste_and_check(page, answer)
        page.wait_for_selector("#panel .arc-row", timeout=10000)
        page.click('#panel [data-act="arc-back"]')
        page.wait_for_selector("#arc-text")
        assert page.input_value("#arc-text") == answer
    finally:
        ctx.close()
    assert not problems


def test_markup_from_the_chat_is_shown_as_text(browser, live_url, gm, sandbox):
    data = good()
    data["plan"][0]["title"] = f"Груз {EVIL}"
    data["questions"] = [f"Вопрос {EVIL}"]
    ctx, page, problems = make_page(browser, live_url)
    try:
        paste_and_check(page, chat_answer(data))
        page.wait_for_selector("#panel .arc-row", timeout=10000)
        assert EVIL in page.inner_text("#panel")
        page.click('#panel [data-act="arc-go"]')
        page.wait_for_selector("#panel >> text=Разбор арки загружен", timeout=10000)
        assert page.evaluate("()=>({xss:window.__xss||0,img:document.querySelectorAll('img[src=\"x\"]').length,csp:(window.__csp||[]).length})") == {"xss": 0, "img": 0, "csp": 0}
    finally:
        ctx.close()
    assert not problems


def test_nothing_overflows_on_a_phone(browser, live_url, gm, sandbox):
    data = good()
    data["plan"].append({"title": "Вне календаря с очень длинным названием " + "слово" * 30, "from": "2099-01-01", "to": "2099-01-01"})
    for width in (360, 390):
        ctx, page, problems = make_page(browser, live_url)
        try:
            page.set_viewport_size({"width": width, "height": 800})
            paste_and_check(page, chat_answer(data))
            page.wait_for_selector("#panel .arc-row", timeout=10000)
            over = page.evaluate("()=>({page:document.documentElement.scrollWidth-document.documentElement.clientWidth,"
                                 "box:[...document.querySelectorAll('#panel *')].filter(e=>e.getBoundingClientRect().right>document.documentElement.clientWidth+1).map(e=>e.className||e.tagName)})")
            assert over["page"] <= 0 and over["box"] == [], (width, over)
        finally:
            ctx.close()
        assert not problems


def test_players_have_no_such_section(browser, live_url, gm, rig, sandbox):
    ctx, page, problems = make_page(browser, live_url, 103)
    try:
        assert page.locator("#gm-arc").count() == 0 and page.locator('[data-act="arc-open"]').count() == 0
    finally:
        ctx.close()
    assert not problems
