"""Кто что может: игрок не управляет порталом, аноним не входит никуда."""
import pytest

GM_POSTS = [
    ("/api/gm/time", {"shift": 1}),
    ("/api/gm/plan/g1/played", None),
    ("/api/gm/items/plan", {"title": "x", "from": "2075-08-02"}),
    ("/api/gm/items/clocks", {"title": "x"}),
    ("/api/gm/items/dossier/n1/delete", None),
    ("/api/gm/district/downtown", {"text": "x"}),
    ("/api/gm/dossier/n1/portrait", None),
    ("/api/gm/dossier/n1/portrait/delete", None),
    ("/api/gm/handouts/h1/file", None),
]


def post(client, url, body):
    return client.post(url, json=body) if body is not None else client.post(url, content=b"")


@pytest.mark.parametrize("url,body", GM_POSTS)
def test_players_cannot_use_gm_endpoints(players, url, body):
    for name, c in players.items():
        r = post(c, url, body)
        assert r.status_code == 403, (name, url, r.status_code, r.text[:100])


@pytest.mark.parametrize("url,body", GM_POSTS)
def test_anonymous_cannot_use_gm_endpoints(anon, url, body):
    assert post(anon, url, body).status_code == 401


def test_player_without_characters_cannot_write(started):
    from conftest import NOCHAR, login
    from helpers import entry
    c = login(NOCHAR)
    r = c.post("/api/entries", json=entry(char="rig", who=["rig"]))
    assert r.status_code == 403
    assert c.get("/api/state").json()["me"]["chars"] == []


def test_player_cannot_act_as_foreign_character(gate):
    from helpers import entry
    assert gate.post("/api/entries", json=entry(char="rig", who=["gate"])).status_code == 403
    assert gate.post("/api/entries", json=entry(char="gm", who=["gate"])).status_code == 403


def test_unknown_routes_and_private_paths_are_404(anon):
    for path in ("/docs", "/openapi.json", "/redoc", "/static/../app/main.py", "/static/%2e%2e/app/config.py",
                 "/data/portal.db", "/config/players.toml", "/app/config.py"):
        assert anon.get(path).status_code in (404, 400), path


def test_security_headers(anon):
    r = anon.get("/")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "same-origin"
    # страницу нельзя встроить на чужой сайт, но веб-версии Telegram могут
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'self'" in csp and "https://*.telegram.org" in csp
    assert "x-frame-options" not in r.headers


def test_handout_keeps_its_own_stricter_policy(gm, anon):
    from helpers import ok
    body = {"title": "Заголовки", "date": "2075-08-01", "vis": "стол"}
    h = next(x for x in ok(gm.post("/api/gm/items/handouts", json=body))["state"]["handouts"] if x["title"] == "Заголовки")
    try:
        data = ok(gm.post(f"/api/gm/handouts/{h['id']}/file", content="<p>x</p>".encode()))
        token = next(x for x in data["state"]["handouts"] if x["id"] == h["id"])["file"]
        csp = anon.get(f"/handout/{token}/view").headers["content-security-policy"]
        assert csp.startswith("sandbox") and "telegram.org" not in csp   # общий заголовок ему не подменяется
    finally:
        gm.post(f"/api/gm/items/handouts/{h['id']}/delete")


def test_fonts_are_served_locally_and_cached(anon):
    page = anon.get("/").text
    assert "fonts.googleapis.com" not in page and "fonts.gstatic.com" not in page
    css = anon.get("/static/vendor/fonts/fonts.css")
    assert css.status_code == 200 and "Jost" in css.text and "PT Serif" in css.text
    assert css.headers["cache-control"] == "public, max-age=2592000"
    names = set(__import__("re").findall(r"url\(\./([\w-]+\.woff2)\)", css.text))
    assert len(names) == 18
    for name in names:
        r = anon.get(f"/static/vendor/fonts/{name}")
        assert r.status_code == 200 and r.content[:4] == b"wOF2", name
    # остальная статика проверяется при каждой загрузке
    assert anon.get("/static/index.html").headers["cache-control"] == "no-cache"


def test_healthz_reports_version(anon):
    r = anon.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["version"]
