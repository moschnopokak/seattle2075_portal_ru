"""Проверки в настоящем браузере: чужой текст не исполняется, страницы открываются без ошибок, раздатка изолирована.

Запуск: pytest -m browser (нужны requirements-dev.txt и установленный Chromium: playwright install chromium).
Если Chromium лежит в нестандартном месте, укажите путь в PORTAL_TEST_CHROMIUM.
"""
import os
import socket
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app.main import app  # noqa: E402
from conftest import login  # noqa: E402
from helpers import entry, ok  # noqa: E402

pytestmark = pytest.mark.browser

P1 = "<img src=x onerror=__xss=1>"
P2 = '"><img src=x onerror=__xss=1>'
P3 = "'><svg/onload=__xss=1>"
P4 = "</script><img src=x onerror=__xss=1>"
P5 = '" onmouseover="__xss=1" x="'

PROBE = ("<!doctype html><html><body><h1>Проба</h1><script>var out={};"
         "try{out.parentDoc=!!parent.document.body}catch(e){out.parentDoc='blocked'}"
         "try{out.ls=String(localStorage.length)}catch(e){out.ls='blocked'}"
         "try{out.cookie=document.cookie||'empty'}catch(e){out.cookie='blocked'}"
         "fetch('/api/state',{credentials:'include'}).then(function(r){out.fetch=r.status})"
         ".catch(function(e){out.fetch='blocked'}).then(function(){parent.postMessage('HO:'+JSON.stringify(out),'*')});"
         "</script></body></html>").encode()

CHECK = ("()=>({xss:window.__xss||0,img:document.querySelectorAll('img[src=\"x\"]').length,"
         "ev:document.body.querySelectorAll('[onerror],[onload],[onmouseover]').length})")
CLOSE = "()=>{if(!document.getElementById('overlay').hidden)closePanel()}"


@pytest.fixture(scope="module", autouse=True)
def strict_csp():
    """Браузерные тесты идут при включённом строгом CSP: любое нарушение (inline-код, чужой хост) станет ошибкой."""
    from app import config
    mp = pytest.MonkeyPatch()
    mp.setattr(config, "CSP_MODE", "enforce")
    yield
    mp.undo()


@pytest.fixture(scope="module")
def live_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    assert server.started, "сервер для браузерных тестов не запустился"
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("PORTAL_TEST_CHROMIUM") or None, args=["--no-sandbox"])
        yield b
        b.close()


