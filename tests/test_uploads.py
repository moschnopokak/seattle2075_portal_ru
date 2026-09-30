"""Картинки досье и раздатки: проверки файлов, лимиты, доступ по токену, отзыв ссылок."""
import io
import re
import time

from helpers import ok, png

HANDOUT = "<!doctype html><html><body><h1>Раздатка</h1><script>window.x=1</script></body></html>".encode()


def portrait_token(state, card_id):
    return next(c for c in state["dossier"] if c["id"] == card_id)["img"]


def test_portrait_roundtrip(gm, anon):
    data = ok(gm.post("/api/gm/dossier/n1/portrait", content=png()))
    token = portrait_token(data["state"], "n1")
    assert re.fullmatch(r"[0-9a-f]{32}", token)
    for size in ("f.webp", "t.webp"):
        r = anon.get(f"/portrait/{token}/{size}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/webp" and r.content[:4] == b"RIFF"
    assert len(anon.get(f"/portrait/{token}/f.webp").content) <= 90 * 1024
    assert len(anon.get(f"/portrait/{token}/t.webp").content) <= 10 * 1024
    # замена меняет токен, старая ссылка умирает
    data = ok(gm.post("/api/gm/dossier/n1/portrait", content=png(color=(0, 0, 200))))
    token2 = portrait_token(data["state"], "n1")
    assert token2 != token and anon.get(f"/portrait/{token}/f.webp").status_code == 404
    assert anon.get(f"/portrait/{token2}/f.webp").status_code == 200
    ok(gm.post("/api/gm/dossier/n1/portrait/delete"))
    assert anon.get(f"/portrait/{token2}/f.webp").status_code == 404


def test_portrait_bad_inputs(gm, anon):
    assert anon.get(f"/portrait/{'0' * 32}/f.webp").status_code == 404
    assert anon.get("/portrait/xyz/f.webp").status_code == 404
    data = ok(gm.post("/api/gm/dossier/n1/portrait", content=png()))
    token = portrait_token(data["state"], "n1")
    try:
        assert anon.get(f"/portrait/{token}/x.webp").status_code == 404
        for body in (b"", b"not an image", png(30, 30), b"\x89PNG\r\n\x1a\n" + b"0" * 100, b"GIF89a" + b"\0" * 20):
            assert gm.post("/api/gm/dossier/n1/portrait", content=body).status_code == 400, body[:12]
        assert gm.post("/api/gm/dossier/n1/portrait", content=b"\0" * (9 * 1024 * 1024)).status_code == 413
        assert gm.post("/api/gm/dossier/нет/portrait", content=png()).status_code == 404
        # после неудачных попыток прежняя картинка цела
        assert anon.get(f"/portrait/{token}/f.webp").status_code == 200
    finally:
        gm.post("/api/gm/dossier/n1/portrait/delete")


def test_portrait_decompression_bomb_is_rejected_fast(gm):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("L", (20000, 20000), 0).save(buf, "PNG")  # 400 Мпикс, сжимается до килобайт
    started = time.time()
    r = gm.post("/api/gm/dossier/n1/portrait", content=buf.getvalue())
    assert r.status_code == 400 and time.time() - started < 10


def test_portrait_link_revoked_when_card_is_hidden(gm, anon):
    data = ok(gm.post("/api/gm/dossier/n1/portrait", content=png()))
    token = portrait_token(data["state"], "n1")
    card = next(c for c in data["state"]["dossier"] if c["id"] == "n1")
    try:
        # сужение «стол» → «знают только Риг»: ссылка меняется, картинка доступна по новой
        body = dict(card, vis="знают", known=["rig"])
        data = ok(gm.post("/api/gm/items/dossier", json=body))
        new = portrait_token(data["state"], "n1")
        assert new != token and anon.get(f"/portrait/{token}/f.webp").status_code == 404
        assert anon.get(f"/portrait/{new}/f.webp").status_code == 200
        # расширение доступа токен не меняет
        data = ok(gm.post("/api/gm/items/dossier", json=dict(card, vis="стол", known=[])))
        assert portrait_token(data["state"], "n1") == new
        # скрытие от всех
        data = ok(gm.post("/api/gm/items/dossier", json=dict(card, vis="мастер", known=[])))
        assert anon.get(f"/portrait/{new}/f.webp").status_code == 404
    finally:
        gm.post("/api/gm/dossier/n1/portrait/delete")
        gm.post("/api/gm/items/dossier", json=dict(card, vis="стол", known=[], img=""))


def make_handout(gm, **kw):
    body = {"title": "Письмо", "date": "2075-08-01", "vis": "знают", "known": ["rig"], "note": "N", "gm_note": "СЕКРЕТ-заметка раздатки"}
    body.update(kw)
    data = ok(gm.post("/api/gm/items/handouts", json=body))
    return next(h for h in data["state"]["handouts"] if h["title"] == body["title"])


def test_handout_flow_and_visibility(gm, rig, hag, anon):
    h = make_handout(gm)
    hid = h["id"]
    try:
        assert not rig.get("/api/state").json()["handouts"]          # без файла игрок не видит
        data = ok(gm.post(f"/api/gm/handouts/{hid}/file", content=HANDOUT, headers={"X-File-Name": "%D0%BF.html"}))
        token = next(x for x in data["state"]["handouts"] if x["id"] == hid)["file"]
        rig_state = rig.get("/api/state").json()
        assert [x["id"] for x in rig_state["handouts"]] == [hid]
        assert "СЕКРЕТ" not in str(rig_state["handouts"]) and "gm_note" not in rig_state["handouts"][0]
        assert not hag.get("/api/state").json()["handouts"]
        packed = anon.get(f"/handout/{token}/view", headers={"Accept-Encoding": "gzip"})
        plain = anon.get(f"/handout/{token}/view", headers={"Accept-Encoding": "identity"})
        assert packed.status_code == plain.status_code == 200 and plain.content == HANDOUT
        csp = plain.headers["content-security-policy"]
        assert csp.startswith("sandbox") and "allow-same-origin" not in csp
        assert "text/html" in plain.headers["content-type"]
    finally:
        gm.post(f"/api/gm/items/handouts/{hid}/delete")
    assert anon.get(f"/handout/{token}/view").status_code == 404


def test_handout_bad_files(gm):
    h = make_handout(gm, title="Плохие файлы")
    try:
        url = f"/api/gm/handouts/{h['id']}/file"
        assert gm.post(url, content=b"").status_code == 400
        assert gm.post(url, content=b"\x00\x01\x02binary").status_code == 400
        assert gm.post(url, content="привет".encode("cp1251")).status_code == 400
        assert gm.post(url, content=b"plain text without markup").status_code == 400
        assert gm.post(url, content=b"<p>" + b"x" * (16 * 1024 * 1024)).status_code == 413
        assert gm.post("/api/gm/handouts/нет/file", content=HANDOUT).status_code == 404
    finally:
        gm.post(f"/api/gm/items/handouts/{h['id']}/delete")


def test_handout_link_revoked_when_access_is_narrowed(gm, anon):
    h = make_handout(gm, title="Узкий доступ", vis="стол", known=[])
    hid = h["id"]
    try:
        data = ok(gm.post(f"/api/gm/handouts/{hid}/file", content=HANDOUT))
        token = next(x for x in data["state"]["handouts"] if x["id"] == hid)["file"]
        assert anon.get(f"/handout/{token}/view").status_code == 200
        card = next(x for x in data["state"]["handouts"] if x["id"] == hid)
        # «стол» → «только Риг»: кто потерял доступ, ссылку не открывает
        data = ok(gm.post("/api/gm/items/handouts", json=dict(card, vis="знают", known=["rig"])))
        new = next(x for x in data["state"]["handouts"] if x["id"] == hid)["file"]
        assert new != token
        assert anon.get(f"/handout/{token}/view").status_code == 404
        assert anon.get(f"/handout/{new}/view").status_code == 200
        # скрытие от всех
        data = ok(gm.post("/api/gm/items/handouts", json=dict(card, vis="мастер", known=[])))
        assert anon.get(f"/handout/{new}/view").status_code == 404
        # возврат доступа выдаёт новую ссылку, файл при этом не потерян
        data = ok(gm.post("/api/gm/items/handouts", json=dict(card, vis="стол", known=[])))
        final = next(x for x in data["state"]["handouts"] if x["id"] == hid)["file"]
        assert anon.get(f"/handout/{final}/view").status_code == 200
    finally:
        gm.post(f"/api/gm/items/handouts/{hid}/delete")


def test_handout_token_format_checked(anon):
    for token in ("z" * 32, "abc", "0" * 31, "../" + "0" * 29):
        assert anon.get(f"/handout/{token}/view").status_code == 404
