"""Политика безопасности содержимого (CSP) и вход через редирект Telegram."""
import hashlib
import hmac
import re
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest

from app import auth, config
from conftest import GATE

STATIC = Path(__file__).resolve().parent.parent / "static"


def test_index_has_no_inline_code():
    """Страж: пока в index.html нет inline-скриптов, стилей и обработчиков, строгий CSP работает."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "inline <script>"
    assert "<style" not in html, "inline <style>"
    assert not re.search(r"\son[a-z]+\s*=", html, re.I), "inline-обработчик события"
    assert "javascript:" not in html.lower()
    for name in re.findall(r'<script[^>]*\bsrc="/static/js/([\w.]+)"', html):
        assert (STATIC / "js" / name).is_file(), name


def test_js_files_have_no_eval_or_inline_html_handlers():
    for path in (STATIC / "js").glob("*.js"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\beval\(|new Function\(|document\.write\(", text), path.name
        assert not re.search(r"""<[a-z][^>]*\son[a-z]+=["']""", text), f"{path.name}: обработчик в разметке"


def test_default_mode_reports_only(anon):
    assert config.CSP_MODE == "report-only"
    r = anon.get("/")
    assert "frame-ancestors" in r.headers["content-security-policy"]
    assert "script-src" not in r.headers["content-security-policy"]         # ничего не блокируется
    report = r.headers["content-security-policy-report-only"]
    assert "script-src 'self' https://telegram.org;" in report and "report-uri /api/csp-report" in report


def test_enforce_mode_is_strict(anon, monkeypatch):
    monkeypatch.setattr(config, "CSP_MODE", "enforce")
    r = anon.get("/")
    csp = r.headers["content-security-policy"]
    assert "content-security-policy-report-only" not in r.headers
    script = re.search(r"script-src ([^;]*)", csp).group(1)
    assert script == "'self' https://telegram.org"                          # без unsafe-inline и unsafe-eval
    assert "unsafe-inline" not in csp.replace("style-src-attr 'unsafe-inline'", "")
    for part in ("default-src 'self'", "object-src 'none'", "base-uri 'none'", "frame-ancestors 'self'", "frame-src 'self' https://oauth.telegram.org"):
        assert part in csp, part


def test_callback_widget_mode_adds_unsafe_eval_only_there(anon, monkeypatch):
    monkeypatch.setattr(config, "CSP_MODE", "enforce")
    monkeypatch.setattr(config, "TG_WIDGET_MODE", "callback")
    assert "'unsafe-eval'" in anon.get("/").headers["content-security-policy"]
    assert anon.get("/api/config").json()["widget_mode"] == "callback"


def test_off_mode_keeps_only_frame_policy(anon, monkeypatch):
    monkeypatch.setattr(config, "CSP_MODE", "off")
    r = anon.get("/")
    assert r.headers["content-security-policy"].startswith("frame-ancestors")
    assert "content-security-policy-report-only" not in r.headers


def test_other_responses_carry_no_page_policy(anon, monkeypatch):
    monkeypatch.setattr(config, "CSP_MODE", "enforce")
    assert "content-security-policy" not in anon.get("/healthz").headers
    assert "content-security-policy" not in anon.get("/static/style.css").headers


def test_csp_report_endpoint_logs_and_limits(anon, caplog):
    body = '{"csp-report": {"violated-directive": "script-src", "blocked-uri": "https://evil.example/x.js", "document-uri": "http://t/"}}'
    with caplog.at_level("WARNING", logger="portal"):
        r = anon.post("/api/csp-report", content=body, headers={"Content-Type": "application/csp-report"})
    assert r.status_code == 204
    assert any("evil.example" in m for m in caplog.messages)
    for junk in (b"", b"not json", b"[]", b'{"csp-report": 5}', b"x" * 20000):
        assert anon.post("/api/csp-report", content=junk).status_code == 204
    from app import main
    main._csp_seen.update(minute=0, count=0)


@pytest.fixture
def bot_token(monkeypatch):
    monkeypatch.setattr(auth, "BOT_TOKEN", "123456:TESTTOKEN")


def signed(fields, token="123456:TESTTOKEN"):
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    key = hashlib.sha256(token.encode()).digest()
    return dict(fields, hash=hmac.new(key, check.encode(), hashlib.sha256).hexdigest())


def test_telegram_redirect_login_sets_session(anon, bot_token):
    query = urlencode(signed({"id": GATE, "first_name": "Г", "username": "gate", "auth_date": int(time.time())}))
    r = anon.get(f"/auth/telegram?{query}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "session=" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    assert anon.get("/api/state").json()["me"]["chars"] == ["gate"]          # cookie уже работает


def test_telegram_redirect_login_rejects_bad_data(anon, bot_token):
    good = signed({"id": GATE, "auth_date": int(time.time())})
    for params in ({**good, "id": 1}, {**good, "hash": "0" * 64}, {"id": GATE}, {},
                   signed({"id": GATE, "auth_date": int(time.time()) - 90000}),
                   signed({"id": GATE, "auth_date": "abc"})):
        r = anon.get("/auth/telegram?" + urlencode(params), follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/?auth=failed", params
        assert "set-cookie" not in r.headers
    assert anon.get("/api/state").status_code == 401


def test_public_config_exposes_widget_mode(anon):
    assert anon.get("/api/config").json()["widget_mode"] == "redirect"
