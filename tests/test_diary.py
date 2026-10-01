"""«Мой дневник»: что попадает в Markdown и PDF, что нет, форматы, права, лимиты, мусор."""
import io

import pytest
from pypdf import PdfReader

from app import diary
from helpers import create, entry, ok, remove

SECRET = "СЕКРЕТ"
HTML = "<!doctype html><html><body><h1>Раздатка</h1></body></html>".encode()


@pytest.fixture(autouse=True)
def fresh_limiter():
    from app import main
    main._diary_times.clear()
    yield
    main._diary_times.clear()


def md(client, **params):
    r = client.get("/api/me/diary", params=dict({"format": "md"}, **params))
    assert r.status_code == 200, (r.status_code, r.text[:200])
    return r.text


def pdf_text(client, **params):
    r = client.get("/api/me/diary", params=dict({"format": "pdf"}, **params))
    assert r.status_code == 200, (r.status_code, r.text[:200])
    reader = PdfReader(io.BytesIO(r.content))
    return "\n".join(p.extract_text() for p in reader.pages), r


@pytest.fixture
def story(gm, gate, rig, hag, sandbox):
    """Риг: общая запись с Гейтом, личная запись без него, хроника, сведения, раздатка, нуйены, репутация и контакт."""
    out = {}
    shared = create(gate, char="gate", title="Общее дело", who=["rig"], goal="Встретиться с [[Открытая карточка]] у моста", where="Мост", cond="Без оружия")
    private = ok(hag.post("/api/entries", json=entry(char="hagane", title="Тайные планы Хаганэ", who=["elijah"], vis="лично", goal="ЛИЧНОЕ-ХАГАНЭ")))
    ok(rig.post(f"/api/entries/{shared['id']}/messages", json={"char": "rig", "text": "Я приду с [[Открытая карточка|ним]]"}))
    ok(gate.post(f"/api/entries/{shared['id']}/roll", json={"char": "gate", "dice": 3, "label": "Скрытность"}))
    ok(gm.post("/api/gm/items/past", json={"title": "Прошлое событие", "from": "2075-07-20", "to": "2075-07-21", "note": "Видно всем", "gm_note": f"{SECRET}-хроника", "session": "Сессия 1"}))
    for title, known, note, gm_note in (("Письмо Рига", ["rig"], "Найдено в сейфе", f"{SECRET}-раздатка"), ("Чужое письмо", ["gate"], "Чужое", "")):
        data = ok(gm.post("/api/gm/items/handouts", json={"title": title, "date": "2075-08-01", "vis": "знают", "known": known, "note": note, "gm_note": gm_note}))
        hid = next(h["id"] for h in data["state"]["handouts"] if h["title"] == title)
        ok(gm.post(f"/api/gm/handouts/{hid}/file", content=HTML, headers={"X-File-Name": "f"}))                # раздатка без файла игроку не видна
    fid = ok(gm.post("/api/gm/items/factions", json={"name": "Корпорация Икс", "kind": "corp", "vis": "стол", "note": "Публично о Икс", "gm_note": f"{SECRET}-фракция"}))["state"]["factions"][-1]["id"]
    ok(gm.post("/api/gm/items/standing", json={"char": "rig", "faction": fid, "value": 3, "note": "Помог", "gm_note": f"{SECRET}-репутация"}))
    ok(gm.post("/api/gm/items/money", json={"char": "rig", "delta": 1500, "note": "Награда", "gm_note": f"{SECRET}-деньги"}))
    ok(gm.post("/api/gm/items/money", json={"char": "gate", "delta": 777, "note": "Деньги Гейта"}))
    ok(gm.post("/api/gm/items/contacts", json={"char": "rig", "name": "Фиксер Ли", "connection": 4, "loyalty": 2, "services": "Достаёт железо", "gm_note": f"{SECRET}-контакт"}))
    out["shared"], out["private"] = shared, private
    return out


# ---------------------------------------------------------------- содержание

