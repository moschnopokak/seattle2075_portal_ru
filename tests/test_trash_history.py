"""Корзина, журнал изменений, откат правок и миграции базы."""
import os
import sqlite3
import subprocess
import sys
import time


from app import audit, db, trash
from helpers import create, entry, ok, png, remove

HANDOUT = "<!doctype html><html><body><h1>x</h1></body></html>".encode()


def history(gm, **params):
    return ok(gm.get("/api/gm/history", params=params))["items"]


def trash_items(gm):
    return ok(gm.get("/api/gm/trash"))["items"]


def find_trash(gm, kind, title):
    return next((t for t in trash_items(gm) if t["kind"] == kind and t["title"] == title), None)


# ---------------------------------------------------------------- миграции

def test_fresh_database_is_at_the_latest_version(started):
    assert db.schema_version() == db.LATEST >= 2
    tables = {r[0] for r in db.conn().execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"audit", "trash"} <= tables


def test_old_database_is_migrated_and_keeps_its_data(tmp_path):
    """База старой схемы (до журнала): при запуске получает новые таблицы и столбцы, данные целы, повтор безопасен."""
    old = tmp_path / "portal.db"
    c = sqlite3.connect(old)
    c.executescript(db.SCHEMA)
    c.execute("INSERT INTO portraits(token,size,card_id,data,bytes) VALUES('t1','f','n1',x'00',1)")
    c.execute("INSERT INTO handout_files(token,item_id,data,bytes,raw_bytes) VALUES('t2','h1',x'00',1,1)")
    c.execute("INSERT INTO meta(key,value) VALUES('mark','до миграции')")
    c.commit()
    assert c.execute("PRAGMA user_version").fetchone()[0] == 0
    c.close()
    code = ("from app import db; db.init(); db.init(); c = db.conn(); "
            "print(db.schema_version(), db.LATEST, "
            "c.execute(\"SELECT trashed FROM portraits\").fetchone()[0], c.execute(\"SELECT trashed FROM handout_files\").fetchone()[0], "
            "c.execute(\"SELECT value FROM meta WHERE key='mark'\").fetchone()[0], "
            "c.execute(\"SELECT COUNT(*) FROM audit\").fetchone()[0], c.execute(\"SELECT COUNT(*) FROM trash\").fetchone()[0])")
    env = dict(os.environ, DATA_DIR=str(tmp_path), CONFIG_DIR=str(tmp_path))
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout.split()
    version, latest, p_trashed, h_trashed, mark1, mark2, n_audit, n_trash = out[0], out[1], out[2], out[3], out[4], out[5], out[6], out[7]
    assert version == latest and (p_trashed, h_trashed) == ("0", "0")
    assert f"{mark1} {mark2}" == "до миграции" and (n_audit, n_trash) == ("0", "0")


# ---------------------------------------------------------------- журнал

def test_entry_lifecycle_is_audited_with_actor_and_changes(gm, gate, rig):
    e = create(gate, char="gate", title="Журнальная встреча", who=["rig"])
    eid = e["id"]
    try:
        ok(rig.post(f"/api/entries/{eid}/act", json={"act": "ans", "v": "да", "char": "rig"}))
        ok(gate.post(f"/api/entries/{eid}/edit", json=entry(char="gate", title="Журнальная встреча", who=["rig"], where="Бар «Тузы»", **{"from": "2075-08-07", "to": "2075-08-07"})))
        rows = history(gm, item=eid)
        actions = [r["action"] for r in rows]
        assert actions == ["edit", "act:ans", "create"]                   # новые сверху
        edit_row = rows[0]
        assert edit_row["actor"] == "Игрок Гейта" and edit_row["role"] == "player" and edit_row["kind"] == "entry"
        fields = {c["field"]: c for c in edit_row["changes"]}
        assert fields["where"]["after"] == "Бар «Тузы»" and fields["where"]["before"] == ""
        assert "from" in fields and "chat" not in fields and "created" not in fields
        assert rows[1]["actor"] == "Игрок Рига"
    finally:
        remove(gm, eid)