@pytest.fixture
def payloads(gm, gate, rig, sandbox):
    """Вредные строки во всех текстовых полях всех разделов. Возвращает идентификаторы созданного."""
    ids = {}
    data = ok(gm.post("/api/gm/items/places", json={"name": P2, "type": "other", "x": 5000, "y": 5000, "vis": "стол",
                                                   "note": P1 + P3, "gm_note": P4}))
    ids["place"] = next(p["id"] for p in data["state"]["places"] if p["name"] == P2)
    data = ok(gate.post("/api/entries", json=entry(title=P2, char="gate", who=["rig"], where=P1, cond=P4, goal=P2,
                                                   place=ids["place"], **{"to": "2075-08-06"})))
    ids["entry"] = next(e["id"] for e in data["state"]["entries"] if e["title"] == P2)
    ok(rig.post(f"/api/entries/{ids['entry']}/act", json={"act": "ans", "v": "да", "char": "rig"}))
    for who, char, text in ((gate, "gate", P1), (rig, "rig", P2 + P3), (gm, None, P5)):
        ok(who.post(f"/api/entries/{ids['entry']}/messages", json={"char": char, "text": text}))
    data = ok(gate.post("/api/entries", json=entry(title=P1, char="gate", who=["gate"], open=True)))
    ids["open"] = next(e["id"] for e in data["state"]["entries"] if e["title"] == P1)
    data = ok(rig.post("/api/entries", json=entry(type="grow", title=P3, char="rig", who=["rig"], goal=P2, effect="2075-08-05")))
    ids["grow"] = next(e["id"] for e in data["state"]["entries"] if e["title"] == P3)
    data = ok(gm.post("/api/gm/items/past", json={"title": P2, "from": "2075-07-20", "to": "2075-07-20", "note": P1,
                                                 "gm_note": P4, "session": P3}))
    ids["past"] = next(p["id"] for p in data["state"]["past"] if p["title"] == P2)
    data = ok(gm.post("/api/gm/items/plan", json={"title": P2, "from": "2075-09-10", "to": "2075-09-11", "note": P1,
                                                 "cover": {"title": P1, "note": P2, "who": ["rig", "gate"]}}))
    ids["plan"] = next(p["id"] for p in data["state"]["plan"] if p["title"] == P2)
    data = ok(gm.post("/api/gm/items/clocks", json={"title": P2, "note": P1, "when": "2075-10-01"}))
    ids["clock"] = next(c["id"] for c in data["state"]["clocks"] if c["title"] == P2)
    data = ok(gm.post("/api/gm/items/rhythm", json={"title": P2, "note": P1, "wd": [2], "vis": "стол"}))
    ids["rhythm"] = next(c["id"] for c in data["state"]["rhythm"] if c["title"] == P2)
    data = ok(gm.post("/api/gm/items/windows", json={"name": P2, "gm": P1, "from": "2075-12-30", "to": "2075-12-31"}))
    ids["window"] = next(w["id"] for w in data["state"]["windows"] if w["name"] == P2)
    data = ok(gm.post("/api/gm/items/dossier", json={
        "name": P2, "alias": P1, "type": "person", "role": P4, "stance": "ally", "org": P3, "vis": "стол", "met": ["rig"],
        "last_date": "2075-08-01", "last_place": ids["place"], "last_note": P2,
        "facts": [{"text": P1, "vis": "стол", "truth": P2, "date": "2075-08-01"}], "gm_note": P4}))
    ids["dossier"] = next(c["id"] for c in data["state"]["dossier"] if c["name"] == P2)
    data = ok(gm.post("/api/gm/items/handouts", json={"title": P2, "date": "2075-08-01", "vis": "стол", "note": P1,
                                                     "gm_note": P4, "place": ids["place"]}))
    ids["handout"] = next(h["id"] for h in data["state"]["handouts"] if h["title"] == P2)
    ok(gm.post(f"/api/gm/handouts/{ids['handout']}/file", content=PROBE, headers={"X-File-Name": "probe.html"}))
    ok(gm.post("/api/gm/district/downtown", json={"text": P1 + P2, "gm_text": P4}))
    return ids


def open_page(browser, live_url, tg_id, problems):
    ctx = browser.new_context(viewport={"width": 1100, "height": 800})

    def only_local(route):
        if route.request.url.startswith(live_url):
            route.continue_()
        else:  # внешние ресурсы (Telegram) в тестах не нужны: отдаём пустышку
            route.fulfill(status=200, body="", content_type="text/plain")

    ctx.route("**/*", only_local)
    ctx.add_cookies([{"name": "session", "value": login(tg_id).cookies["session"], "url": live_url}])
    page = ctx.new_page()
    page.recorded = []
    page.on("request", lambda r: page.recorded.append(r.url))
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}")
            if m.type == "error" and "blocked by CORS" not in m.text and "Failed to load resource" not in m.text else None)
    page.on("dialog", lambda d: (problems.append(f"DIALOG: {d.message}"), d.dismiss()))
    page.add_init_script("window.addEventListener('message',e=>{if(typeof e.data==='string'&&e.data.startsWith('HO:'))window.__ho=e.data});"
                         "document.addEventListener('securitypolicyviolation',e=>{(window.__csp=window.__csp||[]).push(e.violatedDirective+' '+e.blockedURI)})")
    page.goto(live_url + "/", wait_until="domcontentloaded")
    page.wait_for_selector("#nav button", timeout=15000)
    return ctx, page