def test_markdown_has_my_data_and_never_secrets_or_other_peoples_data(story, rig):
    text = md(rig, parts="chron,entries,chat,dossier,handouts,sheet")
    assert text.startswith("---\ntags: [дневник]\nперсонаж: Риг\n") and "# Дневник: Риг" in text
    for needle in ("Общее дело", "Встретиться с [[Открытая карточка]] у моста", "Мост", "Без оружия", "Прошлое событие", "Сессия: Сессия 1", "Видно всем",
                   "Письмо Рига", "Найдено в сейфе", "Корпорация Икс", "+3, Уважение", "Баланс: 1 500 ¥", "Награда", "Фиксер Ли", "Связи 4, лояльность 2",
                   "Я приду с [[Открытая карточка|ним]]", "Скрытность"):
        assert needle in text, needle
    for forbidden in (SECRET, "Тайные планы", "Чужое письмо", "Деньги Гейта", "777"):
        assert forbidden not in text, forbidden


def test_default_parts_leave_out_the_discussions(story, rig):
    text = md(rig)
    assert "Общее дело" in text and "Обсуждения записей" not in text and "Я приду" not in text
    assert "## Хроника" in text and "## Записи" in text and "## Досье" in text and "## Раздатки" in text and "## Лист персонажа" in text


def test_parts_can_be_picked(story, rig):
    text = md(rig, parts="sheet")
    assert "## Лист персонажа" in text and "## Хроника" not in text and "## Записи" not in text and "Общее дело" not in text
    assert "## Хроника" in md(rig, parts="chron") and "Баланс" not in md(rig, parts="chron")


def test_each_player_gets_only_his_own_character(story, gate, rig, hag):
    mine = md(gate)
    assert "Дневник: Гейт" in mine and "Деньги Гейта" in mine and "Общее дело" in mine and "Фиксер Ли" not in mine and "Награда" not in mine
    stranger = md(hag)
    assert "Общее дело" not in stranger and "Тайные планы" in stranger and "ЛИЧНОЕ-ХАГАНЭ" in stranger and "Фиксер Ли" not in stranger and SECRET not in stranger


def test_a_private_entry_appears_only_for_its_participants(story, hag, rig):
    assert "Тайные планы Хаганэ" in md(hag) and "Тайные планы" not in md(rig)


def test_dossier_facts_follow_visibility(story, gm, rig):
    shown = md(rig, parts="dossier")
    assert "Открытая карточка" in shown and "Карточка для Гейта" not in shown and "СЕКРЕТ-скрытая карточка" not in shown and SECRET not in shown


def test_sheet_without_data_says_so(gate, rig, sandbox, gm):
    text = md(rig, parts="sheet")
    assert "Баланс: 0 ¥" in text and text.count("Пока ничего.") >= 2


def test_gm_can_preview_a_players_diary_but_must_name_the_character(story, gm):
    assert "Дневник: Риг" in md(gm, char="rig") and "предпросмотр мастера" in md(gm, char="rig")
    assert SECRET not in md(gm, char="rig", parts="chron,entries,chat,dossier,handouts,sheet")      # заметки мастера и в предпросмотре не попадают
    assert gm.get("/api/me/diary", params={"format": "md"}).status_code == 400
    assert gm.get("/api/me/diary", params={"format": "md", "char": "нет"}).status_code == 400


# ---------------------------------------------------------------- PDF

def test_pdf_is_a_real_pdf_with_the_same_text(story, rig):
    text, r = pdf_text(rig, parts="chron,entries,chat,dossier,handouts,sheet")
    assert r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF-")
    for needle in ("Дневник: Риг", "Общее дело", "Прошлое событие", "Письмо Рига", "Корпорация Икс", "Фиксер Ли", "Награда"):
        assert needle in text, needle
    assert "[[" not in text and "Встретиться с Открытая карточка у моста" in text.replace("\n", " ")      # в PDF ссылки становятся именами
    for forbidden in (SECRET, "Тайные планы", "Деньги Гейта"):
        assert forbidden not in text


