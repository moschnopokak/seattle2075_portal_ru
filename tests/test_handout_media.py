"""Раздатки-файлы: картинки, PDF и аудио. Тип по содержимому, перекодирование картинок, выдача с Range, лимиты, миграция."""
import io
import os
import sqlite3
import subprocess
import sys
from urllib.parse import quote

import pytest
from PIL import Image

from app import db, handouts
from helpers import ok
from media import (FLAC, HTML, M4A, MP3, MP3_RAW, OGG, PDF, WEBM, gif_animated, jpeg_with_exif, png_bytes, wav_bytes,
                   webp_bytes)


# ---------------------------------------------------------------- вспомогательное

@pytest.fixture
def hid(gm):
    data = ok(gm.post("/api/gm/items/handouts", json={"title": "Файловая раздатка", "date": "2075-08-01", "vis": "стол", "known": [], "note": "N", "gm_note": "СЕКРЕТ-заметка"}))
    item = next(h for h in data["state"]["handouts"] if h["title"] == "Файловая раздатка")
    yield item["id"]
    gm.post(f"/api/gm/items/handouts/{item['id']}/delete")
    for t in ok(gm.get("/api/gm/trash"))["items"]:
        if t["title"] == "Файловая раздатка":
            gm.post(f"/api/gm/trash/{t['id']}/purge")


def upload(gm, hid, raw, name="файл"):
    return gm.post(f"/api/gm/handouts/{hid}/file", content=raw, headers={"X-File-Name": quote(name)})      # как это делает страница


def card(state, hid):
    return next(h for h in state["handouts"] if h["id"] == hid)


def put(gm, hid, raw, name="файл"):
    return card(ok(upload(gm, hid, raw, name))["state"], hid)


# ---------------------------------------------------------------- определение типа

@pytest.mark.parametrize("raw,expected", [
    (png_bytes(), ("image", "image/png")), (jpeg_with_exif(), ("image", "image/jpeg")), (gif_animated(), ("image", "image/gif")),
    (webp_bytes(), ("image", "image/webp")), (PDF, ("pdf", "application/pdf")), (b"\xef\xbb\xbf\n" + PDF, ("pdf", "application/pdf")),
    (MP3, ("audio", "audio/mpeg")), (MP3_RAW, ("audio", "audio/mpeg")), (OGG, ("audio", "audio/ogg")), (wav_bytes(), ("audio", "audio/wav")),
    (FLAC, ("audio", "audio/flac")), (M4A, ("audio", "audio/mp4")), (WEBM, ("audio", "audio/webm")),
    (HTML, None), (b"plain text", None), (b"", None), (b"\xff", None), (b"\xff\xfb", None),
])
def test_type_is_detected_by_content(raw, expected):
    assert handouts.sniff(raw) == expected


def test_extension_and_declared_type_do_not_matter(gm, hid):
    h = put(gm, hid, png_bytes(), "это_html.html")
    assert h["kind"] == "image"
    h = put(gm, hid, HTML, "картинка.png")
    assert h["kind"] == "html"


def test_not_every_ff_is_mp3():
    assert handouts.sniff(b"\xff\xf1\x50\x80" + b"\x00" * 100) is None            # AAC ADTS: слой 0, это не MP3
    assert handouts.sniff(b"\xff\xfb\xf0\x00" + b"\x00" * 100) is None            # индекс битрейта 15 недопустим
    assert handouts.sniff(b"\xff\xfb\x9c\x00" + b"\x00" * 100) is None            # индекс частоты 3 недопустим


# ---------------------------------------------------------------- загрузка каждого вида

