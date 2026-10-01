"""Ссылки [[Имя]] в браузере: открывают карточки, не выдают скрытые, не исполняют чужой текст, показывают упоминания."""
import pytest

from helpers import entry, ok, remove
from ui_support import open_page

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("strict_csp")]

EVIL = "<img src=x onerror=__xss=1>"
GOAL = (f"Поговорить с [[Ёжик Видимый]], с [[Секретная Особа]], с [[Нет Такого]] и с [[колючка|Колючкой]] {EVIL} "
        f"и ещё [[Ёжик Видимый|{EVIL}]] и [[{EVIL}]]")
TITLES = {"Ёжик Видимый", "Секретная Особа"}


def clean_trash(gm):
    for t in ok(gm.get("/api/gm/trash"))["items"]:
        if t["title"] in TITLES or t["title"] in ("Дело со ссылками", "Тайная встреча со ссылкой"):
            gm.post(f"/api/gm/trash/{t['id']}/purge")


@pytest.fixture
def scene(gm, gate, rig, hag):
    cards = {}
    for name, vis, alias in (("Ёжик Видимый", "стол", "Колючка"), ("Секретная Особа", "мастер", "")):
        data = ok(gm.post("/api/gm/items/dossier", json={"name": name, "alias": alias, "vis": vis, "role": f"Роль: [[Ёжик Видимый]] знает {name}"}))
        cards[name] = next(c["id"] for c in data["state"]["dossier"] if c["name"] == name)
    shared = ok(gate.post("/api/entries", json=entry(char="gate", title="Дело со ссылками", who=["rig"], goal=GOAL)))
    eid = next(e["id"] for e in shared["state"]["entries"] if e["title"] == "Дело со ссылками")
    ok(rig.post(f"/api/entries/{eid}/messages", json={"char": "rig", "text": "Идём к [[Ёжик Видимый]]!"}))
    private = ok(hag.post("/api/entries", json=entry(char="hagane", title="Тайная встреча со ссылкой", who=["elijah"], vis="лично", goal="[[Ёжик Видимый]]")))
    pid = next(e["id"] for e in private["state"]["entries"] if e["title"] == "Тайная встреча со ссылкой")
    yield {"cards": cards, "entry": eid}
    remove(gm, eid)
    remove(gm, pid)
    for cid in cards.values():
        gm.post(f"/api/gm/items/dossier/{cid}/delete")
    clean_trash(gm)


def make_page(browser, live_url, tg_id, problems):
    ctx, page = open_page(browser, live_url, tg_id, problems)
    page.evaluate("async()=>{const r=await fetch('/api/state',{credentials:'same-origin'});applyState(await r.json());}")
    return ctx, page


@pytest.fixture
def player(browser, live_url, scene):
    problems = []
    ctx, page = make_page(browser, live_url, 102, problems)           # Гейт
    yield page
    ctx.close()
    assert not problems, problems


@pytest.fixture
def master(browser, live_url, scene):
    problems = []
    ctx, page = make_page(browser, live_url, 1, problems)
    yield page
    ctx.close()
    assert not problems, problems


def open_entry(page, eid):
    page.evaluate("id=>{UI.section='cal';render();openDetail('e:'+id)}", eid)
    page.wait_for_selector("#panel .goal", timeout=10000)


def check_clean(page):
    n = page.evaluate("()=>({xss:window.__xss||0,img:document.querySelectorAll('img[src=\"x\"]').length,csp:(window.__csp||[]).length})")
    assert n == {"xss": 0, "img": 0, "csp": 0}, n


def test_player_gets_links_only_for_cards_he_sees(player, scene):
    open_entry(player, scene["entry"])
    goal = player.locator("#panel .goal")
    links = goal.locator(".dlink")
    assert links.count() == 3 and links.nth(0).inner_text() == "Ёжик Видимый" and links.nth(1).inner_text() == "Колючкой"      # имя и позывной
    assert links.nth(2).inner_text() == EVIL                                              # подпись со вредной разметкой выведена буквами
    assert goal.locator(".dlink-missing").count() == 0                                   # игроку неработающую ссылку не подсвечиваем
    text = goal.inner_text()
    assert "Секретная Особа" in text and "Нет Такого" in text and "[[" not in text       # скрытая и несуществующая выглядят одинаково: простое имя
    assert EVIL in text                                                                   # чужая разметка выводится буквами
    check_clean(player)


def test_link_opens_the_card_and_the_card_lists_mentions(player, scene):
    open_entry(player, scene["entry"])
    player.locator("#panel .goal .dlink").first.click()
    player.wait_for_function("()=>document.querySelector('#panel h2')&&document.querySelector('#panel h2').textContent.includes('Ёжик Видимый')", timeout=10000)
    panel = player.inner_text("#panel")
    assert "Упоминается" in panel and "Дело со ссылками" in panel
    assert "Тайная встреча" not in panel                                                  # личная запись других игроков не видна и не упомянута
    assert player.locator("#panel .dlink").count() >= 1                                   # в роли карточки тоже ссылка
    player.locator('#panel .mentions [data-open^="e:"]').first.click()                    # из упоминания обратно в запись
    player.wait_for_selector("#panel .goal", timeout=10000)
    check_clean(player)


def test_chat_message_links_work(player, scene):
    open_entry(player, scene["entry"])
    chat = player.locator("#panel .chat .msg p .dlink")
    assert chat.count() == 1 and chat.first.inner_text() == "Ёжик Видимый"


def test_master_sees_hidden_cards_and_marks_broken_links(master, scene):
    open_entry(master, scene["entry"])
    goal = master.locator("#panel .goal")
    assert goal.locator(".dlink").count() == 4                                            # включая карточку, скрытую от игроков
    missing = goal.locator(".dlink-missing")
    assert missing.count() == 2 and missing.first.inner_text() == "Нет Такого" and missing.nth(1).inner_text() == EVIL
    assert "Карточки с таким именем нет" in missing.first.get_attribute("title")
    check_clean(master)


def test_master_sees_both_private_and_shared_mentions(master, scene):
    master.evaluate("id=>openDossier(id)", scene["cards"]["Ёжик Видимый"])
    master.wait_for_selector("#panel .mentions", timeout=10000)
    panel = master.inner_text("#panel .mentions")
    assert "Дело со ссылками" in panel and "Тайная встреча со ссылкой" in panel