def test_players_cannot_read_history_or_trash(players, anon):
    for c in list(players.values()) + [anon]:
        for method, url in (("get", "/api/gm/history"), ("get", "/api/gm/trash"), ("post", "/api/gm/trash/empty"),
                            ("post", "/api/gm/trash/1/restore"), ("post", "/api/gm/trash/1/purge"), ("post", "/api/gm/history/1/revert")):
            r = getattr(c, method)(url)
            assert r.status_code in (401, 403), (url, r.status_code)


def test_history_filters_search_and_paging(gm):
    titles = [f"Страничный таймер {i}" for i in range(5)]
    ids = []
    try:
        for t in titles:
            data = ok(gm.post("/api/gm/items/clocks", json={"title": t, "note": "n"}))
            ids.append(next(c["id"] for c in data["state"]["clocks"] if c["title"] == t))
        newest = history(gm, limit=3, kind="clocks")
        assert [r["title"] for r in newest] == titles[::-1][:3]
        older = history(gm, limit=3, kind="clocks", before=newest[-1]["id"])
        assert older[0]["title"] == titles[1]
        assert [r["title"] for r in history(gm, q="Страничный таймер 3")] == ["Страничный таймер 3"]
        assert history(gm, q="%") == [] and history(gm, q="_") == []        # подстановочные знаки LIKE не работают как шаблон
        assert all(r["actor"] == "Мастер" for r in history(gm, q="Мастер", limit=5))
        assert len(history(gm, limit=100000)) <= 200                          # верхняя граница
    finally:
        for i in ids:
            gm.post(f"/api/gm/items/clocks/{i}/delete")


def test_time_changes_are_audited_and_can_be_reverted(gm):
    before = gm.get("/api/state").json()["now"]
    try:
        ok(gm.post("/api/gm/time", json={"shift": 4, "tod": "ночь"}))
        row = history(gm, kind="time")[0]
        assert row["action"] == "time" and {c["field"] for c in row["changes"]} >= {"date"}
        ok(gm.post(f"/api/gm/history/{row['id']}/revert"))
        assert gm.get("/api/state").json()["now"] == before
        assert history(gm, kind="time")[0]["action"] == "revert"
    finally:
        gm.post("/api/gm/time", json={"date": before["date"], "tod": before["tod"]})


# ---------------------------------------------------------------- корзина: записи

def test_deleted_entry_goes_to_trash_with_its_chat_and_can_be_restored(gm, gate, rig):
    e = create(gate, char="gate", title="Удаляемая встреча", who=["rig"])
    eid = e["id"]
    ok(rig.post(f"/api/entries/{eid}/messages", json={"char": "rig", "text": "первое"}))
    ok(gate.post(f"/api/entries/{eid}/messages", json={"char": "gate", "text": "второе"}))
    ok(gate.post(f"/api/entries/{eid}/act", json={"act": "del", "char": "gate"}))
    assert all(x["id"] != eid for x in gm.get("/api/state").json()["entries"])
    row = find_trash(gm, "entry", "Удаляемая встреча")
    assert row and row["by"] == "Игрок Гейта" and row["days_left"] >= 29
    assert gm.get("/api/state").json()["trash"] >= 1
    assert gate.get("/api/state").json()["trash"] is None                    # игрок про корзину не знает
    assert history(gm, item=eid)[0]["action"] == "delete"
    ok(gm.post(f"/api/gm/trash/{row['id']}/restore"))
    back = next(x for x in gm.get("/api/state").json()["entries"] if x["id"] == eid)
    assert [m["t"] for m in back["chat"]] == ["первое", "второе"]
    assert back["created"] == e["created"] and back["answers"] == e["answers"]
    assert find_trash(gm, "entry", "Удаляемая встреча") is None
    assert history(gm, item=eid)[0]["action"] == "restore"
    assert gm.post(f"/api/gm/trash/{row['id']}/restore").status_code == 404   # дважды нельзя
    remove(gm, eid)


# ---------------------------------------------------------------- корзина: карточки, файлы