def test_pdf_survives_hostile_and_exotic_text(story, gate, rig, gm):
    weird = "Эмодзи 😀 китайский 漢字 нули \x00\x01 [[Нет|такой ссылки]] <b>разметка</b> & &amp; длинное " + "я" * 1500
    e = create(gate, char="gate", title="Странный текст", who=["rig"], goal=weird, where="я" * 110)
    try:
        text, r = pdf_text(rig)
        assert r.status_code == 200 and "Странный текст" in text and "<b>разметка</b>" in text
        assert "\x00" not in text
        assert "?" in text                                                                           # знаки, которых нет в шрифте, заменены
    finally:
        remove(gm, e["id"])


def test_headers_and_file_names(story, rig):
    r = rig.get("/api/me/diary", params={"format": "pdf"})
    cd = r.headers["content-disposition"]
    assert cd.startswith('attachment; filename="diary.pdf"') and "filename*=UTF-8''%D0%94%D0%BD%D0%B5%D0%B2%D0%BD%D0%B8%D0%BA-%D0%A0%D0%B8%D0%B3-2075-" in cd
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
    r = rig.get("/api/me/diary")
    assert r.headers["content-type"].startswith("text/markdown") and 'filename="diary.md"' in r.headers["content-disposition"]


def test_file_name_is_cleaned():
    assert diary.filename({"character": 'Эл/ис: "тест"\n', "date": "2075-08-05"}, "md") == "Дневник-Эл-ис-тест-2075-08-05.md"
    assert diary.filename({"character": "///", "date": "2075-08-05"}, "pdf") == "Дневник-персонаж-2075-08-05.pdf"


# ---------------------------------------------------------------- права и защита

def test_login_is_required(anon):
    assert anon.get("/api/me/diary").status_code == 401


def test_a_player_cannot_ask_for_someone_elses_character(story, rig):
    r = rig.get("/api/me/diary", params={"char": "gate"})
    assert r.status_code == 403
    assert rig.get("/api/me/diary", params={"char": "rig"}).status_code == 200


def test_a_player_without_a_character_gets_a_clear_error(sandbox):
    from conftest import login, NOCHAR
    r = login(NOCHAR).get("/api/me/diary")
    assert r.status_code == 403


@pytest.mark.parametrize("params", [{"format": "docx"}, {"format": ""}, {"format": "md", "parts": "хроника"}, {"format": "md", "parts": "chron,вирус"},
                                    {"format": "md", "parts": ",,"}, {"format": "pdf", "parts": "sheet,../etc"}])
def test_bad_parameters(story, rig, params):
    r = rig.get("/api/me/diary", params=params)
    assert r.status_code in (200, 400), params
    if params.get("format") not in ("md", "pdf") or "вирус" in params.get("parts", "") or "../" in params.get("parts", "") or params.get("parts") == "хроника":
        assert r.status_code == 400


def test_empty_parts_mean_defaults(story, rig):
    assert "## Записи" in md(rig, parts=",,")


def test_flood_is_limited(story, rig, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "DIARIES_PER_MINUTE", 3)
    main._diary_times.clear()
    for _ in range(3):
        assert rig.get("/api/me/diary").status_code == 200
    r = rig.get("/api/me/diary")
    assert r.status_code == 429 and "Слишком часто" in r.json()["detail"]
    main._diary_times.clear()


def test_pdf_fonts_are_bundled_and_cover_cyrillic():
    assert diary.FONT_REGULAR.exists() and diary.FONT_BOLD.exists()
    assert all(ord(c) in diary._supported() for c in "АБВГабвгЁё«»—−¥№")


def test_markdown_text_cannot_break_the_structure(story, gate, rig, gm):
    data = ok(gate.post("/api/entries", json=entry(char="gate", title="Заголовок\n## Подмена", who=["rig"], goal="строка\n- вложенный пункт\n---\n# Ещё заголовок")))
    e = next(x for x in data["state"]["entries"] if x["title"].startswith("Заголовок"))
    try:
        text = md(rig)
        lines = text.split("\n")
        assert not any(line.startswith("## Подмена") or line.startswith("# Ещё заголовок") for line in lines)     # чужой текст не становится заголовком
    finally:
        remove(gm, e["id"])
