"""Вход: подписи Telegram, токены сессии, режим разработки."""
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from urllib.parse import urlencode

import pytest

from app import auth, config
from conftest import GATE, GM, RIG, STRANGER, login

TEST_TOKEN = "123456:TESTTOKEN"


@pytest.fixture
def bot_token(monkeypatch):
    monkeypatch.setattr(auth, "BOT_TOKEN", TEST_TOKEN)


def widget(fields, token=TEST_TOKEN):
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    key = hashlib.sha256(token.encode()).digest()
    return dict(fields, hash=hmac.new(key, check.encode(), hashlib.sha256).hexdigest())


def test_anonymous_gets_401(anon):
    assert anon.get("/api/state").status_code == 401


def test_unlisted_user_gets_403_with_own_id(anon):
    c = login(STRANGER)
    r = c.get("/api/state")
    assert r.status_code == 403
    assert r.json()["detail"]["tg_id"] == STRANGER


def test_tampered_tokens_rejected(anon):
    good = login(GATE).cookies["session"]
    body, sig = good.rsplit(".", 1)
    for bad in (good[:-2] + "aa", "x." + sig, body + ".", "garbage", body + "." + "0" * 64):
        r = anon.get("/api/state", headers={"Authorization": "Bearer " + bad}, cookies={})
        assert r.status_code == 401, bad
    payload = json.dumps({"u": GM, "n": "", "e": int(time.time()) + 999}, separators=(",", ":")).encode()
    forged = base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + sig
    assert anon.get("/api/state", headers={"Authorization": "Bearer " + forged}).status_code == 401


def test_expired_token_rejected(anon):
    payload = json.dumps({"u": GM, "n": "", "e": int(time.time()) - 10}, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = hmac.new(config.SECRET_KEY, body.encode(), hashlib.sha256).hexdigest()
    assert anon.get("/api/state", headers={"Authorization": f"Bearer {body}.{sig}"}).status_code == 401


def test_bearer_header_works(anon):
    token = login(RIG).cookies["session"]
    r = anon.get("/api/state", headers={"Authorization": "Bearer " + token})
    assert r.status_code == 200 and r.json()["me"]["chars"] == ["rig"]


def test_widget_login(anon, bot_token):
    fields = {"id": GATE, "first_name": "G", "username": "gate", "auth_date": int(time.time())}
    r = anon.post("/api/auth/widget", json=widget(fields))
    assert r.status_code == 200 and r.json()["listed"] is True
    assert anon.post("/api/auth/widget", json=widget(fields, "999:OTHER")).status_code == 401
    old = dict(fields, auth_date=int(time.time()) - 90000)
    assert anon.post("/api/auth/widget", json=widget(old)).status_code == 401
    assert anon.post("/api/auth/widget", json={"id": GM}).status_code == 401
    forged = widget(fields)
    forged["id"] = GM
    assert anon.post("/api/auth/widget", json=forged).status_code == 401


@pytest.mark.parametrize("data", [
    {"hash": "x", "auth_date": "abc", "id": "1"},
    {"hash": "ф" * 64, "auth_date": "1", "id": "1"},   # не-ASCII в подписи
    {"id": "abc", "hash": "00"},
    {"hash": ["a"], "id": 1},
    {},
])
def test_widget_garbage_is_401_not_500(anon, bot_token, data):
    assert anon.post("/api/auth/widget", json=data).status_code == 401


def test_widget_signed_but_nonnumeric_fields(anon, bot_token):
    """Подпись верна, но auth_date или id не числа: отказ, а не ошибка сервера."""
    for fields in ({"id": GATE, "auth_date": "abc"}, {"id": "abc", "auth_date": int(time.time())}, {"auth_date": int(time.time())}):
        r = anon.post("/api/auth/widget", json=widget(fields))
        assert r.status_code == 401, (fields, r.status_code)


def test_webapp_login(anon, bot_token):
    user = json.dumps({"id": RIG, "first_name": "R", "username": "rig"}, separators=(",", ":"))
    fields = {"auth_date": str(int(time.time())), "user": user, "query_id": "AAA"}
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    init = urlencode(dict(fields, hash=hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()))
    assert anon.post("/api/auth/webapp", json={"init_data": init}).status_code == 200
    assert anon.post("/api/auth/webapp", json={"init_data": init + "x"}).status_code == 401
    for bad in ("", "a=b", "hash=zz", 5, None, ["x"]):
        assert anon.post("/api/auth/webapp", json={"init_data": bad}).status_code == 401, bad


def test_dev_login_404_when_disabled(anon, monkeypatch):
    monkeypatch.setattr(config, "DEV_LOGIN", False)
    assert anon.post("/api/auth/dev", json={"tg_id": GM}).status_code == 404
    assert anon.get("/api/config").json()["dev_login"] is False


def test_dev_login_ignored_when_bot_token_is_set(tmp_path):
    """DEV_LOGIN=1 вместе с BOT_TOKEN: рабочий сервер, вход без Telegram выключается сам."""
    env = dict(os.environ, DATA_DIR=str(tmp_path), DEV_LOGIN="1", BOT_TOKEN="1:x")
    code = "from app import config; print(config.DEV_LOGIN, config.DEV_LOGIN_REQUESTED)"
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout.split()
    assert out == ["False", "True"]
    env.pop("BOT_TOKEN")
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout.split()
    assert out == ["True", "True"]


def test_secret_key_file_is_private(tmp_root):
    mode = (tmp_root / "data" / "secret.key").stat().st_mode & 0o777
    assert mode == 0o600


def test_logout_clears_cookie(anon):
    c = login(GATE)
    r = c.post("/api/auth/logout")
    assert r.status_code == 200 and "session=" in r.headers["set-cookie"]