def visit_everything(page, ids, view, problems, label):
    def check(what):
        n = page.evaluate(CHECK)
        if n["xss"] or n["img"] or n["ev"]:
            problems.append(f"XSS {label}/{view}/{what}: {n}")
        for v in page.evaluate("()=>window.__csp||[]"):
            problems.append(f"CSP {label}/{view}/{what}: {v}")

    for section in ("now", "cal", "chron", "dossier", "handouts", "map", "gm"):
        if section == "gm" and view != "gm":
            continue
        page.evaluate("s=>{UI.section=s;render();}", section)
        page.wait_for_timeout(700 if section == "map" else 150)
        if section == "cal":
            for mode in ("lanes", "week", "month", "stage"):
                page.evaluate("m=>{UI.cal=m;render();}", mode)
        check(section)
    keys = [f"e:{ids['entry']}", f"e:{ids['open']}", f"e:{ids['grow']}", f"p:{ids['past']}", f"n:{ids['dossier']}",
            f"m:{ids['place']}", "d:downtown", f"h:{ids['handout']}", f"b:{ids['plan']}", f"r:{ids['rhythm']}"]
    if view == "gm":
        keys += [f"g:{ids['plan']}", f"c:{ids['clock']}"]
    for key in keys:
        page.evaluate("s=>{UI.section=s.startsWith('n:')?'dossier':s.startsWith('h:')?'handouts':s.startsWith('m:')?'map':'now';}", key)
        page.evaluate("k=>openDetail(k)", key)
        page.wait_for_timeout(120)
        check(key)
        page.evaluate(CLOSE)
    if view == "gm":
        forms = [("openItemForm", ["dossier", ids["dossier"]]), ("openItemForm", ["places", ids["place"]]),
                 ("openItemForm", ["clocks", ids["clock"]]), ("openItemForm", ["plan", ids["plan"]]),
                 ("openItemForm", ["past", ids["past"]]), ("openItemForm", ["rhythm", ids["rhythm"]]),
                 ("openItemForm", ["windows", ids["window"]]), ("openHandoutForm", [ids["handout"]]),
                 ("openDistrictForm", ["downtown"])]
        for fn, args in forms:
            page.evaluate("([f,a])=>window[f]?window[f](...a):eval(f)(...a)", [fn, args])
            page.wait_for_timeout(100)
            check(fn + str(args))
            page.evaluate(CLOSE)
        page.evaluate("id=>{const e=S.entries.find(x=>x.id===id);openForm(e.from,e)}", ids["entry"])
        page.wait_for_timeout(100)
        check("openForm(entry)")
        page.evaluate(CLOSE)


def test_hostile_text_is_never_executed(browser, live_url, payloads):
    problems = []
    for name, tg, views in (("gm", 1, ("gm", "rig", "gate")), ("rig", 103, ("self",)), ("max", 101, ("self",))):
        ctx, page = open_page(browser, live_url, tg, problems)
        for view in views:
            if view != "self":
                page.evaluate("v=>{V=v;render();}", view)
            visit_everything(page, payloads, view, problems, name)
        ctx.close()
    assert not problems, "\n".join(problems[:20])


def test_hostile_text_is_shown_as_plain_text(browser, live_url, payloads):
    problems = []
    ctx, page = open_page(browser, live_url, 103, problems)
    page.evaluate("k=>openDetail(k)", f"e:{payloads['entry']}")
    page.wait_for_timeout(200)
    text = page.inner_text("#panel")
    assert P1 in text and text.count("onerror") >= 5      # название, где, условия, цель и сообщения чата видны буквами
    page.evaluate(CLOSE)
    page.evaluate("()=>{UI.section='dossier';render()}")
    page.evaluate("k=>openDetail(k)", f"n:{payloads['dossier']}")
    page.wait_for_timeout(200)
    assert P1 in page.inner_text("#panel")
    ctx.close()
    assert not problems, problems


def test_handout_runs_in_isolated_sandbox(browser, live_url, payloads):
    problems = []
    ctx, page = open_page(browser, live_url, 1, problems)
    page.evaluate("()=>{UI.section='handouts';render()}")
    page.evaluate("k=>openDetail(k)", f"h:{payloads['handout']}")
    for _ in range(40):
        if page.evaluate("window.__ho||null"):
            break
        page.wait_for_timeout(100)
    probe = page.evaluate("window.__ho||null")
    ctx.close()
    assert probe, "раздатка не прислала результат проверки"
    assert probe == 'HO:{"parentDoc":"blocked","ls":"blocked","cookie":"blocked","fetch":"blocked"}', probe
    assert not problems, problems


def test_fonts_come_from_our_server(browser, live_url):
    problems = []
    ctx, page = open_page(browser, live_url, 1, problems)
    page.evaluate("()=>document.fonts.ready")
    page.wait_for_timeout(300)
    loaded = page.evaluate("()=>[...document.fonts].filter(f=>f.status==='loaded').map(f=>f.family.replace(/['\"]/g,'')+' '+f.weight+' '+f.style)")
    assert "Jost 400 normal" in loaded and "Jost 300 normal" in loaded, loaded    # кириллица основного и крупного текста
    assert page.evaluate("()=>document.fonts.check('400 16px Jost','Сегодня')")
    outside = [u for u in page.recorded if not u.startswith(live_url)]
    assert all("telegram.org" in u for u in outside), outside                      # наружу ходит только скрипт Telegram
    assert not any("font" in u and not u.startswith(live_url) for u in page.recorded)
    ctx.close()
    assert not problems, problems