def test_deleted_dossier_card_closes_its_portrait_and_restores_with_a_new_link(gm, anon):
    data = ok(gm.post("/api/gm/items/dossier", json={"name": "Корзиночная карточка", "vis": "стол", "gm_note": "g"}))
    cid = next(c["id"] for c in data["state"]["dossier"] if c["name"] == "Корзиночная карточка")
    token = next(c for c in ok(gm.post(f"/api/gm/dossier/{cid}/portrait", content=png()))["state"]["dossier"] if c["id"] == cid)["img"]
    assert anon.get(f"/portrait/{token}/f.webp").status_code == 200
    used_before = gm.get("/api/state").json()["portraits"]["used"]
    ok(gm.post(f"/api/gm/items/dossier/{cid}/delete"))
    assert anon.get(f"/portrait/{token}/f.webp").status_code == 404           # по ссылке уже не открывается
    assert gm.get("/api/state").json()["portraits"]["used"] < used_before     # в лимит не входит
    row = find_trash(gm, "dossier", "Корзиночная карточка")
    ok(gm.post(f"/api/gm/trash/{row['id']}/restore"))
    card = next(c for c in gm.get("/api/state").json()["dossier"] if c["id"] == cid)
    assert card["img"] and card["img"] != token                               # новая ссылка
    assert anon.get(f"/portrait/{card['img']}/f.webp").status_code == 200
    assert anon.get(f"/portrait/{token}/f.webp").status_code == 404
    gm.post(f"/api/gm/items/dossier/{cid}/delete")
    gm.post(f"/api/gm/trash/{find_trash(gm, 'dossier', 'Корзиночная карточка')['id']}/purge")


def test_deleted_handout_closes_its_file_and_restores(gm, anon):
    data = ok(gm.post("/api/gm/items/handouts", json={"title": "Корзиночная раздатка", "date": "2075-08-01", "vis": "стол"}))
    hid = next(h["id"] for h in data["state"]["handouts"] if h["title"] == "Корзиночная раздатка")
    token = next(h for h in ok(gm.post(f"/api/gm/handouts/{hid}/file", content=HANDOUT))["state"]["handouts"] if h["id"] == hid)["file"]
    assert anon.get(f"/handout/{token}/view").status_code == 200
    ok(gm.post(f"/api/gm/items/handouts/{hid}/delete"))
    assert anon.get(f"/handout/{token}/view").status_code == 404
    row = find_trash(gm, "handouts", "Корзиночная раздатка")
    ok(gm.post(f"/api/gm/trash/{row['id']}/restore"))
    new = next(h for h in gm.get("/api/state").json()["handouts"] if h["id"] == hid)["file"]
    assert new != token and anon.get(f"/handout/{new}/view").status_code == 200
    gm.post(f"/api/gm/items/handouts/{hid}/delete")
    gm.post(f"/api/gm/trash/{find_trash(gm, 'handouts', 'Корзиночная раздатка')['id']}/purge")
    assert anon.get(f"/handout/{new}/view").status_code == 404


def test_restore_refuses_conflicts(gm):
    w = gm.get("/api/state").json()["windows"][0]
    data = ok(gm.post("/api/gm/items/windows", json={"name": "Временный этап", "from": "2075-12-29", "to": "2075-12-30"}))
    wid = next(x["id"] for x in data["state"]["windows"] if x["name"] == "Временный этап")
    ok(gm.post(f"/api/gm/items/windows/{wid}/delete"))
    ok(gm.post("/api/gm/items/windows", json={"name": "Занявший место", "from": "2075-12-29", "to": "2075-12-31"}))
    row = find_trash(gm, "windows", "Временный этап")
    r = gm.post(f"/api/gm/trash/{row['id']}/restore")
    assert r.status_code == 409 and "пересека" in r.text
    assert find_trash(gm, "windows", "Временный этап")                          # из корзины не пропал
    other = next(x["id"] for x in gm.get("/api/state").json()["windows"] if x["name"] == "Занявший место")
    gm.post(f"/api/gm/items/windows/{other}/delete")
    gm.post(f"/api/gm/trash/{find_trash(gm, 'windows', 'Занявший место')['id']}/purge")
    gm.post(f"/api/gm/trash/{row['id']}/purge")
    assert w