@pytest.mark.parametrize("raw,kind,mime", [
    (png_bytes(), "image", "image/png"), (gif_animated(), "image", "image/gif"), (webp_bytes(), "image", "image/webp"), (PDF, "pdf", "application/pdf"),
    (MP3, "audio", "audio/mpeg"), (OGG, "audio", "audio/ogg"), (wav_bytes(), "audio", "audio/wav"), (M4A, "audio", "audio/mp4"),
])
def test_each_kind_is_stored_and_served_with_the_exact_type(gm, anon, hid, raw, kind, mime):
    h = put(gm, hid, raw, "файл.bin")
    assert h["kind"] == kind and h["size"] > 0
    r = anon.get(f"/handout/{h['file']}/view")
    assert r.status_code == 200 and r.headers["content-type"].split(";")[0] == mime
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["accept-ranges"] == "bytes"
    assert r.headers["content-disposition"] == "inline" and "content-security-policy" not in r.headers
    assert r.headers["cross-origin-resource-policy"] == "same-origin" and r.headers["referrer-policy"] == "no-referrer"
    if kind != "image":
        assert r.content == raw                                                  # PDF и звук хранятся и отдаются как есть
    if mime == "image/gif":
        assert r.content == raw                                                  # анимация сохраняется


def test_html_is_still_gzipped_in_a_sandbox(gm, anon, hid):
    h = put(gm, hid, HTML)
    assert h["kind"] == "html"
    r = anon.get(f"/handout/{h['file']}/view", headers={"Accept-Encoding": "identity"})
    assert r.content == HTML and r.headers["content-security-policy"].startswith("sandbox") and "text/html" in r.headers["content-type"]
    row = db.conn().execute("SELECT mime, encoding FROM handout_files WHERE token=?", (h["file"],)).fetchone()
    assert (row["mime"], row["encoding"]) == ("text/html", "gzip")


def test_replacing_a_file_changes_its_kind_and_drops_the_old_one(gm, anon, hid):
    first = put(gm, hid, HTML)
    second = put(gm, hid, PDF)
    assert second["kind"] == "pdf" and second["file"] != first["file"]
    assert anon.get(f"/handout/{first['file']}/view").status_code == 404
    assert anon.get(f"/handout/{second['file']}/view").headers["content-type"] == "application/pdf"


def test_server_owned_fields_survive_editing_the_description(gm, hid):
    h = put(gm, hid, png_bytes(), "карта.png")
    data = ok(gm.post("/api/gm/items/handouts", json=dict(h, title="Файловая раздатка", note="Новое описание")))
    after = card(data["state"], hid)
    assert after["kind"] == "image" and after["file"] == h["file"] and after["fname"] == "карта.png" and after["note"] == "Новое описание"


def test_default_names_and_players_see_the_kind_but_not_the_file_name(gm, rig, hid):
    h = put(gm, hid, PDF, "")
    assert h["fname"] == "раздатка.pdf"
    put(gm, hid, png_bytes(), "СЕКРЕТНОЕ_имя.png")
    mine = card(rig.get("/api/state").json(), hid)
    assert mine["kind"] == "image" and "fname" not in mine and "gm_note" not in mine and "СЕКРЕТ" not in str(mine)


# ---------------------------------------------------------------- картинки

def test_image_is_reencoded_without_metadata_and_rotated(gm, anon, hid):
    raw = jpeg_with_exif((40, 20))
    assert b"SecretMakerXYZ" in raw
    h = put(gm, hid, raw)
    out = anon.get(f"/handout/{h['file']}/view").content
    assert b"SecretMakerXYZ" not in out and not Image.open(io.BytesIO(out)).getexif()
    assert Image.open(io.BytesIO(out)).size == (20, 40)                           # поворот из метки применён


def test_png_with_text_chunks_loses_them_and_keeps_transparency(gm, anon, hid):
    from PIL import PngImagePlugin
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "СекретныйАвтор")
    src = io.BytesIO()
    Image.new("RGBA", (10, 10), (1, 2, 3, 128)).save(src, "PNG", pnginfo=info)
    h = put(gm, hid, src.getvalue())
    out = anon.get(f"/handout/{h['file']}/view").content
    img = Image.open(io.BytesIO(out))
    assert "СекретныйАвтор".encode() not in out and img.mode == "RGBA" and img.getpixel((0, 0)) == (1, 2, 3, 128)


