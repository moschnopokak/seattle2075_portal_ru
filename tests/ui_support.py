"""Общие части браузерных тестов: живой сервер, Chromium, страница с cookie входа и сбором ошибок.

Фикстуры (strict_csp, live_url, browser) подключены плагином через pytest_plugins в conftest.py, а open_page импортируется.
Playwright импортируется только внутри фикстуры browser: без него обычные тесты запускаются как раньше.
"""
import os
import socket
import threading
import time

import pytest

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402
from conftest import login  # noqa: E402


@pytest.fixture(scope="module")
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
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("PORTAL_TEST_CHROMIUM") or None, args=["--no-sandbox"])
        yield b
        b.close()


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