def test_purge_empty_and_expiry(gm):
    ids = []
    for t in ("Корзина А", "Корзина Б", "Корзина В"):
        data = ok(gm.post("/api/gm/items/clocks", json={"title": t}))
        ids.append(next(c["id"] for c in data["state"]["clocks"] if c["title"] == t))
        gm.post(f"/api/gm/items/clocks/{ids[-1]}/delete")
    ok(gm.post(f"/api/gm/trash/{find_trash(gm, 'clocks', 'Корзина А')['id']}/purge"))
    assert find_trash(gm, "clocks", "Корзина А") is None and gm.post("/api/gm/trash/999999/purge").status_code == 404
    # срок хранения: состарим одну запись
    old = find_trash(gm, "clocks", "Корзина Б")
    db.conn().execute("UPDATE trash SET deleted_at=? WHERE id=?", (time.time() - 40 * 86400, old["id"]))
    assert trash.purge_expired() >= 1
    assert find_trash(gm, "clocks", "Корзина Б") is None and find_trash(gm, "clocks", "Корзина В")
    ok(gm.post("/api/gm/trash/empty"))
    assert [t for t in trash_items(gm) if t["title"].startswith("Корзина ")] == []


def test_old_journal_rows_expire(started):
    audit.record(None, "edit", "clocks", "x", "Старая запись")
    db.conn().execute("UPDATE audit SET ts=? WHERE title='Старая запись'", (time.time() - 400 * 86400,))
    assert audit.purge_old(365) >= 1
    assert db.conn().execute("SELECT COUNT(*) FROM audit WHERE title='Старая запись'").fetchone()[0] == 0


# ---------------------------------------------------------------- откат

def test_revert_edit_restores_previous_values_but_keeps_file_links(gm, anon):
    data = ok(gm.post("/api/gm/items/dossier", json={"name": "Откатываемая", "role": "было", "vis": "стол"}))
    cid = next(c["id"] for c in data["state"]["dossier"] if c["name"] == "Откатываемая")
    token = next(c for c in ok(gm.post(f"/api/gm/dossier/{cid}/portrait", content=png()))["state"]["dossier"] if c["id"] == cid)["img"]
    card = next(c for c in gm.get("/api/state").json()["dossier"] if c["id"] == cid)
    try:
        ok(gm.post("/api/gm/items/dossier", json=dict(card, role="стало", gm_note="новая заметка")))
        row = next(r for r in history(gm, item=cid) if r["action"] == "edit")
        assert {c["field"] for c in row["changes"]} == {"role", "gm_note"}
        ok(gm.post(f"/api/gm/history/{row['id']}/revert"))
        back = next(c for c in gm.get("/api/state").json()["dossier"] if c["id"] == cid)
        assert back["role"] == "было" and back["gm_note"] == "" and back["img"] == token    # картинка не потеряна
        assert anon.get(f"/portrait/{token}/f.webp").status_code == 200
        assert history(gm, item=cid)[0]["action"] == "revert"
    finally:
        gm.post(f"/api/gm/items/dossier/{cid}/delete")
        gm.post(f"/api/gm/trash/{find_trash(gm, 'dossier', 'Откатываемая')['id']}/purge")


def test_revert_narrowing_visibility_rotates_the_file_link(gm, anon):
    data = ok(gm.post("/api/gm/items/handouts", json={"title": "Откат видимости", "date": "2075-08-01", "vis": "знают", "known": ["rig"]}))
    hid = next(h["id"] for h in data["state"]["handouts"] if h["title"] == "Откат видимости")
    token = next(h for h in ok(gm.post(f"/api/gm/handouts/{hid}/file", content=HANDOUT))["state"]["handouts"] if h["id"] == hid)["file"]
    item = next(h for h in gm.get("/api/state").json()["handouts"] if h["id"] == hid)
    try:
        ok(gm.post("/api/gm/items/handouts", json=dict(item, vis="стол", known=[])))          # открыли всем
        row = next(r for r in history(gm, item=hid) if r["action"] == "edit")
        ok(gm.post(f"/api/gm/history/{row['id']}/revert"))                                    # откат: снова только Рига
        new = next(h for h in gm.get("/api/state").json()["handouts"] if h["id"] == hid)
        assert new["vis"] == "знают" and new["file"] != token                                  # потеряли доступ: ссылка сменилась
        assert anon.get(f"/handout/{token}/view").status_code == 404
    finally:
        gm.post(f"/api/gm/items/handouts/{hid}/delete")
        gm.post(f"/api/gm/trash/{find_trash(gm, 'handouts', 'Откат видимости')['id']}/purge")