@pytest.mark.parametrize("raw", [
    b"\x89PNG\r\n\x1a\n" + "мусор".encode() * 20, b"\xff\xd8\xff" + b"\x00" * 50, b"GIF89a" + b"\x00" * 50, b"RIFF\x00\x00\x00\x00WEBPjunk",
    png_bytes()[:40],                                                             # обрезанная картинка
])
def test_broken_images_are_refused_politely(gm, hid, raw):
    r = upload(gm, hid, raw)
    assert r.status_code == 400 and "не читается" in r.json()["detail"]


def test_huge_dimensions_are_refused(gm, hid):
    out = io.BytesIO()
    Image.new("L", (9000, 9000), 0).save(out, "PNG")                              # 81 мегапиксель, а сжимается в крошки
    assert len(out.getvalue()) < 1_000_000
    r = upload(gm, hid, out.getvalue())
    assert r.status_code == 400 and "слишком большая" in r.json()["detail"]


def test_just_over_our_own_pixel_limit_is_refused_but_below_it_passes(gm, hid):
    over = io.BytesIO()
    Image.new("L", (8000, 7700), 0).save(over, "PNG")                             # 61,6 мегапикселя: выше нашего предела, ниже предела Pillow
    r = upload(gm, hid, over.getvalue())
    assert r.status_code == 400 and "слишком большая" in r.json()["detail"] and "60" in r.json()["detail"]
    under = io.BytesIO()
    Image.new("L", (3000, 2000), 0).save(under, "PNG")
    assert upload(gm, hid, under.getvalue()).status_code == 200


def test_decompression_bomb_message_is_not_a_server_error(gm, hid):
    out = io.BytesIO()
    Image.new("L", (20000, 20000), 0).save(out, "PNG")                            # 400 мегапикселей, за пределом даже «предупреждения» Pillow
    r = upload(gm, hid, out.getvalue())
    assert r.status_code == 400 and "слишком большая" in r.json()["detail"]


# ---------------------------------------------------------------- PDF и текст

def test_truncated_pdf_is_refused(gm, hid):
    r = upload(gm, hid, PDF.replace(b"%%EOF", b""))
    assert r.status_code == 400 and "обрезан" in r.json()["detail"]


def test_html_pretending_to_be_a_pdf_never_runs_as_html(gm, anon, hid):
    sneaky = b"%PDF-1.4\n<html><script>window.x=1</script></html>\n%%EOF"
    h = put(gm, hid, sneaky)
    r = anon.get(f"/handout/{h['file']}/view")
    assert r.headers["content-type"] == "application/pdf" and r.headers["x-content-type-options"] == "nosniff"


def test_unknown_binary_is_refused_with_the_list_of_supported_types(gm, hid):
    r = upload(gm, hid, b"\x00\x01\x02\x03binary" * 10)
    assert r.status_code == 400 and "PDF" in r.json()["detail"] and "аудио" in r.json()["detail"]
    assert upload(gm, hid, b"   \n  ").status_code == 400


# ---------------------------------------------------------------- Range

def test_range_requests_for_seeking(gm, anon, hid):
    h = put(gm, hid, MP3)
    url = f"/handout/{h['file']}/view"
    size = len(anon.get(url).content)
    r = anon.get(url, headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and r.headers["content-range"] == f"bytes 0-9/{size}" and len(r.content) == 10
    r = anon.get(url, headers={"Range": "bytes=-5"})
    assert r.status_code == 206 and r.headers["content-range"] == f"bytes {size - 5}-{size - 1}/{size}" and len(r.content) == 5
    r = anon.get(url, headers={"Range": "bytes=100-"})
    assert r.status_code == 206 and r.headers["content-range"] == f"bytes 100-{size - 1}/{size}"
    r = anon.get(url, headers={"Range": f"bytes=5-{size * 10}"})
    assert r.status_code == 206 and r.headers["content-range"] == f"bytes 5-{size - 1}/{size}"
    r = anon.get(url, headers={"Range": f"bytes={size}-"})
    assert r.status_code == 416 and r.headers["content-range"] == f"bytes */{size}"
    r = anon.get(url, headers={"Range": "bytes=9-3"})
    assert r.status_code == 416
    for weird in ("bytes=abc", "bytes=1-2,5-6", "items=0-5", "bytes=-", "bytes=0-5; evil", ""):
        assert anon.get(url, headers={"Range": weird}).status_code == 200, weird


def test_range_of_a_downloaded_part_matches_the_whole(gm, anon, hid):
    h = put(gm, hid, MP3)
    url = f"/handout/{h['file']}/view"
    whole = anon.get(url).content
    assert anon.get(url, headers={"Range": "bytes=3-20"}).content == whole[3:21]


# ---------------------------------------------------------------- доступ, лимиты, корзина

def test_media_follows_the_same_access_rules_as_html(gm, anon, hid):
    h = put(gm, hid, png_bytes())
    token = h["file"]
    narrowed = ok(gm.post("/api/gm/items/handouts", json=dict(h, vis="знают", known=["rig"])))
    new = card(narrowed["state"], hid)["file"]
    assert new != token and anon.get(f"/handout/{token}/view").status_code == 404 and anon.get(f"/handout/{new}/view").status_code == 200
    ok(gm.post("/api/gm/items/handouts", json=dict(h, vis="мастер", known=[])))
    assert anon.get(f"/handout/{new}/view").status_code == 404


def test_quota_counts_stored_bytes(gm, hid, monkeypatch):
    base = handouts.usage()["used"]
    monkeypatch.setattr(handouts.config, "HANDOUT_QUOTA_MB", (base + 300) / 1048576)
    r = upload(gm, hid, MP3)                                                      # около 400 байт: не влезает
    assert r.status_code == 413 and "заполнено" in r.json()["detail"]
    monkeypatch.setattr(handouts.config, "HANDOUT_QUOTA_MB", (base + 5000) / 1048576)
    assert upload(gm, hid, MP3).status_code == 200


def test_upload_size_limit_applies_to_media(gm, hid, monkeypatch):
    monkeypatch.setattr(handouts.config, "HANDOUT_MAX_UPLOAD_MB", 0.0005)         # 524 байта
    assert upload(gm, hid, MP3 + b"\x00" * 600).status_code == 413


def test_trash_and_restore_keep_the_type(gm, anon, hid):
    h = put(gm, hid, PDF, "письмо.pdf")
    ok(gm.post(f"/api/gm/items/handouts/{hid}/delete"))
    assert anon.get(f"/handout/{h['file']}/view").status_code == 404
    t = next(t for t in ok(gm.get("/api/gm/trash"))["items"] if t["title"] == "Файловая раздатка")
    data = ok(gm.post(f"/api/gm/trash/{t['id']}/restore"))
    back = card(data["state"], hid)
    assert back["kind"] == "pdf" and anon.get(f"/handout/{back['file']}/view").headers["content-type"] == "application/pdf"


# ---------------------------------------------------------------- миграция

def test_old_files_become_gzipped_html_after_migration(tmp_path):
    old = tmp_path / "portal.db"
    c = sqlite3.connect(old)
    c.executescript(db.SCHEMA)
    c.execute("INSERT INTO handout_files(token,item_id,data,bytes,raw_bytes) VALUES('t1','h1',x'1f8b',2,10)")
    c.commit()
    c.close()
    code = ("from app import db; db.init(); db.init(); r = db.conn().execute('SELECT mime, encoding FROM handout_files').fetchone(); "
            "print(db.schema_version(), db.LATEST, r['mime'], r['encoding'])")
    env = dict(os.environ, DATA_DIR=str(tmp_path), CONFIG_DIR=str(tmp_path))
    version, latest, mime, encoding = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout.split()
    assert version == latest and (mime, encoding) == ("text/html", "gzip")