def test_revert_create_and_delete(gm, gate):
    data = ok(gm.post("/api/gm/items/clocks", json={"title": "Откат добавления"}))
    cid = next(c["id"] for c in data["state"]["clocks"] if c["title"] == "Откат добавления")
    row = next(r for r in history(gm, item=cid) if r["action"] == "create")
    ok(gm.post(f"/api/gm/history/{row['id']}/revert"))                      # добавление отменено: в корзине
    assert all(c["id"] != cid for c in gm.get("/api/state").json()["clocks"]) and find_trash(gm, "clocks", "Откат добавления")
    drow = next(r for r in history(gm, item=cid) if r["action"] == "delete")
    ok(gm.post(f"/api/gm/history/{drow['id']}/revert"))                     # удаление отменено: вернулась
    assert any(c["id"] == cid for c in gm.get("/api/state").json()["clocks"])
    gm.post(f"/api/gm/items/clocks/{cid}/delete")
    gm.post(f"/api/gm/trash/{find_trash(gm, 'clocks', 'Откат добавления')['id']}/purge")
    # запись: отмена создания
    e = create(gate, char="gate", title="Откат записи", who=["gate"])
    crow = next(r for r in history(gm, item=e["id"]) if r["action"] == "create")
    ok(gm.post(f"/api/gm/history/{crow['id']}/revert"))
    assert find_trash(gm, "entry", "Откат записи")
    gm.post(f"/api/gm/trash/{find_trash(gm, 'entry', 'Откат записи')['id']}/purge")


def test_revert_errors(gm, gate):
    assert gm.post("/api/gm/history/999999/revert").status_code == 404
    e = create(gate, char="gate", title="Откат ошибок", who=["gate"])
    eid = e["id"]
    ok(gate.post(f"/api/entries/{eid}/edit", json=entry(char="gate", title="Откат ошибок", who=["gate"], where="x")))
    edit_row = next(r for r in history(gm, item=eid) if r["action"] == "edit")
    ok(gate.post(f"/api/entries/{eid}/act", json={"act": "del", "char": "gate"}))
    r = gm.post(f"/api/gm/history/{edit_row['id']}/revert")                  # запись удалена: сначала восстановить
    assert r.status_code == 409 and "корзин" in r.text
    ok(gm.post(f"/api/gm/trash/{find_trash(gm, 'entry', 'Откат ошибок')['id']}/restore"))
    assert history(gm, item=eid)                                             # журнал пережил удаление и восстановление
    restore_row = next(r for r in history(gm, item=eid) if r["action"] == "restore")
    assert gm.post(f"/api/gm/history/{restore_row['id']}/revert").status_code == 400     # восстановление откатывать нельзя
    remove(gm, eid)
    gm.post(f"/api/gm/trash/{find_trash(gm, 'entry', 'Откат ошибок')['id']}/purge")


def test_hostile_titles_are_returned_as_plain_data(gm):
    title = '"><img src=x onerror=__xss=1>'
    data = ok(gm.post("/api/gm/items/clocks", json={"title": title}))
    cid = next(c["id"] for c in data["state"]["clocks"] if c["title"] == title)
    gm.post(f"/api/gm/items/clocks/{cid}/delete")
    assert any(r["title"] == title for r in history(gm, item=cid))
    assert find_trash(gm, "clocks", title)
    gm.post(f"/api/gm/trash/{find_trash(gm, 'clocks', title)['id']}/purge")


def test_uploads_and_notes_are_audited(gm):
    before = history(gm, limit=1)[0]["id"]
    data = ok(gm.post("/api/gm/items/dossier", json={"name": "Журнал файлов", "vis": "стол"}))
    cid = next(c["id"] for c in data["state"]["dossier"] if c["name"] == "Журнал файлов")
    ok(gm.post(f"/api/gm/dossier/{cid}/portrait", content=png()))
    ok(gm.post(f"/api/gm/dossier/{cid}/portrait/delete"))
    ok(gm.post("/api/gm/district/downtown", json={"text": "Новый текст района", "gm_text": "g"}))
    new = [r for r in history(gm, limit=50) if r["id"] > before]
    kinds = {(r["kind"], r["action"]) for r in new}
    assert {("dossier", "create"), ("dossier", "upload"), ("dossier", "file-delete"), ("dnote", "edit")} <= kinds
    gm.post(f"/api/gm/items/dossier/{cid}/delete")
    gm.post(f"/api/gm/trash/{find_trash(gm, 'dossier', 'Журнал файлов')['id']}/purge")
